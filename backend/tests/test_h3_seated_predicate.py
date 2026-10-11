import copy
import json
from pathlib import Path
import pytest
from app.services.h3_execution_optimizer import check_authority


def sample():
    return json.loads((Path(__file__).parent / 'fixtures/h3_shot5_seated_predicate.json').read_text())


def audit(s):
    return check_authority(s['raw_prompt'], s['output'], s['authority'], s['initial'], s['limits'])


def test_saved_final_sits_at_is_explicit_seated_state_without_prompt_edit():
    s = sample()
    before = copy.deepcopy(s)
    assert audit(s)['passed']
    assert s == before


@pytest.mark.parametrize('predicate', ['sits at', 'is sitting at', 'sits on', 'is sitting in'])
def test_explicit_sitting_location_predicate(predicate):
    s = sample()
    s['output']['optimized_prompt'] = s['output']['optimized_prompt'].replace(
        '<Subject 2> sits at', '<Subject 2> ' + predicate)
    assert audit(s)['checks']['seated_state_preserved_<Subject 2>']


@pytest.mark.parametrize('replacement', [
    '<Subject 2> does not sit at', '<Subject 2> is not sitting at',
    '<Subject 2> sits down at', '<Subject 1> sits at',
])
def test_negation_new_sitting_action_and_other_actor_do_not_satisfy_fixed_state(replacement):
    s = sample()
    s['output']['optimized_prompt'] = s['output']['optimized_prompt'].replace('<Subject 2> sits at', replacement)
    assert not audit(s)['checks']['seated_state_preserved_<Subject 2>']


def test_explicit_standing_conflict_still_fails_independently():
    s = sample()
    s['output']['optimized_prompt'] += '\n<Subject 2> stands up.'
    assert not audit(s)['checks']['no_acquisition_reblocking_<Subject 2>']
