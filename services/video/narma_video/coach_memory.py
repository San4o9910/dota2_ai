"""Bounded, explicitly selected cross-match context for the same owned player."""
import json

from . import curriculum
from .hero_pool import _load_history
from .learning import _plans


def active_practice(connection, owner_id, current):
    profile, history = _load_history(connection, owner_id, persist=False)
    hero = current['result_payload']['player']['hero']
    return [{'id': str(p['id']), 'exercise_id': p['exercise_id'], 'updated_at': p['updated_at'].isoformat(),
             'source_job_id': str(p['source_job_id']), 'action': p['exercise']['action'],
             'question': p['exercise']['decision_question'], 'measurement': p['exercise']['measurement']}
            for p in _plans(connection, owner_id, profile, history)
            if p['status'] == 'active' and p['validity'] == 'current'
            and p['hero'] == hero and p['position'] == current['current_position']][:1]


def collect(connection, owner_id, current):
    from .coach_chat import _current
    from .replay_coach import prepare_evidence
    _, history = _load_history(connection, owner_id, persist=False)
    hero = current['result_payload']['player']['hero']
    related, sources, references = [], [], []
    if current['current_position'] is not None:
        for fact in history:
            if (fact['match_id'] == current['match_id'] or fact['hero'] != hero
                    or fact['position'] != current['current_position'] or fact.get('report_is_previous')):
                continue
            other = _current(connection, owner_id, fact['job_id'])
            if not other or other['report_sha256'] != fact['report_sha256']:
                continue
            build, old_build = current['result_payload']['coverage'].get('engine_build'), fact.get('engine_build')
            if build is not None and old_build is not None and str(build) != str(old_build):
                continue
            encoded, _ = prepare_evidence(other['result_payload'], **other['chat_context'])
            data = json.loads(encoded)
            prefix = 'match.' + fact['match_id'] + ':'
            # Only the explicitly retained evidence subset is sent. No timelines
            # or numeric aggregates are fabricated from omitted events.
            evidence = data.get('evidence', [])[:24]
            for event in evidence:
                original = event['id']
                event['id'] = prefix + original
                references.append({'id': event['id'], 'evidence_id': original, 'job_id': fact['job_id'],
                    'match_id': fact['match_id'], 'time': event.get('time'), 'type': event.get('type')})
            related.append({'match_id': fact['match_id'], 'hero': hero, 'position': fact['position'],
                'played_at': fact['played_at'], 'date_source': fact['date_source'], 'engine_build': old_build,
                'metrics': fact['metrics'], 'evidence': evidence,
                'coverage_note': 'Отобраны до 24 событий. Отсутствие события в этой выборке ничего не доказывает.'})
            sources.append({'job_id': fact['job_id'], 'report_sha256': other['report_sha256'],
                            'context': other['chat_context'], 'hero': hero})
            if len(related) == 2:
                break
    return related, sources, references, active_practice(connection, owner_id, current)


def valid_sources(connection, owner_id, sources):
    from .coach_chat import _current
    for source in sources:
        row = _current(connection, owner_id, source['job_id'])
        if (not row or row['report_sha256'] != source['report_sha256']
                or row['chat_context'] != source['context'] or row['result_payload']['player']['hero'] != source['hero']):
            return False
    return True


def references(connection, owner_id, turn):
    from .coach_chat import _current
    from .replay_coach import prepare_evidence
    result = []
    sources = [{'job_id': str(turn['job_id']), 'primary': True}, *turn.get('sources', [])]
    for source in sources:
        row = _current(connection, owner_id, source['job_id'])
        if not row:
            continue
        data, _ = prepare_evidence(row['result_payload'], **row['chat_context'])
        events = json.loads(data).get('evidence', [])
        for event in (events if source.get('primary') else events[:24]):
            result.append({'id': event['id'] if source.get('primary') else 'match.' + row['match_id'] + ':' + event['id'],
                'evidence_id': event['id'], 'job_id': str(row['id']), 'match_id': row['match_id'],
                'report_sha256': row['report_sha256'],
                'time': event.get('time'), 'type': event.get('type')})
    return result
