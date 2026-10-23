import copy
import json

import pytest

from app.models.task import Task
from app.services.task_service import TaskService


@pytest.mark.parametrize('capability,native', [('GENERATE', False), ('EXTEND', True), ('TEMPORAL_EXTEND', True), ('EXTEND', False)])
def test_task_list_and_detail_preserve_existing_physical_contract_without_inventing_native(capability, native):
    metadata = {
        'execution_scope': 'CLIP', 'clip_index': 2, 'clip_plan_revision': 3,
        'capability': capability, 'approval_status': 'APPROVED',
        'artifact_kind': 'NATIVE_CONTINUITY_OUTPUT' if native else 'CLIP_ONLY',
        'execution_contract': {'capability': capability, 'artifact_kind': 'NATIVE_CONTINUITY_OUTPUT' if native else 'CLIP_ONLY'},
    }
    if native:
        metadata['physical_output'] = {
            'physical_output_role': 'NATIVE_CONTINUITY_OUTPUT', 'overlap_frames': 17,
            'overlap_duration': 17 / 24, 'fps': 24, 'timebase': '1/24',
            'previous': {'generated_by_task_id': 'exact-previous'},
        }
        metadata['execution_contract']['previous_clip'] = {'clip_index': 1, 'generated_by_task_id': 'exact-previous'}
    if capability == 'TEMPORAL_EXTEND':
        metadata['execution_contract']['temporal_anchor_manifest'] = {'anchors': [{'anchor_id': 'KF4', 'frame_position': 234}]}
    before = copy.deepcopy(metadata)
    task = Task(id='projection-task', name='Clip', type='shot_video', status='completed',
                progress=100, result_url='/native.mp4', metadata_json=json.dumps(metadata))
    listed = TaskService.format_task_list([task], {}, {}, {})[0]['clipExecution']
    detailed = TaskService.format_task_detail(task)['clipExecution']
    for key in ('artifact_kind', 'execution_contract', 'physical_output'):
        assert listed.get(key) == detailed.get(key) == before.get(key)
        assert (key in listed) == (key in before)
    assert json.loads(task.metadata_json) == before


def test_non_clip_task_does_not_receive_clip_projection():
    task = Task(id='shot-projection', name='Shot', type='shot_video', status='completed', progress=100,
                metadata_json=json.dumps({'physical_output': {'overlap_frames': 17}}))
    assert TaskService.format_task_list([task], {}, {}, {})[0]['clipExecution'] is None
