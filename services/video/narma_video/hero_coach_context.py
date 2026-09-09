"""Bounded, owner-scoped preparation for an optional longitudinal coach.

No model, network, database access or paid operation belongs in this module.
The caller must obtain ``pool`` using its authenticated owner's ``get_pool``.
"""
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import math
import re
import unicodedata

from .role_context import get_role_context


CONTEXT_SCHEMA = 'narma.hero-coach-context.v1'
ANNOTATIONS_SCHEMA = 'narma.hero-coach-annotations.v1'
_HERO = re.compile(r'^npc_dota_hero_[a-z0-9_]{1,64}$')
_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
_MATCH_ID = re.compile(r'^[0-9]{8,12}$')
_JOB_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_NUMBER_WORD = re.compile(
    r'\b(?:ноль|нул\w*|один|одна|одно|одну|одного|одной|одним|одном|'
    r'два|две|двух|двум\w*|три|трёх|трех|трем\w*|трём\w*|'
    r'четыр\w*|пят\w*|пятнадцат\w*|шест\w*|сем\w*|семнадцат\w*|'
    r'восем\w*|восьм\w*|девят\w*|десят\w*|одиннадцат\w*|двенадцат\w*|'
    r'тринадцат\w*|четырнадцат\w*|двадцат\w*|тридцат\w*|сорок\w*|'
    r'сто|ста|сот\w*|сотен|сотню|тысяч\w*|миллион\w*|'
    r'вдвое|втрое|вчетверо|впятеро|вдвойне|половин\w*|полтора|полторы|'
    r'zero|one|two|three|four|five|six|seven|eight|nine|ten|'
    r'eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|'
    r'nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|'
    r'hundred|thousand|million|double|triple|twice|half)\b', re.IGNORECASE,
)
_METRICS = {'lh10', 'nw10', 'deaths10', 'dead_pct', 'gpm'}
_FOCUSES = {'item_plan', 'farm_checkpoint', 'safe_return', 'lane_support', 'rotation_window'}
_REFLECTIONS = {'done', 'partial', 'not_done'}


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _encoded(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(',', ':')).encode('utf-8')
    except (ValueError, TypeError):
        raise ValueError('HERO_COACH_CONTEXT_INVALID') from None


def _reference(value):
    if not isinstance(value, Mapping) or set(value) - {'match_id', 'job_id', 'time'}:
        raise ValueError('HERO_COACH_EVIDENCE_MISMATCH')
    match_id, job_id = value.get('match_id'), value.get('job_id')
    if not isinstance(match_id, str) or not _MATCH_ID.fullmatch(match_id):
        raise ValueError('HERO_COACH_EVIDENCE_MISMATCH')
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ValueError('HERO_COACH_EVIDENCE_MISMATCH')
    result = {'match_id': match_id, 'job_id': job_id}
    if 'time' in value:
        if not _number(value['time']) or not -300 <= value['time'] <= 86400:
            raise ValueError('HERO_COACH_EVIDENCE_MISMATCH')
        result['time'] = value['time']
    return result


def _reference_key(value):
    ref = _reference(value)
    # An absent timestamp is different from an invented timestamp of zero.
    return (ref['match_id'], ref['job_id'], 'time' in ref, ref.get('time'))


