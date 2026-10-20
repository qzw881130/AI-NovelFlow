"""Limited production adapter: real local fixtures, in-memory DB, fake I/O only."""
import asyncio
import json
import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.models.prompt_template import PromptTemplate
from app.services import h3_phase_b_pipeline as pipe
from app.services import h3_single_stage_experiment as compiler
from app.services.comfyui.service import ComfyUIService
from app.services.comfyui.workflows import WorkflowBuilder

ROOT = Path(__file__).parent / 'fixtures/h3_multi_keyframe_phase_b'
NAMES = ['shot12_c1_generate', 'shot3_c6_extend', 'shot5_c2_temporal_extend']


def saved(name, suffix=''):
    return json.loads((ROOT / (name + suffix + '.json')).read_text())


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Unexpected real external stage')
    from app.services.llm_service import LLMService
    from app.services.comfyui.client import ComfyUIClient
    monkeypatch.setattr(LLMService, 'chat_completion', forbidden)
    monkeypatch.setattr(ComfyUIClient, 'queue_prompt', forbidden)
    monkeypatch.setattr(ComfyUIClient, 'upload_image', forbidden)
    monkeypatch.setattr(ComfyUIClient, 'upload_video', forbidden)
    monkeypatch.setattr('app.services.h3_execution_optimizer.optimize_h3_execution_prompt', forbidden)
    monkeypatch.setattr('app.services.h3_preflight_repair.repair_output', forbidden)


def make_case(db, name, *, silent=False):
    snap = saved(name)
    if silent:
        # Synthetic no-dialogue variant: real states/resources, no production mutation.
        snap['canonical_plan']['dialogue_timeline_source'] = []
        snap['builder_input']['dialogue_timeline_source'] = []
    workflow = SimpleNamespace(**snap['workflow'], extension='{}')
    binder = snap['physical_evidence'].get('reference_binder')
    if binder:
        workflow.workflow_json = Path(binder['template_path']).read_text()
    workflow.name = 'existing frozen workflow'
    novel = Novel(title='offline Phase B')
    db.add(novel); db.flush()
    chapter = Chapter(novel_id=novel.id, title='offline', number=1)
    db.add(chapter); db.flush()
    shot = Shot(chapter_id=chapter.id, index=1, duration=snap['builder_input']['shot']['duration'],
                video_director_plan=json.dumps(snap['canonical_plan']))
    db.add(shot); db.flush()
    selected = PromptTemplate(name='User Phase B version', type=pipe.TEMPLATE_TYPE, is_active=True,
                              is_system=False, template=compiler.PHASE_B_TEMPLATE.read_text()+'\nUSER VERSION\n')
    system = PromptTemplate(name='System Phase B', type=pipe.TEMPLATE_TYPE, is_active=True,
                            is_system=True, template=compiler.PHASE_B_TEMPLATE.read_text())
    db.add_all([selected, system]); db.flush()
    novel.h3_multi_keyframe_director_phase_b_template_id = selected.id
    clip = snap['builder_input']['clip']
    contract = {'previous_clip': snap['physical_evidence'].get('previous_clip'),
                'temporal_anchor_manifest': {'anchors': snap['physical_evidence'].get('temporal_anchors', [])},
                'capability': clip['capability']}
    task = Task(type='shot_video', name='Phase B offline', status='running', novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id, metadata_json=json.dumps({
                    'h3_prompt_pipeline': 'phase_b', 'execution_scope': 'CLIP', 'clip_index': clip['clip_index'],
                    'capability': clip['capability'], 'execution_contract': contract}))
    db.add(task); db.commit()
    args = dict(db=db, task=task, novel=novel, shot=shot, builder_input=snap['builder_input'],
                manifest=snap['reference_manifest'], workflow=workflow, previous_path=snap['previous_video_path'],
                execution_contract=contract)
    return snap, args, selected


class FakeDirector:
    def __init__(self, content):
        self.content = content
        self.calls = []
    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {'success': True, 'content': json.dumps(self.content), 'usage': {'total_tokens': 123}}


class FakeComfy:
    def __init__(self):
        self.posts = []
        self.uploads = []
    async def upload_image(self, path):
        self.uploads.append(path)
        return {'success': True, 'filename': f'uploaded_{len(self.uploads)}.png'}
    async def upload_video(self, path):
        return {'success': True, 'filename': 'previous.mp4'}
    async def queue_prompt(self, graph):
        self.posts.append(deepcopy(graph))
        return {'success': True, 'prompt_id': 'offline-prompt'}
    async def wait_for_result(self, *args, **kwargs):
        return {'success': True, 'video_url': '/offline/output.mp4'}


@pytest.mark.parametrize('clause_style', ['identity_mark', 'recognition_feature'])
def test_phase_b_accepts_current_character_identity_clause(db_session, clause_style):
    snap, args, _ = make_case(db_session, NAMES[0])
    appearances = snap['builder_input']['shot']['official_character_appearances']
    for name, appearance in appearances.items():
        replacement = (r'稳定身份标记为\1。' if clause_style == 'identity_mark'
                       else r'稳定识别特征是\1。')
        updated = re.sub(r'稳定身份标记包括([^；]+)；', replacement, appearance)
        assert updated != appearance
        appearances[name] = updated
    llm = FakeDirector(saved(NAMES[0], '_mock_response'))
    prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    assert llm.calls and 'recorded stable features:' in prompt
    assert json.loads(args['task'].metadata_json)['h3_phase_b']['status'] == 'COMPILED'


