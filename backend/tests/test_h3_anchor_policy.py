import copy
import json
from types import SimpleNamespace as NS
import pytest
from app.services import h3_anchor_policy as policy
from app.services.h3_native_prompt import dialogue_events, sections
from app.services.shot_video_service import _apply_h3_execution_references
from app.services.comfyui.workflows import WorkflowBuilder

@pytest.fixture
def case():
    source='A remains seated. B raises separated empty hands, palms up. No fabric appears.'
    authority={'reference_bindings':[
        {'picture':'<Picture 1>','type':'DIRECTOR_VISUAL_ANCHOR','subject':None},
        {'picture':'<Picture 2>','type':'DIRECTOR_VISUAL_ANCHOR','subject':None},
        {'picture':'<Picture 3>','type':'CHARACTER_IDENTITY','subject':'<Subject 1>'},
        {'picture':'<Picture 4>','type':'SCENE','subject':None}],
        'anchor_policy':{'catalog':[
            {'anchor_id':'KF1','original_time':0,'source_picture':'<Picture 1>'},
            {'anchor_id':'KF2','original_time':3,'source_picture':'<Picture 2>'}],
            'canonical_visual_sources':[{'id':'action','text':source}],'drop_binding':{'supported':True}}}
    start='Begin with A seated as suggested by <Picture 1>.'
    action='B raises separated empty hands, palms up. No fabric appears.'
    end='Develop the empty-hand state suggested by <Picture 2> without matching its exact framing.'
    prompt='subject_definitions:\n<Subject 1> is A, identity from <Picture 3>.\nsummary:\nA 4-second view.\nretention_analysis:\n<Picture 4> supplies the scene.\ndetailed_description:\n'+start+' '+action+'\n<Subject 1> (S1) says, <d>[Chinese] 好。</d>\n'+end+'\noverall_soundscape:\nRoom tone.\nnon_diegetic_music:\nN/A'
    requirements=[{'id':'V1','requirement':'A stays seated','source_id':'action','source_excerpt':'A remains seated.','prompt_excerpt':start},
        {'id':'V2','requirement':'Empty-hand display with no cloth','source_id':'action','source_excerpt':action,'prompt_excerpt':action}]
    anchors=[{'id':id,'decision':'KEEP','original_time':time,'optimized_time':time,'delta':0,'reason':'Useful visual guidance.',
              'preserved_visual_requirements':[req],'prompt_excerpt':excerpt,'arrival_relation':{'dialogue_id':'D1','position':pos,'prompt_excerpt':excerpt}}
             for id,time,req,excerpt,pos in [('KF1',0,'V1',start,'BEFORE'),('KF2',3,'V2',end,'AFTER')]]
    output={'optimized_prompt':prompt,'canonical_visual_requirements':requirements,
        'reference_projection':[{'source_picture':r['picture'],'picture':r['picture']} for r in authority['reference_bindings']],
        'av_timeline':{'optimized_duration':4,'anchors':anchors,'dialogue_events':[{'id':'D1','optimized_start':1,'optimized_end':2}],
                      'execution_phases':[{'type':'CAMERA','start':0,'end':4},{'type':'ANCHOR_ARRIVAL','anchor_id':'KF2','start':3,'end':3}]}}
    manifest={'references':[{'slot':i,'image_url':f'/ref{i}.png','kind':r['type'],'binding':{'uploaded_filename':f'old{i}.png'}} for i,r in enumerate(authority['reference_bindings'],1)]}
    return authority,output,manifest

def audit(case):
    authority,output,_=case;p=output['optimized_prompt']
    return policy.check_anchor_policy(p,output,authority,dialogue_events(p),sections(p)['detailed_description'])[0]

def drop(case):
    o=case[1];a=o['av_timeline']['anchors'][1]
    o['optimized_prompt']=o['optimized_prompt'].replace(a['prompt_excerpt'],'').replace('<Picture 3>','<Picture 2>').replace('<Picture 4>','<Picture 3>')
    a.update(decision='DROP',optimized_time=None,delta=None,prompt_excerpt=None,arrival_relation=None,released_constraint='Discard distant full composition, not the gesture.')
    o['av_timeline']['execution_phases']=o['av_timeline']['execution_phases'][:1]
    o['reference_projection']=[{'source_picture':f'<Picture {old}>','picture':f'<Picture {new}>'} for old,new in [(1,1),(3,2),(4,3)]]