def _proposed_action(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('HERO_COACH_RESPONSE_INVALID')
    if any(character.isnumeric() for character in value) or _NUMBER_WORD.search(value):
        raise ValueError('HERO_COACH_NUMERIC_CLAIM')
    if any(unicodedata.category(character) in {'Cc', 'Cf', 'Cs'} for character in value):
        raise ValueError('HERO_COACH_RESPONSE_INVALID')
    if any(marker in value.lower() for marker in ('http:', 'https:', 'www.', '<', '>', '```')):
        raise ValueError('HERO_COACH_RESPONSE_INVALID')
    return value.strip()


def build_hero_coach_context(pool: Mapping, *, hero: str, position: int,
                            max_matches: int = 20) -> dict:
    """Select bounded facts from an authenticated, already filtered hero pool.

    Ordering is by Match ID, matching the pool, not by re-upload timestamp.
    Ownership is a caller/database boundary; this helper never accepts an owner
    argument or interprets identity fields as authorization.
    """
    if (not isinstance(hero, str) or not _HERO.fullmatch(hero)
            or type(position) is not int or not 1 <= position <= 5
            or type(max_matches) is not int or not 1 <= max_matches <= 20):
        raise ValueError('HERO_COACH_SCOPE_INVALID')
    if not isinstance(pool, Mapping) or pool.get('schema_version') != 'narma.hero-pool.v1':
        raise ValueError('HERO_COACH_CONTEXT_INVALID')
    scope = pool.get('scope')
    if (not isinstance(scope, Mapping) or scope.get('hero') != hero
            or type(scope.get('position')) is not int or scope['position'] != position):
        raise ValueError('HERO_COACH_SCOPE_INVALID')
    rows = pool.get('matches')
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('HERO_COACH_CONTEXT_INVALID')
    selected, seen = [], set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        if row.get('hero') != hero or type(row.get('position')) is not int or row['position'] != position:
            continue
        ref = _reference({key: row.get(key) for key in ('match_id', 'job_id')})
        if ref['match_id'] in seen:
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        seen.add(ref['match_id'])
        selected.append(row)
    selected.sort(key=lambda row: int(row['match_id']), reverse=True)
    available_count = len(selected)
    selected = selected[:max_matches]
    matches, metrics, builds = [], {}, set()
    for row in selected:
        build = row.get('engine_build')
        if isinstance(build, str) and re.fullmatch(r'[0-9]{1,10}', build):
            build = int(build)
        if build is not None and (type(build) is not int or not 0 < build < 10**10):
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        builds.add(build)
        raw_metrics = row.get('metrics')
        if not isinstance(raw_metrics, Mapping):
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        values, metric_ids = {}, []
        for key in sorted(_METRICS):
            value = raw_metrics.get(key)
            if value is not None and (not _number(value) or value < 0 or (key == 'dead_pct' and value > 100)):
                raise ValueError('HERO_COACH_CONTEXT_INVALID')
            values[key] = value
            metric_id = f"match.{row['match_id']}.{key}"
            metrics[metric_id] = {'kind': key, 'value': value,
                                 'match_id': row['match_id'], 'job_id': row['job_id']}
            metric_ids.append(metric_id)
        outcome = row.get('outcome')
        if outcome not in {'win', 'loss', None}:
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        matches.append({'match_id': row['match_id'], 'job_id': row['job_id'],
                        'engine_build': build, 'outcome': outcome,
                        'metrics': values, 'metric_ids': metric_ids,
                        'practice': {
                            'source': 'self_reported',
                            'focus': row.get('focus') if row.get('focus') in _FOCUSES else None,
                            'reflection': row.get('reflection') if row.get('reflection') in _REFLECTIONS else None,
                        }})
    limitations = ['uploaded_completed_replays_only', 'position_self_reported',
                   'ordered_by_match_id_not_verified_date', 'patch_rank_opponents_not_matched',
                   'metrics_do_not_measure_understanding', 'qualitative_annotations_require_evaluation']
    if not matches:
        limitations.append('no_comparable_matches')
    if None in builds:
        limitations.append('engine_build_missing')
    if len(builds) > 1:
        limitations.append('engine_builds_not_comparable')
    if available_count > max_matches:
        limitations.append('older_matches_excluded')
    known_matches = {(row['match_id'], row['job_id']) for row in matches}
    patterns, pattern_ids = [], set()
    raw_patterns = pool.get('patterns')
    if not isinstance(raw_patterns, list) or len(raw_patterns) > 20:
        raise ValueError('HERO_COACH_CONTEXT_INVALID')
    # The pool's pattern denominator is its latest 20 games. A narrower export
    # must not retain a recurrence claim whose denominator includes hidden rows.
    can_export_patterns = max_matches >= min(available_count, 20) and len(builds) <= 1
    if not can_export_patterns and raw_patterns:
        limitations.append('patterns_excluded_outside_comparable_window')
    for source in raw_patterns if can_export_patterns else []:
        if not isinstance(source, Mapping):
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        pattern_id = source.get('id')
        if (not isinstance(pattern_id, str) or not _ID.fullmatch(pattern_id)
                or not (pattern_id == 'safe_return' or re.fullmatch(r'item_plan_item_[a-z0-9_]{1,80}', pattern_id))
                or pattern_id in pattern_ids):
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        pattern_ids.add(pattern_id)
        count, eligible = source.get('matches'), source.get('eligible_matches')
        if (type(count) is not int or type(eligible) is not int
                or not 3 <= count <= eligible <= len(matches)):
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        title, observation = source.get('title'), source.get('observation')
        if (not isinstance(title, str) or not 1 <= len(title) <= 200
                or not isinstance(observation, str) or not 1 <= len(observation) <= 1000):
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        raw_refs = source.get('evidence')
        if not isinstance(raw_refs, list) or not 1 <= len(raw_refs) <= 20:
            raise ValueError('HERO_COACH_CONTEXT_INVALID')
        evidence, evidence_facts, ref_keys = [], [], set()
        for raw_ref in raw_refs:
            if not isinstance(raw_ref, Mapping):
                raise ValueError('HERO_COACH_CONTEXT_INVALID')
            ref = _reference({key: raw_ref[key] for key in ('match_id', 'job_id', 'time') if key in raw_ref})
            key = _reference_key(ref)
            if key[:2] not in known_matches or key in ref_keys:
                raise ValueError('HERO_COACH_EVIDENCE_MISMATCH')
            ref_keys.add(key)
            event_id = raw_ref.get('event_id')
            if not isinstance(event_id, str) or not _ID.fullmatch(event_id):
                # A historical parse lacking event IDs remains in the pool but
                # is not sufficient evidence for an external agent annotation.
                continue
            evidence.append(ref)
            fact = {**ref, 'event_id': event_id}
            for field in ('previous_time', 'active_time', 'delay_seconds'):
                if field in raw_ref:
                    if not _number(raw_ref[field]) or not -300 <= raw_ref[field] <= 86400:
                        raise ValueError('HERO_COACH_CONTEXT_INVALID')
                    fact[field] = raw_ref[field]
            previous_id = raw_ref.get('previous_event_id')
            if isinstance(previous_id, str) and _ID.fullmatch(previous_id):
                fact['previous_event_id'] = previous_id
            item = raw_ref.get('item')
            if isinstance(item, str) and re.fullmatch(r'item_[a-z0-9_]{1,80}', item):
                fact['item'] = item
            evidence_facts.append(fact)
        if not evidence:
            limitations.append('pattern_event_references_missing')
            continue
        metric_ids = [f'pattern.{pattern_id}.matches', f'pattern.{pattern_id}.eligible_matches']
        metrics[metric_ids[0]] = {'kind': 'recurrence_matches', 'value': count}
        metrics[metric_ids[1]] = {'kind': 'eligible_matches', 'value': eligible}
        patterns.append({'pattern_id': pattern_id, 'title': title, 'observation': observation,
                         'metric_ids': metric_ids, 'evidence': evidence, 'evidence_facts': evidence_facts})
    wins = sum(row['outcome'] == 'win' for row in matches)
    losses = sum(row['outcome'] == 'loss' for row in matches)
    context = {
        'schema_version': CONTEXT_SCHEMA, 'framework_status': 'prepared_not_running',
        'scope': {'hero': hero, 'position': position, 'position_source': 'self_reported',
                  'chronology': 'match_id', 'selected_matches': len(matches), 'max_matches': max_matches},
        'counts': {'matches': len(matches), 'wins': wins, 'losses': losses,
                   'unknown': len(matches) - wins - losses,
                   'winrate': round(wins * 100 / (wins + losses), 1) if wins + losses else None},
        'matches': matches, 'metric_catalog': metrics, 'patterns': patterns,
        'role_context': get_role_context(position),
        'limitations': sorted(set(limitations)),
    }
    encoded = _encoded(context)
    if len(encoded) > 64000:
        raise ValueError('HERO_COACH_CONTEXT_TOO_LARGE')
    context['dataset_version'] = hashlib.sha256(encoded).hexdigest()
    return context


def validate_hero_coach_annotations(payload: Mapping, context: Mapping) -> dict:
    """Validate proposed exercises against existing deterministic patterns only.

    ``context`` is server-generated trusted state, not client-supplied data.
    Fact fields are immutable; only qualitative action/measurement prose may
    differ. This rejects structural and numeric invention, not all semantic
    mistakes; annotations remain separate from the factual report.
    """
    if not isinstance(context, Mapping) or context.get('schema_version') != CONTEXT_SCHEMA:
        raise ValueError('HERO_COACH_CONTEXT_INVALID')
    # Detect accidental version/content mismatch in a stored context; this is
    # integrity checking, not authentication (ownership remains the API's job).
    version = context.get('dataset_version')
    content = {key: value for key, value in context.items() if key != 'dataset_version'}
    if version != hashlib.sha256(_encoded(content)).hexdigest():
        raise ValueError('HERO_COACH_CONTEXT_INVALID')
    if not isinstance(payload, Mapping) or set(payload) != {'patterns'}:
        raise ValueError('HERO_COACH_RESPONSE_INVALID')
    proposed = payload['patterns']
    if not isinstance(proposed, list) or len(proposed) > 3:
        raise ValueError('HERO_COACH_RESPONSE_INVALID')
    source_patterns = context.get('patterns')
    if not isinstance(source_patterns, list):
        raise ValueError('HERO_COACH_CONTEXT_INVALID')
    source_by_id = {row['pattern_id']: row for row in source_patterns}
    matches = {(row['match_id'], row['job_id']) for row in context.get('matches', [])}
    output, seen = [], set()
    for row in proposed:
        required = {'pattern_id', 'title', 'observation', 'action', 'measure', 'evidence'}
        if not isinstance(row, Mapping) or set(row) != required:
            raise ValueError('HERO_COACH_RESPONSE_INVALID')
        pattern_id = row['pattern_id']
        if not isinstance(pattern_id, str) or pattern_id not in source_by_id or pattern_id in seen:
            raise ValueError('HERO_COACH_PATTERN_MISMATCH')
        seen.add(pattern_id)
        source = source_by_id[pattern_id]
        if row['title'] != source['title'] or row['observation'] != source['observation']:
            raise ValueError('HERO_COACH_FACT_OVERRIDE')
        evidence = row['evidence']
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
            raise ValueError('HERO_COACH_EVIDENCE_MISMATCH')
        allowed = {_reference_key(ref) for ref in source['evidence']}
        references, used = [], set()
        for ref in evidence:
            key = _reference_key(ref)
            if key not in allowed or key in used or key[:2] not in matches:
                raise ValueError('HERO_COACH_EVIDENCE_MISMATCH')
            used.add(key)
            references.append(_reference(ref))
        output.append({
            'pattern_id': pattern_id, 'title': source['title'],
            'observation': source['observation'],
            'metric_ids': deepcopy(source.get('metric_ids', [])),
            'action': _proposed_action(row['action'], 400),
            'measure': _proposed_action(row['measure'], 300),
            'evidence': references,
        })
    return {'schema_version': ANNOTATIONS_SCHEMA,
            'dataset_version': context.get('dataset_version'),
            'scope': deepcopy(context.get('scope')), 'patterns': output}