def test_phase_b_missing_identity_clause_keeps_picture_binding_without_inventing_marks(db_session):
    snap, args, _ = make_case(db_session, NAMES[0])
    appearances = snap['builder_input']['shot']['official_character_appearances']
    for name, appearance in appearances.items():
        updated = re.sub(r'稳定身份标记包括[^；]+；', '', appearance)
        assert updated != appearance
        appearances[name] = updated
    prompt = asyncio.run(pipe.build_phase_b_prompt(
        **args, llm=FakeDirector(saved(NAMES[0], '_mock_response'))))
    assert json.loads(args['task'].metadata_json)['h3_phase_b']['status'] == 'COMPILED'
    assert 'recorded stable features:' not in prompt
    assert 'stable identity is bound exclusively to <Picture' in prompt


@pytest.mark.parametrize('narration_only', [False, True], ids=['mixed-speech', 'narration-only'])
def test_phase_b_narration_is_audio_only_and_keeps_visible_subjects(db_session, narration_only):
    snap, args, _ = make_case(db_session, NAMES[0])
    for key in ('canonical_plan', 'builder_input'):
        dialogue = snap[key]['dialogue_timeline_source']
        for event in dialogue if narration_only else dialogue[:1]:
            event['speaker'] = '旁白'
    args['shot'].video_director_plan = json.dumps(snap['canonical_plan'], ensure_ascii=False)
    db_session.commit()

    prompt = asyncio.run(pipe.build_phase_b_prompt(
        **args, llm=FakeDirector(saved(NAMES[0], '_mock_response'))))
    record = json.loads(args['task'].metadata_json)['h3_phase_b']
    assert record['status'] == 'COMPILED'
    assert record['director_input']['speech_slots'][0]['speaker'] == '<Narrator>'
    if narration_only:
        assert all(slot['speaker'] == '<Narrator>' for slot in record['director_input']['speech_slots'])
    assert '<Narrator> (S1)' in prompt
    assert 'narrates in voice-over' in prompt
    assert '<Narrator> is ' not in prompt
    assert '<Narrator>' not in record['director_input']['subject_bindings']


def test_phase_b_visible_character_without_picture_uses_recorded_identity(db_session):
    snap, args, _ = make_case(db_session, NAMES[0])
    builder = snap['builder_input']
    builder['clip_visible_characters'].append('礼官')
    builder['shot']['characters'].append('礼官')
    builder['shot']['official_character_appearances']['礼官'] = '稳定身份标记为圆脸、灰发、右眉浅痣。'
    prompt = asyncio.run(pipe.build_phase_b_prompt(
        **args, llm=FakeDirector(saved(NAMES[0], '_mock_response'))))
    record = json.loads(args['task'].metadata_json)['h3_phase_b']
    assert record['status'] == 'COMPILED'
    assert record['director_input']['subject_bindings']['<Subject 5>'] == '礼官'
    assert '<Subject 5> is 礼官, with no individual identity Picture in this Clip' in prompt
    assert '圆脸、灰发、右眉浅痣' in prompt