def test_keep_preserves_requirements_and_source(case):
    before=copy.deepcopy(case);assert all(audit(case).values());assert case==before

def test_retime_can_arrive_before_dialogue_without_changing_requirements(case):
    o=case[1];before=copy.deepcopy(o['canonical_visual_requirements']);a=o['av_timeline']['anchors'][1]
    a.update(decision='RETIME',optimized_time=.8,delta=-2.2);a['arrival_relation']['position']='BEFORE'
    o['av_timeline']['execution_phases'][1].update(start=.8,end=.8)
    excerpt=a['prompt_excerpt'];o['optimized_prompt']=o['optimized_prompt'].replace(excerpt,'').replace('<Subject 1> (S1)',excerpt+'\n<Subject 1> (S1)')
    assert all(audit(case).values());assert o['canonical_visual_requirements']==before

def test_final_state_before_line_cannot_claim_arrival_after_line(case):
    excerpt=case[1]['av_timeline']['anchors'][1]['prompt_excerpt']
    case[1]['optimized_prompt']=case[1]['optimized_prompt'].replace(excerpt,'').replace('<Subject 1> (S1)',excerpt+'\n<Subject 1> (S1)')
    assert not audit(case)['anchor_arrival_relation']

def test_drop_preserves_actions_but_releases_full_kf_constraint(case):
    before=copy.deepcopy(case[1]['canonical_visual_requirements']);drop(case)
    assert all(audit(case).values());assert case[1]['canonical_visual_requirements']==before
    assert before[1]['prompt_excerpt'] in case[1]['optimized_prompt']
    assert 'without matching its exact framing' not in case[1]['optimized_prompt']
    case[1]['optimized_prompt']=case[1]['optimized_prompt'].replace(before[1]['prompt_excerpt'],'')
    assert not audit(case)['canonical_visual_requirement_consistency']

@pytest.mark.parametrize('field,value',[('optimized_time',3),('prompt_excerpt','Still reach discarded picture'),('arrival_relation',{'position':'AFTER'})])
def test_drop_cannot_keep_arrival_contract(case,field,value):
    drop(case);case[1]['av_timeline']['anchors'][1][field]=value
    assert not audit(case)['anchor_decision_semantics']

def test_drop_cannot_leave_scheduled_arrival(case):
    drop(case);case[1]['av_timeline']['execution_phases'].append({'type':'ANCHOR_ARRIVAL','anchor_id':'KF2','start':3,'end':3})
    assert not audit(case)['anchor_arrival_phase_binding']

def test_drop_compacts_numbering_manifest_and_worker_paths_together(case):
    before=copy.deepcopy(case[2]);drop(case);selected=policy.project_reference_manifest(case[2],case[0],case[1])
    assert [r['image_url'] for r in selected['references']]==['/ref1.png','/ref3.png','/ref4.png']
    assert [r['slot'] for r in selected['references']]==[1,2,3]
    assert [r['source_slot'] for r in selected['references']]==[1,3,4]
    assert selected['excluded_references'][0]['image_url']=='/ref2.png'
    assert all('binding' not in r for r in selected['references'])
    task=NS(metadata_json=json.dumps({'optimize_h3_prompt':True,'h3_prompt_optimizer':{'status':'OPTIMIZED','authority_check':{'passed':True},'execution_reference_manifest':selected}}))
    manifest,paths=_apply_h3_execution_references(task,case[2],['one','two','three','four'])
    assert paths==['one','three','four'] and manifest==selected and case[2]==before
    assert len(json.loads(task.reference_images))==3

@pytest.mark.parametrize('mutation,key',[
    (lambda o:o['reference_projection'].reverse(),'reference_projection_consistent'),
    (lambda o:o.update(optimized_prompt=o['optimized_prompt']+' <Picture 9>'),'picture_presence'),
    (lambda o:o['av_timeline']['anchors'][0].update(preserved_visual_requirements=['missing']),'anchor_required_outcomes_retained'),
    (lambda o:o['canonical_visual_requirements'][0].update(source_excerpt='Invented story'),'canonical_visual_requirement_trace')])
