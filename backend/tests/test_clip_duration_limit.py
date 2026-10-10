"""Product duration, workflow bounds and saved standard/continuation compatibility."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from app.constants.capability import VIDEO_CAPABILITY_CONTRACTS, clip_duration_maximum
from app.api.shots import _get_video_workflow_capability
from app.services import h3_execution_optimizer as opt
from app.services.shot_video_service import _apply_h3_execution_duration
from app.services.h3_continuation import target_frames
from app.services.clip_validator import validate_clip_plan
from migrations.increase_h3_clip_duration_limit import upgraded_extension


@pytest.mark.parametrize('capability', VIDEO_CAPABILITY_CONTRACTS)
@pytest.mark.parametrize('duration', [4, 13.1, 15, 15.375, 18.5, 20])
def test_all_clip_modes_allow_twenty_without_changing_minimum(capability, duration):
    limits = opt.workflow_duration_limits(capability=capability)
    assert limits['minimum'] == 4 and limits['maximum'] == 20
    assert opt.effective_execution_duration(duration, limits=limits)['effective_duration'] == duration
    clip = {'clip_index': 1, 'start_time': 0, 'end_time': duration, 'capability': capability}
    findings = validate_clip_plan(duration, [clip], [])['blocking']
    assert not any(f['code'] == 'PROVIDER_DURATION_LIMIT' for f in findings)


@pytest.mark.parametrize('extension,expected', [({},20), ({'max_clip_duration':12},12),
    ({'max_clip_duration':15},15), ({'max_seconds':18.5},18.5), ({'max_clip_duration':30},20)])
def test_api_optimizer_and_worker_share_ceiling_and_lower_workflow_limits(extension, expected):
    assert clip_duration_maximum(extension) == expected
    workflow = NS(extension=json.dumps(extension), name='Frozen')
    assert _get_video_workflow_capability(workflow)['max_clip_duration'] == expected
    assert opt.workflow_duration_limits(extension)['maximum'] == expected
    task = NS(metadata_json=json.dumps({'capability':'EXTEND'}))
    assert _apply_h3_execution_duration(task, expected, workflow)[0] == expected
    with pytest.raises(ValueError):
        _apply_h3_execution_duration(task, expected + .01, workflow)


@pytest.mark.parametrize('fixture', ['h3_v5_approved_c1', 'h3_v5_c2_repeated_provenance'])
def test_saved_outputs_still_pass_with_new_limits_and_no_changes(fixture):
    sample = json.loads((Path(__file__).parent/'fixtures'/f'{fixture}.json').read_text())
    before = copy.deepcopy(sample)
    limits = opt.workflow_duration_limits(capability='EXTEND' if 'c2' in fixture else 'GENERATE')
    result = opt.check_authority(sample['raw_prompt'], sample['output'], sample['authority'], sample['initial'], limits)
    assert result['passed'], result['blocking_findings']
    assert sample == before


def test_frame_rounding_and_overlap_unchanged():
    assert target_frames(15) == 362
    assert target_frames(20) == 481
    assert 685 + target_frames(20) - 39 == 1127


def test_migration_changes_only_shipped_default_metadata():
    workflow = NS(is_system=True, file_path='/workflows/multi_reference_video_minimax_h3_ref2va_20260928.json',
        type='multi_reference_video', extension='{"max_clip_duration":15,"max_reference_images":9}')
    assert upgraded_extension(workflow) == {'max_clip_duration':20, 'max_reference_images':9}
    for changes in ({'is_system':False}, {'file_path':'/custom.json'}, {'extension':'{"max_clip_duration":12}'},
                    {'extension':'{"max_clip_duration":20}'}, {'extension':'{"max_clip_duration":15,"max_seconds":12}'}):
        alternative = NS(**{**vars(workflow), **changes})
        assert upgraded_extension(alternative) is None