@pytest.mark.parametrize('name', NAMES)
@pytest.mark.parametrize('silent', [False, True], ids=['dialogue', 'silent'])
@pytest.mark.parametrize('subject_tags', [False, True], ids=['name-prose-compatible', 'bound-subject-prose'])
def test_live_adapter_compiler_actual_builder_and_pre_submit(db_session, name, silent, subject_tags):
    snap, args, selected = make_case(db_session, name, silent=silent)
    response = saved(name, '_mock_response')
    if silent:
        response['dialogue_events'] = []
        for anchor in response['anchors']:
            anchor['arrival_relation'] = None
        # Mock prose tests the contract, not LLM action-coverage quality.
        response['detailed_description'] = '人物保持沉默，依序完成当前 Canonical 范围内的动作。'
        response['overall_soundscape'] = '只保留有场景和动作依据的环境声与衣料声。'
    if subject_tags:
        # Contract-only prose: no claim that this mock certifies action quality.
        subject = snap['builder_input']['reference_binding_contract']['characters'][0]['subject']
        response['detailed_description'] = subject + '依序完成当前 Canonical 动作。' + ''.join(
            f'[[SPEECH_{i}]]' for i in range(1, len(response['dialogue_events']) + 1))
        response['overall_soundscape'] = subject + '动作产生的衣料声及现有环境声。'
    llm = FakeDirector(response)
    before = deepcopy(snap)
    prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    task = args['task']
    assert len(llm.calls) == 1
    request = llm.calls[0]
    assert request['system_prompt'] == selected.template
    assert request['task_type'] == pipe.TEMPLATE_TYPE
    wire = request['user_content']
    bindings = json.loads(wire)['subject_bindings']
    assert bindings == {b['subject']: b['name'] for b in snap['builder_input']['reference_binding_contract']['characters']}
    if subject_tags:
        assert subject in bindings and subject in prompt
        assert 'Use only the existing <Subject N> tags in subject_bindings' in request['system_prompt']
    for key in ['frozen_execution', 'optimized_duration', 'optimized_start', 'optimized_time', 'authority_echo', 'execution_phases']:
        assert '"'+key+'"' not in wire
    assert snap == before
    metadata = json.loads(task.metadata_json)
    record = metadata['h3_phase_b']
    assert record['status'] == 'COMPILED' and record['preflight']['passed']
    assert record['template']['id'] == selected.id and task.prompt_text == prompt
    if silent:
        assert record['director_input']['speech_slots'] == []
        assert record['director_input']['speaker_bindings'] == {}
        assert record['compiler_result']['execution_decisions']['timing']['dialogue_events'] == []
        assert 'All characters remain silent' in prompt
        assert '<d>' not in prompt and '[[SPEECH_' not in prompt
    assert not all(record['preflight']['native_diagnostics'].values())
    assert json.loads(args['shot'].video_director_plan)['ai_calls'][-1]['task_type'] == pipe.TEMPLATE_TYPE
    paths = [r['local_path'] for r in snap['reference_manifest']['references']]
    original = snap['builder_input']['clip']['end_time'] - snap['builder_input']['clip']['start_time']
    duration, temporal, manifest, selected_paths = pipe.apply_execution(task, original, snap['reference_manifest'], paths)
    assert duration == llm.content['optimized_duration']
    assert len(selected_paths) == len(manifest['references'])
    service = object.__new__(ComfyUIService)
    service.builder = WorkflowBuilder()
    service.client = FakeComfy()
    workflow = args['workflow']
    mapping = json.loads(workflow.node_mapping)
    def check(graph, uploads):
        pipe.verify_submission(task, workflow, graph, uploads, args['previous_path'])
    if name == NAMES[0]:
        output = asyncio.run(service.generate_shot_video_with_workflow(
            prompt, workflow.workflow_json, mapping, duration_seconds=duration, seed=7,
            reference_image_paths=selected_paths, before_submit=check))
    else:
        output = asyncio.run(service.generate_video_continuation_with_workflow(
            prompt, workflow.workflow_json, mapping, args['previous_path'], duration, 'offline-only',
            capability=workflow.type, reference_image_paths=selected_paths,
            anchors=[{'image_path': a['local_path'], 'position': a['frame_position']} for a in temporal['anchors']],
            require_native_output=True, before_submit=check))
    assert output['success'], output
    assert len(service.client.posts) == 1
    assert json.loads(task.metadata_json)['h3_phase_b']['submission_preflight']['passed']
    assert json.loads(task.metadata_json)['effective_duration'] == duration
    assert snap == before


def test_reuse_requires_same_input_and_selected_template(db_session):
    snap, args, selected = make_case(db_session, NAMES[0])
    llm = FakeDirector(saved(NAMES[0], '_mock_response'))
    prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    task = args['task']; metadata=json.loads(task.metadata_json)
    metadata['skip_llm_when_prompt_exists']=True;task.metadata_json=json.dumps(metadata)
    assert asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm)) == prompt
    assert len(llm.calls)==1
    assert json.loads(task.metadata_json)['h3_phase_b']['reuse']
    selected.template += '\nEdited by user'
    with pytest.raises(ValueError, match='REUSABLE_PLAN_MISSING'):
        asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    assert len(llm.calls)==1


@pytest.mark.parametrize('name', NAMES[:2], ids=['generate', 'extend'])
def test_reuse_current_prompt_after_output_mapping_change(db_session, name):
    _, args, _ = make_case(db_session, name)
    llm = FakeDirector(saved(name, '_mock_response'))
    prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    original_record = json.loads(args['task'].metadata_json)['h3_phase_b']
    mapping = json.loads(args['workflow'].node_mapping)
    mapping['clip_video_output_node_id'] = mapping['video_save_node_id']
    args['workflow'].node_mapping = json.dumps(mapping)
    metadata = json.loads(args['task'].metadata_json)
    metadata.update(skip_llm_when_prompt_exists=True, phase_b_requested_prompt=prompt)
    args['task'].metadata_json = json.dumps(metadata)

    assert asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm)) == prompt
    record = json.loads(args['task'].metadata_json)['h3_phase_b']
    assert record['input_fingerprint'] != original_record['input_fingerprint']
    assert record['reuse_scope'] == 'SAME_SEMANTIC_INPUT'
    assert record['reuse'] is True
    assert len(llm.calls) == 1


def test_reuse_changed_mapping_rejects_different_current_prompt(db_session):
    _, args, _ = make_case(db_session, NAMES[1])
    llm = FakeDirector(saved(NAMES[1], '_mock_response'))
    asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    mapping = json.loads(args['workflow'].node_mapping)
    mapping['clip_video_output_node_id'] = mapping['video_save_node_id']
    args['workflow'].node_mapping = json.dumps(mapping)
    metadata = json.loads(args['task'].metadata_json)
    metadata.update(skip_llm_when_prompt_exists=True, phase_b_requested_prompt='different current prompt')
    args['task'].metadata_json = json.dumps(metadata)

    with pytest.raises(ValueError, match='REUSABLE_PLAN_MISSING'):
        asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    assert len(llm.calls) == 1


