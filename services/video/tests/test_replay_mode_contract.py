"""The selected depth changes both the requested teaching contract and its reader."""
from copy import deepcopy
import pytest
from narma_video import replay_coach as coach, openai_provider as provider
from test_replay_coach import RESULT_V2


def result(level):
    return {**deepcopy(RESULT_V2), 'schema_version': 'narma.replay-coaching.v3', 'training_level': level,
            'lesson': {'first': 'Объяснение понятия.', 'second': 'Условное действие.', 'third': 'Проверка решения.',
                       'evidence_ids': ['buyback.1']}}


def test_every_depth_has_a_distinct_constrained_request():
    digests = set()
    for level, labels in coach.MODE_LESSONS.items():
        instructions, schema, contract = coach.mode_contract(level)
        assert contract == 'narma.replay-coaching.v3'
        assert schema['properties']['training_level']['const'] == level
        assert all(label in instructions for label in labels)
        digests.add(provider.request_digest(instructions, '{}', schema))
    assert len(digests) == 3
    assert coach.mode_contract(None) == (coach.API_SYSTEM_V2, coach.ReplayCoachingV2.model_json_schema(), coach.COACHING_SCHEMA_V2)


@pytest.mark.parametrize('level', list(coach.MODE_LESSONS))
def test_depth_and_all_lesson_fields_are_validated(level):
    data = result(level);ids = {'buyback.1', 'death.1'}
    assert coach.validate_coaching(data, ids, expected_schema='narma.replay-coaching.v3', expected_level=level).training_level == level
    for changed in ({**data, 'training_level': 'advanced' if level != 'advanced' else 'foundations'},
                    {**data, 'lesson': {**data['lesson'], 'second': 'Потерял 999 золота.'}},
                    {**data, 'lesson': {**data['lesson'], 'evidence_ids': ['foreign']}}, RESULT_V2):
        with pytest.raises(ValueError):
            coach.validate_coaching(changed, ids, expected_schema='narma.replay-coaching.v3', expected_level=level)
