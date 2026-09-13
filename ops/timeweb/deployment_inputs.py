"""Compare nonsecret dispatch inputs with their resolved workflow environment.

This is a diagnostic only: it never changes inputs, selects a provider, or grants
an allowance. The event file is GitHub's runner context, not a client request log.
"""
import json
import os
from pathlib import Path
import re


PRESERVE_EXPIRY = 'Сохранить текущий срок'
FIELDS = {
    'build_stats_source': ('NARMA_BUILD_STATS_SOURCE', 'authored'),
    'prepare_chatgpt_auth': ('PREPARE_CHATGPT_AUTH', False),
    'activate_hermes': ('ACTIVATE_HERMES', False),
    'prepare_openai_api': ('PREPARE_OPENAI_API', False),
    'openai_limit_microusd': ('OPENAI_LIMIT_MICROUSD', ''),
    'openai_expires_at': ('OPENAI_EXPIRES_AT', PRESERVE_EXPIRY),
}
FLAGS = {'prepare_chatgpt_auth', 'activate_hermes', 'prepare_openai_api'}


def normalize(name, value):
    if name in FLAGS:
        if type(value) is bool:
            return 'true' if value else 'false'
        if type(value) is str and value in ('true', 'false'):
            return value
        raise ValueError('invalid_boolean')
    if type(value) is not str:
        raise ValueError('invalid_string')
    if name == 'openai_expires_at' and value == PRESERVE_EXPIRY:
        return ''
    return value


def safe_value(name, value):
    """Only fixed enums, bounded digits and ISO-shaped timestamps may be logged."""
    if type(value) is not str:
        return '[invalid]'
    if value == '':
        return '[empty]'
    if name in FLAGS:
        return value if value in ('true', 'false') else '[invalid]'
    if name == 'build_stats_source':
        return value if value in ('authored', 'stratz') else '[invalid]'
    if name == 'openai_limit_microusd':
        return value if re.fullmatch(r'[0-9]{1,8}', value) else '[invalid]'
    if name == 'openai_expires_at':
        return value if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value) else '[invalid]'
    return '[invalid]'


def inspect_inputs(event, environ):
    manual = environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
    inputs = event.get('inputs', {}) if manual and isinstance(event, dict) else {}
    if not isinstance(event, dict) or not isinstance(inputs, dict):
        raise ValueError('invalid_event_shape')
    rows, mismatches, normalized = {}, [], {}
    for name, (env_name, default) in FIELDS.items():
        present = name in inputs
        try:
            expected = normalize(name, inputs[name] if present else default)
        except ValueError:
            expected = None
        actual = environ.get(env_name)
        matches = expected is not None and expected == actual
        rows[name] = {
            'present': present,
            'event': safe_value(name, expected),
            'resolved': safe_value(name, actual),
            'matches': matches,
        }
        normalized[name] = expected
        if not matches:
            mismatches.append(name)
    preserve = (not mismatches
                and all(normalized[name] == 'false' for name in FLAGS)
                and normalized['openai_limit_microusd'] == ''
                and normalized['openai_expires_at'] == '')
    return rows, mismatches, preserve


def main():
    try:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        rows, mismatches, preserve = inspect_inputs(event, os.environ)
    except (KeyError, OSError, ValueError):
        print('::error::Cannot compare workflow input contexts; deployment stopped before provider access.')
        return 1
    print('Deployment input receipt: ' + json.dumps(rows, sort_keys=True))
    if mismatches:
        message = 'Workflow input contexts differ; deployment stopped before provider access.'
        annotation = 'error'
    elif preserve:
        message = 'GitHub передал режим сохранения провайдера; активация OpenAI не выполняется, лимит сохраняется.'
        annotation = 'notice'
    else:
        message = 'Workflow input contexts match. Provider and allowance validation follows; activation is not yet confirmed.'
        annotation = 'notice'
    print('::' + annotation + '::' + message)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        lines = ['Deployment input receipt', '', message, '',
                 '| Input | Present in event | Event value | Resolved value | Match |',
                 '| --- | --- | --- | --- | --- |']
        for name, row in rows.items():
            lines.append('| ' + ' | '.join((name, str(row['present']).lower(), row['event'],
                                             row['resolved'], str(row['matches']).lower())) + ' |')
        try:
            with open(summary, 'a', encoding='utf-8') as handle:
                handle.write('\n'.join(lines) + '\n')
        except OSError:
            print('::error::Cannot write workflow input receipt; deployment stopped before provider access.')
            return 1
    return 1 if mismatches else 0


if __name__ == '__main__':
    raise SystemExit(main())