def test_reuse_changed_mapping_rejects_changed_director_input(db_session):
    _, args, _ = make_case(db_session, NAMES[1])
    llm = FakeDirector(saved(NAMES[1], '_mock_response'))
    prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    mapping = json.loads(args['workflow'].node_mapping)
    mapping['clip_video_output_node_id'] = mapping['video_save_node_id']
    args['workflow'].node_mapping = json.dumps(mapping)
    metadata = json.loads(args['task'].metadata_json)
    metadata.update(skip_llm_when_prompt_exists=True, phase_b_requested_prompt=prompt,
                    video_prompt_language='en')
    args['task'].metadata_json = json.dumps(metadata)

    with pytest.raises(ValueError, match='REUSABLE_PLAN_MISSING'):
        asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    assert len(llm.calls) == 1


def test_reuse_workflow_preflight_rejects_changed_workflow():
    plan = {"ai_calls": [{"task_type": pipe.TEMPLATE_TYPE, "clip_index": 1,
                          "parsed_result": {"version": pipe.VERSION, "status": "COMPILED",
                                            "workflow_id": "original"}}]}
    assert pipe.reuse_plan_workflow_blocker(plan, 1, "original") is None
    assert "工作流已更换" in pipe.reuse_plan_workflow_blocker(plan, 1, "replacement")
    assert "没有可复用" in pipe.reuse_plan_workflow_blocker(plan, 2, "original")


def test_speaker_handoff_template_change_preserves_history_and_custom_selection(db_session):
    """In-memory template update only; never synchronize a production template."""
    from app.services.novel_prompt_templates import resolve_novel_prompt_template
    case = saved('test3_shot2_c3_speaker_handoff')
    before_body = case['baseline_system_template']
    new_body = compiler.PHASE_B_TEMPLATE.read_text()
    assert before_body != new_body
    # The original five fields remain the historical contract; language-aware
    # tasks explicitly add only the keyed description translations.
    assert before_body.split('AUTHORITY AND TIME')[0] == new_body.split('DESCRIPTIVE LANGUAGE')[0]
    assert 'Without video_prompt_language, retain the original five-field response contract' in new_body
    assert before_body.split('ANCHORS AND REFERENCES')[1].split('DIRECTOR PROSE')[0] == new_body.split('ANCHORS AND REFERENCES')[1].split('DIRECTOR PROSE')[0]
    assert before_body.split('Soundscape may describe')[1] == new_body.split('Soundscape may describe')[1]
    assert pipe.VERSION == 'H3_PHASE_B_LIMITED_V3'
    _, args, custom = make_case(db_session, NAMES[0])
    custom_body = custom.template
    system = db_session.query(PromptTemplate).filter(
        PromptTemplate.type == pipe.TEMPLATE_TYPE, PromptTemplate.is_system.is_(True)).one()
    system.template = before_body
    args['novel'].h3_multi_keyframe_director_phase_b_template_id = system.id
    db_session.flush()
    old_task = args['task']
    intent = json.loads(old_task.metadata_json)
    llm = FakeDirector(saved(NAMES[0], '_mock_response'))
    old_prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    history = deepcopy((old_task.prompt_text, old_task.metadata_json, old_task.status))
    old_plan = json.loads(args['shot'].video_director_plan)
    old_fingerprint = json.loads(old_task.metadata_json)['h3_phase_b']['input_fingerprint']
    assert llm.calls[0]['system_prompt'] == before_body

    system.template = new_body
    new_task = Task(type='shot_video', name='offline handoff template check', status='running',
                    novel_id=old_task.novel_id, chapter_id=old_task.chapter_id, shot_id=old_task.shot_id,
                    metadata_json=json.dumps({**intent, 'skip_llm_when_prompt_exists': True}))
    db_session.add(new_task); db_session.commit()
    args = {**args, 'task': new_task}
    with pytest.raises(ValueError, match='REUSABLE_PLAN_MISSING'):
        asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    assert len(llm.calls) == 1  # No silent fallback or automatic Director retry.
    assert json.loads(args['shot'].video_director_plan) == old_plan
    assert (old_task.prompt_text, old_task.metadata_json, old_task.status) == history

    # Explicitly allow a new fake Director attempt for the new template body.
    new_task.metadata_json = json.dumps({**intent, 'skip_llm_when_prompt_exists': False})
    new_prompt = asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    record = json.loads(new_task.metadata_json)['h3_phase_b']
    assert len(llm.calls) == 2 and record['llm_call_count'] == 1
    assert llm.calls[-1]['system_prompt'] == new_body
    assert llm.calls[-1]['max_tokens'] == 4500
    assert record['template']['id'] == system.id
    assert record['input_fingerprint'] != old_fingerprint
    assert record['preflight']['passed']
    # FakeDirector returns identical prose: no deterministic handoff injection.
    assert new_prompt == old_prompt
    assert (old_task.prompt_text, old_task.metadata_json, old_task.status) == history
    plan = json.loads(args['shot'].video_director_plan)
    assert plan['ai_calls'][:-1] == old_plan['ai_calls']
    assert {k: v for k, v in plan.items() if k != 'ai_calls'} == {
        k: v for k, v in old_plan.items() if k != 'ai_calls'}
    assert custom.template == custom_body
    args['novel'].h3_multi_keyframe_director_phase_b_template_id = custom.id
    db_session.flush()
    assert resolve_novel_prompt_template(db_session, args['novel'], pipe.TEMPLATE_TYPE).id == custom.id