def test_no_wrong_picture_or_invented_requirement(case,mutation,key):
    drop(case);mutation(case[1]);assert not audit(case)[key]

def test_unverified_binding_blocks_drop_but_not_keep(case):
    case[0]['anchor_policy']['drop_binding']['supported']=False
    assert all(audit(case).values());drop(case);assert not audit(case)['drop_binding_supported']

def test_soft_kf_details_are_not_automatically_story_requirements(case):
    case[0]['anchor_policy']['catalog'][1]['visual_reference_description']='Tiny face, distant framing, foreground ratio 90%.'
    drop(case);assert all(audit(case).values())
    assert 'distant framing' not in json.dumps(case[1]['canonical_visual_requirements'])
    assert 'Tiny face' not in case[1]['optimized_prompt']

def test_existing_ref2va_binder_matches_projection_and_preserves_other_nodes(db_session,case):
    from app.models.workflow import Workflow
    from app.services.workflow_service import WorkflowService
    WorkflowService(db_session).load_default_workflows();workflow=db_session.query(Workflow).filter(Workflow.type=='multi_reference_video').one()
    assert policy.reference_drop_capability(workflow)['supported']
    assert not policy.reference_drop_capability(NS(type='other'))['supported']
    graph=json.loads(workflow.workflow_json);before=copy.deepcopy(graph);mapping=json.loads(workflow.node_mapping)
    drop(case);manifest=policy.project_reference_manifest(case[2],case[0],case[1]);files=[r['image_url'] for r in manifest['references']]
    WorkflowBuilder.bind_multi_reference_video_images(graph,mapping,files)
    assert len([k for k in graph['136']['inputs'] if k.startswith('ref_images.')])==3
    assert [graph[mapping[f'load_image_node_{i}']]['inputs']['image'] for i in range(1,4)]==files
    image_nodes={mapping[f'load_image_node_{i}'] for i in range(1,10)}
    assert all(graph[k]==v for k,v in before.items() if k not in image_nodes|{'136'})
    assert {k:v for k,v in graph['136']['inputs'].items() if not k.startswith('ref_images.')}=={k:v for k,v in before['136']['inputs'].items() if not k.startswith('ref_images.')}
    assert json.loads(workflow.workflow_json)==before

def test_runtime_keeps_requirement_sources_separate_from_kf_details(monkeypatch):
    from app.services import h3_execution_optimizer as opt
    monkeypatch.setattr(opt,'previous_video_frames',lambda _:[])
    raw='duration: 4s\n<Subject 1> is A, stable identity.\nKF1 — START — Clip-local 0s — TEXT_ONLY. Camera distance is incidental.'
    runtime,_=opt.build_runtime_input(raw,'SINGLE_FRAME',{'planned_duration':4},execution_context={'anchor_policy_version':1,'canonical_visual_sources':[{'id':'action','text':'A stays seated.'}]})
    p=runtime['immutable_authority']['anchor_policy']
    assert p['canonical_visual_sources']==[{'id':'action','text':'A stays seated.'}]
    assert 'Camera distance' in p['catalog'][0]['visual_reference_description']
    assert 'SOFT_REFERENCE_KEEP_RETIME_DROP' in runtime['execution_flexibility']['anchor_camera_composition_and_blocking']

@pytest.mark.parametrize('leak',['KEEP','RETIME','DROP','anchor_id: KF2','preserved_visual_requirements: V1'])
def test_anchor_internal_fields_never_become_final_prompt(leak):
    from app.services.h3_native_prompt import check_native_prompt
    prompt='subject_definitions:\n<Subject 1> is A.\nsummary:\nA 4-second view.\nretention_analysis:\nKeep costume, pose, blocking and identity face.\ndetailed_description:\nMaintain established floor positions. '+leak+'\noverall_soundscape:\nQuiet.\nnon_diegetic_music:\nN/A'
    checks,_=check_native_prompt(prompt,[],{'subject_bindings':{'<Subject 1>':'A'},'reference_bindings':[]},'',{'handoffs':[]})
    assert not checks['no_final_state_machine_terms']


