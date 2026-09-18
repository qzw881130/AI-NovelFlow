import json
from copy import deepcopy
import pytest
from app.schemas.chapter_shot_split import parse_output
from regression_baseline.treatment_cases import director_output


def test_director_owns_treatment_schema_and_event_references():
    data=director_output(narration=True)
    assert parse_output(json.dumps(data,ensure_ascii=False))['shots'][0]['source_treatments'][0]['type']=='NARRATION'


@pytest.mark.parametrize('damage',['offset','missing_ref','visual_audio_type','duplicate_key'])
def test_treatment_schema_rejects_untrusted_or_missing_fields(damage):
    data=deepcopy(director_output(narration=True))
    treatment=data['shots'][0]['source_treatments'][0]
    if damage=='offset':treatment['source_start']=0
    elif damage=='missing_ref':data['shots'][0]['audio_events'][0].pop('treatment_ref')
    elif damage=='visual_audio_type':treatment.update(type='VISUAL',audio_type='NARRATION')
    else:data['shots'][0]['source_treatments'].append(deepcopy(treatment))
    with pytest.raises(ValueError):parse_output(json.dumps(data,ensure_ascii=False))