def test_reuse_rejects_previous_compiler_contract_without_llm(db_session):
    _, args, _ = make_case(db_session, NAMES[0])
    llm = FakeDirector(saved(NAMES[0], '_mock_response'))
    asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    plan = json.loads(args['shot'].video_director_plan)
    plan['ai_calls'][-1]['parsed_result']['version'] = 'H3_PHASE_B_LIMITED_V2'
    args['shot'].video_director_plan = json.dumps(plan)
    metadata = json.loads(args['task'].metadata_json)
    metadata['skip_llm_when_prompt_exists'] = True
    args['task'].metadata_json = json.dumps(metadata)
    with pytest.raises(ValueError, match='REUSABLE_PLAN_MISSING'):
        asyncio.run(pipe.build_phase_b_prompt(**args, llm=llm))
    assert len(llm.calls) == 1


@pytest.mark.parametrize('failure', ['speaker', 'duration', 'missing_action_catalog', 'llm_failure'])
def test_failed_planning_persists_and_never_repairs(db_session, failure):
    snap, args, _ = make_case(db_session, NAMES[0])
    response=saved(NAMES[0], '_mock_response')
    if failure=='speaker': response['dialogue_events'][0]['speaker']='wrong'
    if failure=='duration': response['optimized_duration']=999
    if failure=='missing_action_catalog': response['anchors'].pop()
    llm=FakeDirector(response)
    if failure=='llm_failure':
        async def error(**kwargs):
            llm.calls.append(kwargs);raise TimeoutError('offline timeout')
        llm.chat_completion=error
    with pytest.raises((ValueError,TimeoutError)):
        asyncio.run(pipe.build_phase_b_prompt(**args,llm=llm))
    assert len(llm.calls)==1
    record=json.loads(args['task'].metadata_json)['h3_phase_b']
    assert record['status']=='FAILED' and record['error']
    assert not args['task'].comfyui_prompt_id


def test_registry_sync_and_novel_selection(db_session):
    from app.services.prompt_template_service import PromptTemplateService
    from app.constants.prompt_template import PROMPT_TEMPLATE_TYPES, PROMPT_TEMPLATE_FILE_NUMBERS
    from app.services.novel_prompt_templates import resolve_novel_prompt_template
    from app.api.prompt_templates import PROMPT_TEMPLATE_EXPORT_CATEGORIES
    assert pipe.TEMPLATE_TYPE in PROMPT_TEMPLATE_TYPES
    assert PROMPT_TEMPLATE_FILE_NUMBERS[pipe.TEMPLATE_TYPE]=='13'
    assert any(group=='视频生成' and any(t==pipe.TEMPLATE_TYPE for t,_ in entries) for group, entries in PROMPT_TEMPLATE_EXPORT_CATEGORIES)
    snap,args,selected=make_case(db_session,NAMES[0])
    body=selected.template
    service=PromptTemplateService(db_session)
    service.init_system_templates()
    assert selected.template==body
    assert resolve_novel_prompt_template(db_session,args['novel'],pipe.TEMPLATE_TYPE).id==selected.id
    system = db_session.query(PromptTemplate).filter(
        PromptTemplate.type == pipe.TEMPLATE_TYPE, PromptTemplate.is_system.is_(True),
        PromptTemplate.name == 'MiniMax H3 单阶段导演规划（Phase B）'
    ).one()
    system_id = system.id
    source = (Path(__file__).parents[1] / 'prompt_templates' / 'H3_MultiKeyframe_Director_PhaseB.txt').read_text()
    assert system.template == source
    assert 'speech_slots is empty' in system.template
    system.template = 'previous system body'
    db_session.flush()
    service.init_system_templates()
    db_session.refresh(system)
    assert system.id == system_id and system.template == source
    assert selected.template == body
    selected.is_active=False;db_session.flush()
    assert resolve_novel_prompt_template(db_session,args['novel'],pipe.TEMPLATE_TYPE).is_system
    assert db_session.query(PromptTemplate).filter(PromptTemplate.type=='h3_multi_keyframe_prompt').count()>0


def test_new_route_defaults_phase_b_and_explicit_legacy_remains_available():
    from app.api.shots import SemanticClipGenerateRequest, BatchShotVideoRequest
    from app.schemas.shot import GenerateVideoDirectorClipRequest, GenerateVideoRequest
    for model, args in [(SemanticClipGenerateRequest, {}), (BatchShotVideoRequest, {'shot_ids': []}),
                        (GenerateVideoDirectorClipRequest, {})]:
        assert model(**args).h3_prompt_pipeline == 'phase_b'
        for route in ('legacy', 'phase_b'):
            assert model(**args, h3_prompt_pipeline=route).h3_prompt_pipeline == route
        for route in ('automatic', '', None):
            with pytest.raises(ValueError): model(**args, h3_prompt_pipeline=route)
    # The retired/general video request is not converted into an H3 route.
    assert 'h3_prompt_pipeline' not in GenerateVideoRequest.model_fields