def test_ref2va_image_shared_with_unvalidated_node_is_not_drop_capable(db_session):
    from app.models.workflow import Workflow
    from app.services.workflow_service import WorkflowService
    WorkflowService(db_session).load_default_workflows();w=db_session.query(Workflow).filter(Workflow.type=='multi_reference_video').one()
    graph=json.loads(w.workflow_json);graph['other']={'class_type':'OtherConsumer','inputs':{'image':['137',0]}}
    assert not policy.reference_drop_capability(NS(type=w.type,workflow_json=json.dumps(graph),node_mapping=w.node_mapping))['supported']

@pytest.mark.parametrize('family',['VIDEO_CONTINUATION','TEMPORAL_EXTEND'])
def test_continuation_drop_only_changes_ordinary_pictures(db_session,family):
    from app.models.workflow import Workflow
    from app.services.workflow_service import WorkflowService
    WorkflowService(db_session).load_default_workflows()
    w=db_session.query(Workflow).filter(Workflow.type==family).one()
    graph=json.loads(w.workflow_json);mapping=json.loads(w.node_mapping);before=copy.deepcopy(graph)
    assert policy.reference_drop_capability(w)['supported']
    WorkflowBuilder.bind_multi_reference_video_images(graph,mapping,['identity.png','scene.png'])
    picture_nodes={str(mapping[f'load_image_node_{i}']) for i in range(1,10)}|{str(mapping['reference_to_video_node_id'])}
    assert all(graph[k]==v for k,v in before.items() if k not in picture_nodes)
    assert graph['23']==before['23'] and graph['66']==before['66'] and graph['37']==before['37']

@pytest.mark.parametrize('description,passed',[
    ('Arrival at retained anchor KF2.',True),
    ('到达KF2。',True),
    ('KF1 and KF2 have possible arrivals.',False),
    ('Arrival at KF20.',False),
])
def test_point_event_can_name_anchor_in_description_without_duplicating_field(case,description,passed):
    phase=case[1]['av_timeline']['execution_phases'][1]
    phase.pop('anchor_id');phase['description']=description
    assert audit(case)['anchor_arrival_phase_binding'] is passed


@pytest.mark.parametrize('description,time,passed',[
    ('Arrival for retimed linked temporal anchor clip-4-KF2.', 3.5, True),
    ('Arrival for retained anchor KF2.', 3.0, True),
    ('Arrival for KF2 and clip-4-KF2.', 3.5, False),
    ('Arrival for clip-5-KF2.', 3.0, False),
    ('Arrival for clip-4-KF20.', 3.5, False),
    ('Arrival for clip-4-KF2.', 3.0, False),
])
def test_point_event_uses_complete_hyphenated_anchor_identity(case, description, time, passed):
    authority, output, _ = case
    authority['anchor_policy']['catalog'].append({'anchor_id':'clip-4-KF2','original_time':3.5})
    anchor = copy.deepcopy(output['av_timeline']['anchors'][1])
    anchor.update(id='clip-4-KF2', original_time=3.5, optimized_time=3.5)
    output['av_timeline']['anchors'].append(anchor)
    phase = output['av_timeline']['execution_phases'][1]
    phase.pop('anchor_id')
    phase.update(description=description, start=time, end=time)
    before = copy.deepcopy(case)
    assert audit(case)['anchor_arrival_phase_binding'] is passed
    assert case == before


def test_reference_scope_accepts_canonical_staging_without_requiring_word_anchor():
    from app.services.h3_native_prompt import check_native_prompt
    prompt='subject_definitions:\n<Subject 1> is A, with a stable face and identity.\nsummary:\nA 4-second view.\nretention_analysis:\nChronological references guide current clothing. Identity images do not overwrite canonical staging, current costume, pose, or blocking.\ndetailed_description:\nMaintain established floor positions.\noverall_soundscape:\nQuiet.\nnon_diegetic_music:\nN/A'
    authority={'subject_bindings':{'<Subject 1>':'A'},'reference_bindings':[{'picture':'<Picture 1>','type':'CHARACTER_IDENTITY','subject':'<Subject 1>'}],'anchor_policy':{'version':1}}
    checks,_=check_native_prompt(prompt,[],authority,'',{'handoffs':[]})
    assert checks['reference_authority_scope']
