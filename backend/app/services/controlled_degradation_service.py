"""R-CD1: one exact-source narration card after one exhausted targeted repair."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.models.appearance_generation import AppearanceShotUsage
from app.models.audio_drive import ShotAudioEvent
from app.models.chapter_shot_split import ChapterShotSplitRun, ShotSource
from app.models.llm_log import LLMLog
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.audio_drive import AudioDriveRepository
from app.schemas.chapter_shot_split import (parse_controlled_degradation_output, parse_output,
    parse_repair_output)
from app.services.chapter_asset_parse_service import digest, source_hash
from app.services.chapter_scope import (OWNERSHIP_VERSION, collect_scope, ownership_source,
    source_window_version, validate_plan)
from app.services.source_speech import direct_speech_matches


VERSION='chapter-controlled-degradation-v1'
DISPOSITION='DEGRADED_NARRATION_CARD'
POLICY_PATH=Path(__file__).resolve().parents[2]/'prompt_templates'/'chapter_degradation_v1.json'


def load_policy():
    raw=POLICY_PATH.read_text(encoding='utf-8');value=json.loads(raw)
    if (value.get('version')!=VERSION or value.get('kind')!='NARRATION_CARD'
            or value.get('completion_disposition')!=DISPOSITION or value.get('max_cards')!=1
            or value.get('repair_attempt')!=1 or value.get('repair_budget')!=1
            or not value.get('allowed_terminal_errors') or not isinstance(value.get('render'),dict)):
        raise ValueError('CONTROLLED_DEGRADATION_POLICY_INVALID')
    return {'file':'prompt_templates/chapter_degradation_v1.json','hash':digest(raw),'definition':value}


def _task_meta(task):
    try:return json.loads(task.metadata_json or '{}') if task else {}
    except (TypeError,ValueError):return {}


def _failed_run_proof(db,run,*,log_type):
    task=db.get(Task,run.task_id) if run else None
    log=db.get(LLMLog,run.call.get('llm_log_id')) if run and run.call.get('llm_log_id') else None
    meta=_task_meta(task)
    if (not run or run.status!='NEEDS_REVIEW' or digest(run.inputs)!=run.input_hash
            or not task or task.status!='failed' or task.type!='chapter_shot_split'
            or task.novel_id!=run.novel_id or task.chapter_id!=run.chapter_id
            or meta.get('execution_purpose')!='production' or meta.get('split_run_id')!=run.id
            or meta.get('input_hash')!=run.input_hash or not run.call.get('response')
            or not log or log.status!='success' or log.task_type!=log_type
            or log.response!=run.call.get('response') or log.system_prompt!=run.inputs.get('system_prompt')
            or log.user_prompt!=run.inputs.get('user_prompt') or log.novel_id!=run.novel_id
            or log.chapter_id!=run.chapter_id):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_PARENT_PROOF_INVALID')
    return task,log


def _summary(plan,target_index):
    values={'characters':[],'scenes':[],'props':[]}
    for shot in plan['shots']:
        if shot['id']==target_index:continue
        names={'characters':shot['characters'],'scenes':[shot['scene']],'props':shot['props']}
        for kind,items in names.items():
            for item in items:
                if item not in values[kind]:values[kind].append(item)
    return values


def narration_card(original,content,policy):
    source=ownership_source(content,original)['ownership_range'];text=content[source['start']:source['end']]
    definition=policy['definition'];key=definition['treatment_key']
    return {'id':original['id'],'completion_disposition':DISPOSITION,
        'source_citations':deepcopy(original['source_citations']),
        'source_ownership':deepcopy(original['source_ownership']),
        'description':definition['description'],'video_description':definition['video_description'],
        'characters':[],'scene':'','props':[],'duration':original['duration'],'continuity_mode':'NORMAL',
        'dialogues':[],'audio_events':[{'order':1,'type':'NARRATION','voice_owner':'旁白',
            'visible_speaker':None,'requires_visible_lipsync':False,'text':text,
            'emotion_prompt':definition['emotion_prompt'],'pause_after':definition['pause_after'],
            'treatment_ref':key}],
        'source_treatments':[{'key':key,'type':'NARRATION',
            'source_evidence':[deepcopy(original['source_ownership'])],
            'visual_targets':[],'audio_type':'NARRATION'}]}


def compose_plan(parent_plan,target_index,content,policy):
    if not 1<=target_index<=len(parent_plan['shots']):raise HTTPException(409,'CONTROLLED_DEGRADATION_TARGET_INVALID')
    original=parent_plan['shots'][target_index-1]
    source=ownership_source(content,original)['ownership_range'];text=content[source['start']:source['end']]
    if (original['dialogues'] or original['audio_events']
            or not original.get('source_treatments')
            or any(item.get('type')!='VISUAL' for item in original['source_treatments'])
            or list(direct_speech_matches(text))):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_TARGET_INELIGIBLE')
    card=narration_card(original,content,policy);shots=deepcopy(parent_plan['shots']);shots[target_index-1]=card
    summary=_summary(parent_plan,target_index)
    result={'source_contract_version':OWNERSHIP_VERSION,'chapter':parent_plan['chapter'],
        **summary,'unresolved_assets':[],'shots':shots}
    parsed=parse_controlled_degradation_output(json.dumps(result,ensure_ascii=False))
    return parsed,card,source


def lineage(db,novel_id,chapter_id,repair_run_id,*,require_latest=True):
    policy=load_policy();repair=db.query(ChapterShotSplitRun).filter_by(
        id=repair_run_id,novel_id=novel_id,chapter_id=chapter_id).first()
    if not repair:raise HTTPException(404,'分镜修复记录不存在')
    if require_latest:
        latest=db.query(ChapterShotSplitRun).filter_by(chapter_id=chapter_id).order_by(
            ChapterShotSplitRun.created_at.desc(),ChapterShotSplitRun.id.desc()).first()
        if not latest or latest.id!=repair.id:raise HTTPException(409,'CONTROLLED_DEGRADATION_REPAIR_NOT_LATEST')
    _repair_task,repair_log=_failed_run_proof(db,repair,log_type='shot_contract_auto_repair')
    auto=repair.inputs.get('auto_repair') or {}
    if (auto.get('attempt')!=policy['definition']['repair_attempt']
            or auto.get('budget')!=policy['definition']['repair_budget']):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_REPAIR_BUDGET_REQUIRED')
    parent=db.get(ChapterShotSplitRun,auto.get('parent_run_id'))
    if not parent or parent.inputs.get('auto_repair'):raise HTTPException(409,'CONTROLLED_DEGRADATION_FULL_PARENT_REQUIRED')
    _failed_run_proof(db,parent,log_type='split_chapter')
    if (auto.get('original_response')!=parent.call.get('response')
            or auto.get('parent_llm_log_id')!=parent.call.get('llm_log_id')):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_LINEAGE_CHANGED')
    repair_plan=auto.get('repair_plan') or {};targets=repair_plan.get('targets') or []
    if repair_plan.get('repair_type')!='SHOT_CROSSES_APPEARANCE_BOUNDARY' or len(targets)!=1:
        raise HTTPException(409,'CONTROLLED_DEGRADATION_SINGLE_TARGET_REQUIRED')
    target_index=targets[0].get('shot_index')
    try:
        patch=parse_repair_output(repair.call['response'])
    except ValueError as exc:raise HTTPException(409,'CONTROLLED_DEGRADATION_REPAIR_OUTPUT_INVALID') from exc
    if [item['shot_index'] for item in patch['repairs']]!=[target_index]:
        raise HTTPException(409,'CONTROLLED_DEGRADATION_REPAIR_TARGET_CHANGED')
    issue=(repair.issues or [{}])[0];terminal=(issue.get('repair') or {}).get('validatorError') or issue.get('message')
    if issue.get('code')!='STILL_INVALID' or not any(str(terminal).startswith(code)
            for code in policy['definition']['allowed_terminal_errors']):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_HUMAN_REQUIRED_REPAIR_REQUIRED')
    if not any((item.get('code')=='NEEDS_REVIEW' and str(item.get('message','')).startswith(
            policy['definition']['allowed_parent_error'])) for item in parent.issues or []):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_PARENT_ERROR_UNSUPPORTED')
    parent_plan=parse_output(parent.call['response'],parent.inputs.get('source_contract_version'),
        parent.inputs.get('source_window_version'))
    if targets[0].get('original_shot')!=parent_plan['shots'][target_index-1]:
        raise HTTPException(409,'CONTROLLED_DEGRADATION_TARGET_SNAPSHOT_CHANGED')
    from app.services.chapter_shot_split_service import auto_repair_findings
    from app.services.shot_contract_auto_repair import (apply_response as apply_auto_repair,
        build_plan as build_auto_repair_plan)
    findings=auto_repair_findings(parent_plan,parent.inputs['basis'],'SHOT_CROSSES_APPEARANCE_BOUNDARY:')
    scene_aware=any(target.get('scene_policy') for target in targets)
    if (findings!=auto.get('violations_before')
            or build_auto_repair_plan(findings,parent_plan,parent.inputs['basis'],scene_aware=scene_aware)!=repair_plan):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_REPAIR_PLAN_CHANGED')
    decisions=[] if scene_aware else None
    try:
        apply_auto_repair(parent_plan,repair_plan,repair.call['response'],parent.inputs['basis'],decisions)
    except ValueError as exc:replayed_error=str(exc)
    else:raise HTTPException(409,'CONTROLLED_DEGRADATION_REPAIR_NO_LONGER_FAILS')
    if replayed_error!=str(terminal):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_REPAIR_FAILURE_CHANGED')
    template=auto.get('template') or {};execution=repair_log.execution_metadata or {}
    if (template.get('hash')!=digest(template.get('text') or '')
            or repair_log.prompt_template_name!=template.get('name')
            or execution.get('operation')!='SHOT_CONTRACT_AUTO_REPAIR'
            or execution.get('repairType')!=repair_plan.get('repair_type')
            or execution.get('attempt')!=1 or execution.get('budget')!=1
            or execution.get('parentRunId')!=parent.id
            or execution.get('originalResponseHash')!=digest(parent.call['response'])
            or execution.get('repairResponseHash')!=digest(repair.call['response'])
            or execution.get('outcome')!='STILL_INVALID'
            or execution.get('validatorError')!=replayed_error
            or any(execution.get(key)!=value for key,value in (issue.get('repair') or {}).items())):
        raise HTTPException(409,'CONTROLLED_DEGRADATION_REPAIR_EXECUTION_PROOF_INVALID')
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).populate_existing().first()
    if not chapter or source_hash(chapter)!=parent.inputs['basis']['source']['hash']:
        raise HTTPException(409,'CONTROLLED_DEGRADATION_SOURCE_CHANGED')
    basis=collect_scope(db,novel_id,chapter_id,OWNERSHIP_VERSION)
    for key in ('source','scope','timeline','appearance_boundaries','source_windows','source_window_contract'):
        if parent.inputs['basis'].get(key)!=basis.get(key):
            raise HTTPException(409,'CONTROLLED_DEGRADATION_SCOPE_CHANGED: '+key)
    plan,card,source=compose_plan(parent_plan,target_index,basis['source']['content'],policy)
    prepared=validate_plan(plan,basis,controlled_degradation={'cards':{target_index:card}})
    partition=[{'id':item['shot']['id'],'start':item['start'],'end':item['end'],
        'disposition':item['completion_disposition']} for item in prepared]
    proof={'version':VERSION,'policy':policy,'parent_run_id':parent.id,'parent_input_hash':parent.input_hash,
        'parent_response_hash':digest(parent.call['response']),'parent_issues_hash':digest(parent.issues),
        'repair_run_id':repair.id,'repair_input_hash':repair.input_hash,
        'repair_response_hash':digest(repair.call['response']),'repair_issues_hash':digest(repair.issues),
        'target_shot_index':target_index,'source_range':[source['start'],source['end']],
        'target_before_hash':digest(parent_plan['shots'][target_index-1]),'card_hash':digest(card),
        'partition_hash':digest(partition),'composed_plan_hash':digest(plan)}
    return {'policy':policy,'parent':parent,'repair':repair,'basis':basis,'plan':plan,'card':card,
        'prepared':prepared,'proof':proof,'partition':partition}


def controlled_result(context):
    proof=context['proof']
    return {'version':VERSION,'kind':'NARRATION_CARD','outcome':'SUCCEEDED_WITH_DEGRADATION',
        'parentRunId':proof['parent_run_id'],'repairRunId':proof['repair_run_id'],
        'targetShotIndex':proof['target_shot_index'],'sourceRange':proof['source_range'],
        'targetBeforeHash':proof['target_before_hash'],'cardHash':proof['card_hash'],
        'partitionHash':proof['partition_hash'],'composedPlanHash':proof['composed_plan_hash'],
        'normalCount':len(context['prepared'])-1,'degradedCount':1}


def replay(db,run):
    controlled=run.inputs.get('controlled_degradation') or {}
    context=lineage(db,run.novel_id,run.chapter_id,controlled.get('repair_run_id'),require_latest=False)
    if context['proof']!=controlled.get('proof') or context['basis']!=run.inputs.get('basis'):
        raise ValueError('CONTROLLED_DEGRADATION_INPUT_CHANGED')
    parsed=parse_controlled_degradation_output(run.call.get('response') or '')
    if parsed!=context['plan'] or run.call.get('composed_response_hash')!=digest(parsed):
        raise ValueError('CONTROLLED_DEGRADATION_COMPOSITION_CHANGED')
    expected=controlled_result(context)
    return parsed,{'cards':{context['proof']['target_shot_index']:context['card']}},expected


def admit(db,novel_id,chapter_id,repair_run_id):
    existing=db.query(ChapterShotSplitRun).filter_by(novel_id=novel_id,chapter_id=chapter_id,status='SUCCEEDED').all()
    existing=next((row for row in existing if (row.inputs.get('controlled_degradation') or {}).get('repair_run_id')==repair_run_id),None)
    if existing:
        from app.services.chapter_shot_split_service import checked_run
        checked_run(db,existing)
        return {'splitRunId':existing.id,'taskId':existing.task_id,'status':existing.status,
            'controlledDegradation':existing.result.get('controlled_degradation'),'idempotent':True}
    context=lineage(db,novel_id,chapter_id,repair_run_id)
    from app.services.chapter_shot_split_service import (audio_snapshot,no_active_shot_tasks,
        previous_shots,snapshot,source_payload)
    from app.services.rebuild_context import stage_parent
    from app.services.shot_treatment_contract import make_contract
    no_active_shot_tasks(db,chapter_id);parent_task_id=stage_parent(db,chapter_id)
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).populate_existing().first()
    if db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).update({'id':chapter_id},synchronize_session=False)!=1:
        raise HTTPException(409,'CONTROLLED_DEGRADATION_CHAPTER_CHANGED')
    db.expire_all();context=lineage(db,novel_id,chapter_id,repair_run_id)
    no_active_shot_tasks(db,chapter_id)
    now=datetime.utcnow();rid,tid,token=str(uuid4()),str(uuid4()),str(uuid4())
    inputs={'basis':context['basis'],'source_contract_version':OWNERSHIP_VERSION,
        'source_window_version':source_window_version(context['basis']['version']),
        'treatment_contract_version':__import__('app.services.narration_coverage',fromlist=['VERSION']).VERSION,
        'controlled_degradation':{'version':VERSION,'repair_run_id':repair_run_id,'proof':context['proof']},
        'previous_shots':previous_shots(db,chapter_id),'previous_chapter_resources':{
            key:getattr(chapter,key) for key in ('parsed_data','shot_images','shot_videos','transition_videos','final_video','status','progress')}}
    task=Task(id=tid,type='chapter_shot_split',status='running',novel_id=novel_id,chapter_id=chapter_id,
        parent_task_id=parent_task_id,name='R-CD1 章回受控降级',description='发布一个 exact-source NARRATION_CARD child',
        progress=1,current_step='验证受控降级 child',claim_token=token,started_at=now,heartbeat_at=now)
    run=ChapterShotSplitRun(id=rid,novel_id=novel_id,chapter_id=chapter_id,task_id=tid,
        version=context['basis']['version'],status='RUNNING',inputs=inputs,input_hash=digest(inputs),
        call={'success':True,'kind':'DETERMINISTIC_CONTROLLED_DEGRADATION',
            'response':json.dumps(context['plan'],ensure_ascii=False,separators=(',',':')),
            'composed_response_hash':digest(context['plan'])},expires_at=now+timedelta(minutes=15))
    task.metadata_json=json.dumps({'execution_purpose':'production','delivery_mode':'CONTROLLED_DEGRADATION','split_run_id':rid,
        'input_hash':run.input_hash,'repair_run_id':repair_run_id},ensure_ascii=False)
    try:
        old_ids=[row['shot']['id'] for row in inputs['previous_shots']]
        AudioDriveRepository(db).cleanup_shots_audio_drive(old_ids,commit=False)
        if old_ids:
            db.query(AppearanceShotUsage).filter(AppearanceShotUsage.shot_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(ShotSource).filter(ShotSource.shot_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(Shot).filter(Shot.id.in_(old_ids)).delete(synchronize_session=False)
        db.add_all([task,run]);db.flush();sources={};created=[]
        for item in context['prepared']:
            planned=item['shot'];disposition=item['completion_disposition']
            shot=Shot(id=str(uuid4()),chapter_id=chapter_id,index=planned['id'],description=planned['description'],
                video_description=planned['video_description'],characters=json.dumps(planned['characters'],ensure_ascii=False),
                scene=planned['scene'],props=json.dumps(planned['props'],ensure_ascii=False),dialogues=json.dumps(planned['dialogues'],ensure_ascii=False),
                duration=planned['duration'],estimated_duration=planned['duration'],continuity_mode=planned['continuity_mode'],
                completion_disposition=disposition,image_status='not_required' if disposition==DISPOSITION else 'pending')
            db.add(shot);db.flush();event_ids=[]
            for event in item['audio']:
                row=ShotAudioEvent(shot_id=shot.id,**AudioDriveRepository(db)._normalize_event_payload(event,event['order']))
                db.add(row);db.flush();event_ids.append(row.id)
            source=ShotSource(shot_id=shot.id,run_id=rid,source_start=item['start'],source_end=item['end'],
                source_hash=context['basis']['source']['hash'],evidence=item['evidence'],ranges=item['ranges'],
                bindings=item['bindings'],snapshot=snapshot(shot),audio_snapshot=audio_snapshot(db,shot.id),
                treatment_contract=make_contract(planned,item['treatment_coverage'],event_ids),source_contract=item['source_contract'])
            source.seal=digest(source_payload(source));db.add(source);sources[shot.id]=source_payload(source);created.append(shot)
        from app.services.narrator_profile_service import ensure_narrator
        ensure_narrator(db,novel_id)
        summary={key:context['plan'][key] for key in ('chapter','characters','scenes','props')}
        chapter=db.get(Chapter,chapter_id);chapter.parsed_data=json.dumps(summary,ensure_ascii=False)
        chapter.status,chapter.progress='pending',0
        for key in ('shot_images','shot_videos','transition_videos','final_video','final_video_task_id'):
            if hasattr(chapter,key):setattr(chapter,key,None)
        degradation=controlled_result(context);run.result={'sources':sources,'summary':summary,
            'controlled_degradation':degradation};run.result_hash=digest(run.result);run.status='SUCCEEDED';run.completed_at=now
        task.status,task.progress,task.current_step,task.completed_at='completed',100,'R-CD1 child 已发布',now
        task.metadata_json=json.dumps({'execution_purpose':'production','delivery_mode':'CONTROLLED_DEGRADATION','split_run_id':rid,
            'input_hash':run.input_hash,'result_hash':run.result_hash,'repair_run_id':repair_run_id,
            'outcome':'SUCCEEDED_WITH_DEGRADATION','degraded_ranges':[context['proof']['source_range']]},ensure_ascii=False)
        db.commit()
    except Exception:
        db.rollback();raise
    return {'splitRunId':rid,'taskId':tid,'status':'SUCCEEDED','controlledDegradation':degradation,'idempotent':False}