@pytest.mark.asyncio
@pytest.mark.parametrize('case_name,cancel_during_upload',[(n,False) for n in NAMES]+[(NAMES[0],True)])
@pytest.mark.parametrize('result_mode',['APPLY','CANDIDATE_ONLY'])
async def test_semantic_api_queue_worker_compiler_and_save(db_session, monkeypatch,case_name,cancel_during_upload,result_mode):
    """Real endpoint, queue wrapper, worker and Prompt input; external I/O is fake."""
    from app.api import shots as api
    from app.models.workflow import Workflow
    from app.models.novel import Character
    from app.repositories import NovelRepository, ChapterRepository, ShotRepository, TaskRepository
    from app.services import shot_video_service as worker
    from app.services.llm_service import LLMService

    snap, args, selected = make_case(db_session, case_name)
    shot, novel = args['shot'], args['novel']
    db_session.delete(args['task']);db_session.flush()
    plan=deepcopy(snap['canonical_plan']);plan.update(clip_plan_revision=1,canonical_visual_plan=True)
    from app.services.clip_planner import TEMPORAL_DECISION_CONTRACT, EARLY_COMPOSITION_CONTRACT
    plan['clip_plan_validation']={'temporal_contract':TEMPORAL_DECISION_CONTRACT,'composition_contract':EARLY_COMPOSITION_CONTRACT}
    for r in snap['reference_manifest']['references']:
        if r['kind']=='DIRECTOR_VISUAL_ANCHOR':
            next(k for k in plan['keyframes'] if k['index']==r['source_keyframe_index'])['image_url']=r['image_url']
    # Fixture stores one executed Clip. Surrounding unexecuted windows only
    # exercise whole-Shot ownership; they supply no new Director decisions.
    current=plan['clip_plan'][0];index=current['clip_index']
    if current['start_time']>0:
        current['previous_clip_index']=index-1
        plan['clip_plan'].insert(0,{'clip_index':index-1,'start_time':0,'end_time':current['start_time'],'capability':'GENERATE'})
        previous=deepcopy(snap['physical_evidence']['previous_clip'])
        previous.update(clip_plan_revision=1,local_path=snap['previous_video_path'])
        monkeypatch.setattr(api,'resolve_extend_previous_av',lambda *a,**k:previous)
        monkeypatch.setattr(worker,'resolve_extend_previous_av',lambda *a,**k:previous)
    if current['end_time']<shot.duration:
        plan['clip_plan'].append({'clip_index':index+1,'start_time':current['end_time'],'end_time':shot.duration,'capability':'EXTEND'})
    if case_name==NAMES[2]:
        current.update(requires_temporal_control=True,temporal_anchor_ids=[a['anchor_id'] for a in snap['physical_evidence']['temporal_anchors']])
        plan['temporal_anchors']=deepcopy(snap['physical_evidence']['temporal_anchors'])
    shot.video_director_plan=json.dumps(plan,ensure_ascii=False)
    shot.characters=json.dumps(snap['builder_input']['shot']['characters'],ensure_ascii=False)
    shot.dialogues=json.dumps([{'dialogue_id':d['id'],'speaker':d['speaker'],'text':d['text']} for d in plan['dialogue_timeline_source']],ensure_ascii=False)
    shot.description='real fixture';shot.video_url='/preserved-historical-shot.mp4'
    for name, appearance in snap['builder_input']['shot']['official_character_appearances'].items():
        db_session.add(Character(novel_id=novel.id,name=name,appearance=appearance))
    workflow=Workflow(**{k:getattr(args['workflow'],k) for k in ['id','name','type','workflow_json','node_mapping','extension']},is_active=True)
    db_session.add(workflow);db_session.commit()
    resources={'references':[deepcopy(r) for r in snap['reference_manifest']['references'] if r['kind']!='DIRECTOR_VISUAL_ANCHOR']}
    # The catalog resolver is substituted, but the existing Clip/reference
    # compiler and new runtime input projector still run on the real plan.
    def resolve(*a,**kw): return resources
    monkeypatch.setattr(api,'resolve_clip_reference_resources',resolve)
    monkeypatch.setattr(worker,'resolve_clip_reference_resources',resolve)
    monkeypatch.setattr(worker,'SessionLocal',lambda:db_session)
    monkeypatch.setattr(db_session,'close',lambda:None)
    jobs=[]
    def capture_enqueue(job, *, db=None):
        if db is not None:
            db.commit()
        jobs.append(job)
    monkeypatch.setattr(worker,'worker_manager',SimpleNamespace(worker=lambda _:SimpleNamespace(enqueue=capture_enqueue)))
    llm=FakeDirector(saved(case_name,'_mock_response'))
    async def reply(self, **kw):
        from h3_language_fakes import language_response
        llm.content = language_response(json.loads(kw['user_content']), saved(case_name,'_mock_response'))
        return await llm.chat_completion(**kw)
    monkeypatch.setattr(LLMService,'chat_completion',reply)
    service=object.__new__(ComfyUIService);service.builder=WorkflowBuilder();service.client=FakeComfy()
    monkeypatch.setattr(worker,'ComfyUIService',lambda:service)
    saves=[]
    async def save(result,task,*pos,**kw):
        saves.append((task.id,kw));task.status='completed';task.result_url='/offline-result.mp4';db_session.commit()
    monkeypatch.setattr(worker,'_save_generated_video',save)
    before_candidate=shot.video_director_plan
    result=await api.execute_semantic_clip(novel.id,shot.chapter_id,shot.id,index,
        api.SemanticClipGenerateRequest(clip_plan_revision=1,optimize_h3_prompt=True,result_mode=result_mode),
        db_session,NovelRepository(db_session),ChapterRepository(db_session),TaskRepository(db_session),ShotRepository(db_session))
    assert len(jobs)==1
    task=db_session.get(Task,result['data']['taskId'])
    assert json.loads(task.metadata_json)['h3_prompt_pipeline']=='phase_b'
    assert json.loads(task.metadata_json)['video_prompt_language']=='en'
    if cancel_during_upload:
        upload=service.client.upload_image
        async def cancel_upload(path):
            task.status='cancelled';db_session.commit()
            return await upload(path)
        service.client.upload_image=cancel_upload
    await jobs.pop()()
    if cancel_during_upload:
        assert task.status=='cancelled'
        assert len(llm.calls)==1 and not service.client.posts and not saves
        return
    assert task.status=='completed',task.error_message
    assert len(llm.calls)==1 and len(service.client.posts)==1 and len(saves)==1
    assert not saves[0][1]['update_shot_result']
    assert shot.video_url=='/preserved-historical-shot.mp4'
    meta=json.loads(task.metadata_json)
    assert meta['h3_phase_b']['submission_preflight']['passed']
    assert meta['h3_phase_b']['version'] == 'H3_PHASE_B_LIMITED_V3'
    assert meta['optimize_h3_prompt'] is False and meta['preflight_auto_repair'] is False
    assert task.workflow_json and task.comfyui_prompt_id
    if result_mode=='CANDIDATE_ONLY':
        assert shot.video_director_plan==before_candidate
    else:
        assert json.loads(shot.video_director_plan)['ai_calls'][-1]['task_type']==pipe.TEMPLATE_TYPE
    from app.services.task_service import TaskService
    # Explicit regeneration of a completed, saved result. A failed Task with an
    # unresolved receipt must instead remain protected from another submission.
    retried=TaskService(db_session).retry_task(task.id)
    assert retried['success'],retried
    assert len(jobs)==1
    assert json.loads(task.metadata_json)['h3_prompt_pipeline']=='phase_b'
    assert shot.video_url=='/preserved-historical-shot.mp4'
    # Exercise scheduling only, without starting another attempt.
    jobs.clear();worker._queued_shot_video_task_ids.discard(task.id)
    if case_name!=NAMES[0]:
        task.status='failed';db_session.commit()
        def invalid_previous(*args,**kwargs): raise ValueError('PREVIOUS_AV_UNAVAILABLE')
        monkeypatch.setattr(worker,'resolve_extend_previous_av',invalid_previous)
        assert TaskService(db_session).retry_task(task.id)['success'] is False
        assert not jobs

