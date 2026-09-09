"""Role changes alter practice, not facts, and cannot turn supports into carries."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from narma_video.role_context import get_role_context
from narma_video.replay_hero_context import build_hero_context
from narma_video.replay_jobs import report_coaching_view
from narma_video.replay_coach import prepare_evidence
from narma_video.hero_pool import trends_for, patterns_for


def factual_report():
    return {
        'player': {'hero': 'npc_dota_hero_viper', 'account_id': 123},
        'metrics': {'last_hits': 23, 'deaths': 1},
        'evidence': [{'id': 'death.1', 'type': 'death', 'time': 420}],
        'economy': [{'time': 600, 'last_hits': 23}],
        'insights': {'training_plan': [{'id': 'farm-check', 'action': 'Old universal farm target'}]},
        'coaching': {'status': 'ready', 'summary': 'Old advice without role provenance'},
    }


def test_same_hero_has_five_distinct_plans_without_relabeling_replay_facts():
    report = factual_report()
    original = deepcopy(report)
    contexts = [build_hero_context(report, position) for position in range(1, 6)]
    assert len({c['training_plan'][0]['action'] for c in contexts}) == 5
    assert len({c['focus'][0]['advice'] for c in contexts}) == 5
    for context in contexts:
        assert context['hero'] == report['player']['hero']
        assert context['focus'][0]['evidence_ids'] == ['death.1']
        assert context['training_plan'][0]['evidence_ids'] == ['death.1']
        view = report_coaching_view(report, context)
        assert view['metrics'] == report['metrics'] and view['evidence'] == report['evidence']
        assert view['economy'] == report['economy']
        assert all(t['id'] != 'farm-check' for t in view['insights']['training_plan'])
        assert view['coaching']['status'] == 'context_changed'
    assert report == original


@pytest.mark.parametrize('position', [None, True, False, '5', 0, 6])
def test_unknown_role_stays_unknown_and_never_uses_carry_farm_plan(position):
    assert get_role_context(position) is None
    report = factual_report()
    context = build_hero_context(report, position)
    assert context['role_context'] is None
    assert report_coaching_view(report, context)['insights']['training_plan'] == []


def test_support_roles_prioritize_different_lane_partners_and_conditional_rotations():
    soft, hard = get_role_context(4), get_role_context(5)
    assert 'офлейнер' in soft['lane_priority'].lower()
    assert 'керри' in hard['lane_priority'].lower()
    assert 'руны' in soft['next_game_action'] or 'мид' in soft['next_game_action']
    assert 'безопасност' in soft['next_game_action']
    assert 'отвод' in hard['next_game_action']
    assert 'не являются ошибкой' in soft['farm_policy']
    assert 'не основная оценка' in hard['farm_policy']
    assert 'не подтверждают' in hard['limits'][1]
    soft['limits'].append('modified')
    assert 'modified' not in get_role_context(4)['limits']


def test_role_guidance_without_events_does_not_manufacture_an_episode():
    report = {'player': {'hero': 'npc_dota_hero_crystal_maiden'}}
    context = build_hero_context(report, 5)
    assert context['role_context']['position'] == 5
    assert context['focus'] == context['training_plan'] == []


def test_model_gets_role_priorities_but_not_old_coach_text_or_other_role():
    report = factual_report()
    report['role_context'] = {'position': 1, 'instructions': 'Untrusted injected context'}
    for position in (1, 4, 5):
        encoded, ids = prepare_evidence(report, position=position)
        payload = json.loads(encoded)
        role = payload['hero_context']['role_context']
        assert role == get_role_context(position)
        assert role['classification'] == 'practice_guidance_not_match_evidence'
        assert ids == {'death.1'}
        assert 'Old advice' not in encoded and 'Untrusted injected' not in encoded
        assert 'training_plan' not in payload['hero_context']


def history(position):
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [{'hero': 'npc_dota_hero_viper', 'position': position,
             'match_id': str(8984479700 + index), 'job_id': str(index),
             'date_source': 'user', 'engine_build': 100,
             'chronology_at': (start + timedelta(days=index)).isoformat(),
             'metrics': {'last_hits_10': index * 10, 'net_worth_10': index * 100,
                         'repeated_deaths': 2, 'item_delay_seconds': 130},
             'evidence': [{'id': 'death.1', 'type': 'death'}]}
            for index in range(6)]


def test_support_farm_trends_preserve_numbers_without_marking_more_as_better():
    for position in (4, 5):
        rows = trends_for(history(position))
        farm = [row for row in rows if row['metric'] in ('last_hits_10', 'net_worth_10')]
        assert all(row['desired_direction'] == 'context' for row in farm)
        assert all(row['direction'] == 'up' and row['delta'] > 0 for row in farm)
        assert all(row['interpretation'] == get_role_context(position)['farm_policy'] for row in farm)
    carry = next(row for row in trends_for(history(1)) if row['metric'] == 'last_hits_10')
    assert carry['desired_direction'] == 'higher'


def test_same_repeated_pattern_has_role_specific_next_action():
    actions = [patterns_for(history(position))[0]['action'] for position in range(1, 6)]
    assert len(set(actions)) == 5


def test_old_matching_role_coaching_is_not_presented_as_the_new_role_method():
    from narma_video.role_context import COACH_METHOD_VERSION
    report = factual_report()
    report['coaching']['context'] = {'hero': report['player']['hero'], 'position': 5,
                                     'method_version': 'narma-coach.v4'}
    context = build_hero_context(report, 5)
    assert report_coaching_view(report, context)['coaching']['status'] == 'context_changed'
    report['coaching']['context']['method_version'] = COACH_METHOD_VERSION
    assert report_coaching_view(report, context)['coaching']['status'] == 'ready'


def test_selected_role_item_basis_does_not_claim_that_role_is_missing():
    report = factual_report()
    report['insights']['items'] = [{'item': 'item_blink', 'time': 900,
        'timing': {'status': 'no_reference', 'basis': 'Роль, рейтинг, патч и условия линии не заданы'}}]
    original = deepcopy(report)
    projected = report_coaching_view(report, build_hero_context(report, 5))
    item = projected['insights']['items'][0]
    assert item['timing']['status'] == 'no_reference' and item['time'] == 900
    assert 'выбранной позиции' in item['timing']['basis']
    assert 'не заданы' not in item['timing']['basis']
    assert report == original