@pytest.mark.asyncio
async def test_batch_preserves_phase_b_route(db_session, monkeypatch, tmp_path):
    from test_semantic_batch_scheduler import _fixture, _install_execution_fake
    from app.api import shots as api
    _, _, shot, parent, child = _fixture(db_session)
    meta=json.loads(child.metadata_json);meta['h3_prompt_pipeline']='phase_b';child.metadata_json=json.dumps(meta)
    calls=[];_install_execution_fake(db_session,monkeypatch,tmp_path,calls)
    execute=api.execute_semantic_clip
    async def observed(*a,**kw):
        assert a[4].h3_prompt_pipeline=='phase_b'
        return await execute(*a,**kw)
    monkeypatch.setattr(api,'execute_semantic_clip',observed)
    assert await api._run_semantic_shot_for_batch(db_session,parent,child,shot)=='completed'
    assert calls==[1,2,3]


def test_preflight_failure_does_not_upload_or_submit(db_session):
    snap,args,_=make_case(db_session,NAMES[0])
    reply=saved(NAMES[0],'_mock_response');reply['dialogue_events'][1]['start']=reply['dialogue_events'][0]['start']
    with pytest.raises(ValueError,match='DIALOGUE'):
        asyncio.run(pipe.build_phase_b_prompt(**args,llm=FakeDirector(reply)))
    record=json.loads(args['task'].metadata_json)['h3_phase_b']
    assert record['status']=='FAILED' and record['llm_call_count']==1


def test_actual_binding_tamper_is_rejected_before_queue(db_session):
    snap,args,_=make_case(db_session,NAMES[0]);task=args['task']
    prompt=asyncio.run(pipe.build_phase_b_prompt(**args,llm=FakeDirector(saved(NAMES[0],'_mock_response'))))
    duration,_,manifest,paths=pipe.apply_execution(task,15.25,snap['reference_manifest'],[r['local_path'] for r in snap['reference_manifest']['references']])
    service=object.__new__(ComfyUIService);service.builder=WorkflowBuilder();service.client=FakeComfy()
    mapping=json.loads(args['workflow'].node_mapping)
    def fail(graph,uploads):
        graph[mapping['load_image_node_1']]['inputs']['image']='different.png'
        pipe.verify_submission(task,args['workflow'],graph,uploads)
    output=asyncio.run(service.generate_shot_video_with_workflow(prompt,args['workflow'].workflow_json,mapping,
        duration_seconds=duration,reference_image_paths=paths,before_submit=fail))
    assert not output['success'] and not service.client.posts
    assert not json.loads(task.metadata_json)['h3_phase_b']['submission_preflight']['checks']['picture_order']


def test_inspector_uses_frozen_phase_b_times_and_states(db_session,tmp_path):
    from unittest.mock import Mock
    from app.services.clip_execution_inspector_service import ClipExecutionInspectorService
    from app.services.inspector_frame_service import InspectorFrameService
    from app.services.inspector_store import InspectorStore
    from test_clip_execution_inspector import measured
    snap,args,_=make_case(db_session,NAMES[0]);task=args['task'];shot=args['shot']
    asyncio.run(pipe.build_phase_b_prompt(**args,llm=FakeDirector(saved(NAMES[0],'_mock_response'))))
    pipe.apply_execution(task,15.25,snap['reference_manifest'],[r['local_path'] for r in snap['reference_manifest']['references']])
    meta=json.loads(task.metadata_json);dec=meta['h3_phase_b']['compiler_result']['execution_decisions'];ci=snap['builder_input']['clip']
    meta['execution_contract'].update(artifact_kind='CLIP_ONLY',clip={'clip_index':1,'clip_plan_revision':1,'start_seconds':0,'end_seconds':15.25,'duration_seconds':15.25})
    meta['dialogue_assignment']=[{'dialogue_id':d['id'],**d} for d in snap['canonical_plan']['dialogue_timeline_source'] if d['end_time']<=15.25]
    task.metadata_json=json.dumps(meta);task.result_url='/offline-result.mp4'
    # A later plan cannot silently replace this execution's source facts.
    shot.video_director_plan=json.dumps({'keyframes':[{'index':1,'time_seconds':0,'description':'LATER_CANONICAL'}]})
    store=InspectorStore(tmp_path);frames=InspectorFrameService(store);frames.probe=Mock(return_value=measured())
    projection,_=ClipExecutionInspectorService(store=store,frames=frames).project(task,shot)
    events=projection['events']
    assert [(e['start'],e['end']) for e in events if e['type']=='DIALOGUE']==[(d['optimized_start'],d['optimized_end']) for d in dec['timing']['dialogue_events']]
    states=[e for e in events if e['type']=='SEMANTIC_KF']
    assert len(states)==5 and 'LATER_CANONICAL' not in json.dumps(states)
    assert all(e['start'] is None for e in events if e['type']=='TRANSITION')
    assert projection['h3_phase_b']['version']==pipe.VERSION


def test_phase_b_management_create_edit_select_export_copy(client,db_session):
    from io import BytesIO
    from zipfile import ZipFile
    from app.services.novel_prompt_templates import resolve_novel_prompt_template
    system=db_session.query(PromptTemplate).filter_by(type=pipe.TEMPLATE_TYPE,is_system=True).one()
    assert system.template==compiler.PHASE_B_TEMPLATE.read_text()
    assert client.get('/api/prompt-templates/system/default',params={'type':pipe.TEMPLATE_TYPE}).json()['data']['id']==system.id
    version=client.post(f'/api/prompt-templates/{system.id}/copy').json()['data']
    text=system.template+'\nUser managed version\n'
    edited=client.put(f"/api/prompt-templates/{version['id']}",json={'name':'Phase B custom','description':'user selected','type':pipe.TEMPLATE_TYPE,'template':text})
    assert edited.status_code==200 and edited.json()['data']['template']==text
    field='h3MultiKeyframeDirectorPhaseBTemplateId'
    created=client.post('/api/novels/',json={'title':'Offline management',field:version['id']})
    assert created.status_code==200 and created.json()['data'][field]==version['id']
    nid=created.json()['data']['id'];novel=db_session.get(Novel,nid)
    assert resolve_novel_prompt_template(db_session,novel,pipe.TEMPLATE_TYPE).template==text
    copied=client.post(f'/api/novels/{nid}/copy',json={'title':'Copy'}).json()['data']
    assert copied[field]==version['id']
    changed=client.put(f'/api/novels/{nid}',json={field:None})
    assert changed.status_code==200 and changed.json()['data'][field] is None
    assert resolve_novel_prompt_template(db_session,novel,pipe.TEMPLATE_TYPE).id==system.id
    archive=client.get('/api/prompt-templates/export-all')
    with ZipFile(BytesIO(archive.content)) as z:
        directory='视频生成/MiniMax H3 单阶段导演规划（Phase B）/'
        assert z.read(directory+'用户-Phase B custom.txt').decode()==text
        assert z.read(directory+'系统-'+system.name+'.txt').decode()==system.template
        assert any('MiniMax H3 多关键帧视频提示词构建/' in n for n in z.namelist())
    assert db_session.query(Task).count()==0
