"""Atomic, provenance-checked ChapterScope Shot publication."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.models.chapter_shot_split import ChapterShotSplitRun as Run, ShotSource
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.models.audio_drive import ShotAudioEvent
from app.models.appearance_generation import AppearanceShotUsage
from app.repositories.audio_drive import AudioDriveRepository
from app.repositories.shot_repository import ShotRepository
from app.services.chapter_scope import (VERSION, OWNERSHIP_VERSION, TASK_TYPE, collect_scope,
    collect_appearance_crossing_findings, collect_visible_character_findings, request_prompts,
    run_version, source_window_version, validate_plan, SplitReview)
from app.services.chapter_asset_parse_service import digest
from app.schemas.chapter_shot_split import parse_output, parse_repair_output, read_historical_output
from app.services.llm_service import LLMService
from app.services.shot_contract_auto_repair import (AutoRepairReview, apply_response as apply_auto_repair,
    BOUNDARY_REPAIR_TYPE, CLOSURE_REPAIR_TYPE, build_plan as build_auto_repair_plan,
    classify as classify_auto_repair, delta as auto_repair_delta,
    render_prompts as render_auto_repair_prompts, resolve_template as resolve_auto_repair_template)


AUTO_REPAIR_GOVERNANCE_VERSION='root-lineage-auto-repair-v1'
HUMAN_CORRECTION_VERSION='human-authored-plan-correction-v1'
MAX_REPAIR_ROUNDS_PER_ROOT_PLAN=3
REPAIR_FAMILY_ORDER=(BOUNDARY_REPAIR_TYPE,CLOSURE_REPAIR_TYPE)


def snapshot(shot):
    result={key: getattr(shot, key) for key in ("id", "chapter_id", "index", "description", "video_description", "characters", "scene", "props", "dialogues", "continuity_mode", "estimated_duration")}
    if getattr(shot,'completion_disposition','NORMAL')!='NORMAL':result['completion_disposition']=shot.completion_disposition
    return result


def audio_snapshot(db, shot_id):
    fields = ("event_order", "event_type", "voice_owner_character_id", "voice_owner_name", "visible_speaker_character_id", "visible_speaker_name", "requires_visible_lipsync", "text", "emotion_prompt", "pause_after")
    return [{key: getattr(row, key) for key in fields} for row in db.query(ShotAudioEvent).filter_by(shot_id=shot_id).order_by(ShotAudioEvent.event_order)]


def previous_shots(db, chapter_id):
    rows = db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index, Shot.id).populate_existing().all()
    return [{"shot": {c.name: (getattr(row, c.name).isoformat() if isinstance(getattr(row,c.name), datetime) else getattr(row,c.name)) for c in Shot.__table__.columns},
             "audio": audio_snapshot(db, row.id)} for row in rows]


def no_active_shot_tasks(db, chapter_id):
    ids = db.query(Shot.id).filter_by(chapter_id=chapter_id)
    task = db.query(Task).filter(Task.status.in_(["pending", "queued", "running"]),
        (Task.shot_id.in_(ids)) | ((Task.chapter_id == chapter_id) & Task.type.in_([
            "shot_image_batch", "shot_video_batch", "chapter_video", "transition_video", "audio_prepare", "narration_card_video"]))).first()
    if task:
        raise HTTPException(409, f"SHOT_TASK_ACTIVE: {task.id}")


def update_log_execution_metadata(db, log_id, metadata, *, commit=True):
    if not log_id:
        return
    if db.query(LLMLog).filter_by(id=log_id).update({"execution_metadata":deepcopy(metadata)},synchronize_session=False)!=1:
        raise RuntimeError("SHOT_CONTRACT_REPAIR_LOG_MISSING")
    if commit:db.commit();db.expire_all()


def auto_repair_findings(data,basis,validation_error):
    if str(validation_error).startswith('SHOT_CROSSES_APPEARANCE_BOUNDARY:'):
        return collect_appearance_crossing_findings(data,basis) if basis.get('source_windows') is not None else []
    return collect_visible_character_findings(data)


def collect_repairable_inventory(data,basis):
    return {
        BOUNDARY_REPAIR_TYPE:collect_appearance_crossing_findings(data,basis)
            if basis.get('source_windows') is not None else [],
        CLOSURE_REPAIR_TYPE:collect_visible_character_findings(data),
    }


def _key_rows(keys):
    return [{'root_shot_index':index,'violation_family':family} for index,family in sorted(keys)]


def _row_keys(rows):
    return {(int(row['root_shot_index']),str(row['violation_family'])) for row in rows or []}


def _finding_keys(findings,origins):
    keys=set()
    for finding in findings:
        index=int(finding['shot_index'])
        if index<1 or index>len(origins):raise ValueError('AUTO_REPAIR_GOVERNANCE_TARGET_ORIGIN_INVALID')
        keys.add((int(origins[index-1]),str(finding['code'])))
    return keys


def _advance_origins(origins,repair_plan,raw_response):
    if repair_plan['repair_type']!=BOUNDARY_REPAIR_TYPE:return list(origins)
    parsed=parse_repair_output(raw_response)
    counts={item['shot_index']:len(item['replacements']) for item in parsed['repairs']}
    result=[]
    for index,origin in enumerate(origins,1):result.extend([origin]*counts.get(index,1))
    return result


def _validation_error(data,basis):
    try:validate_plan(data,basis)
    except ValueError as exc:return str(exc)
    return None


def _select_repair(data,basis,origins,attempted,repair_plan_hint=None):
    validation_error=_validation_error(data,basis)
    error_code=(validation_error or '').split(':',1)[0].split(';',1)[0]
    if error_code not in REPAIR_FAMILY_ORDER:return None,validation_error
    inventory=collect_repairable_inventory(data,basis)
    for family in REPAIR_FAMILY_ORDER:
        findings=[item for item in inventory[family]
            if (origins[int(item['shot_index'])-1],family) not in attempted]
        if findings and classify_auto_repair(findings,family+':')=='AUTO_REPAIRABLE':
            options={}
            if family==BOUNDARY_REPAIR_TYPE and repair_plan_hint and repair_plan_hint.get('repair_type')==family:
                policies=[target.get('scene_policy') for target in repair_plan_hint.get('targets',[])]
                options['scene_aware']=all(policy is not None for policy in policies)
                versions={policy.get('version') for policy in policies if policy}
                if options['scene_aware'] and len(versions)==1:options['scene_policy_version']=next(iter(versions))
            plan=build_auto_repair_plan(findings,data,basis,**options)
            return {'family':family,'findings':findings,'repair_plan':plan,
                'target_keys':_finding_keys(findings,origins),'inventory':inventory},validation_error
    return None,validation_error


def _root_receipt(db,run,basis):
    human=(run.inputs.get('human_authored_correction') or {}) if run else {}
    allowed_status={'NEEDS_REVIEW','SUCCEEDED'} if human else {'NEEDS_REVIEW'}
    if (not run or run.status not in allowed_status or run.inputs.get('auto_repair')
            or run.inputs.get('controlled_degradation') or digest(run.inputs)!=run.input_hash
            or (run.status=='SUCCEEDED' and digest(run.result)!=run.result_hash)
            or run.inputs.get('basis')!=basis):
        raise ValueError('AUTO_REPAIR_GOVERNANCE_ROOT_INVALID')
    task=db.get(Task,run.task_id);log=db.get(LLMLog,run.call.get('llm_log_id')) if run.call.get('llm_log_id') else None
    meta=json.loads(task.metadata_json or '{}') if task else {}
    if human:
        parent=db.get(Run,human.get('parent_run_id'));parent_task=db.get(Task,parent.task_id) if parent else None
        parent_log=db.get(LLMLog,parent.call.get('llm_log_id')) if parent and parent.call.get('llm_log_id') else None
        parent_meta=json.loads(parent_task.metadata_json or '{}') if parent_task else {}
        expected_task_status='completed' if run.status=='SUCCEEDED' else 'failed'
        if (human.get('version')!=HUMAN_CORRECTION_VERSION or not task or task.status!=expected_task_status
                or task.type!=TASK_TYPE or meta.get('execution_purpose')!='production'
                or meta.get('delivery_mode')!='HUMAN_AUTHORED_PLAN_CORRECTION'
                or meta.get('input_hash')!=run.input_hash or meta.get('split_run_id')!=run.id
                or log is not None or run.call.get('kind')!='HUMAN_AUTHORED_PLAN_CORRECTION'
                or not run.call.get('success') or not parent or parent.status!='NEEDS_REVIEW'
                or digest(parent.inputs)!=parent.input_hash or human.get('parent_input_hash')!=parent.input_hash
                or human.get('parent_response_hash')!=digest(parent.call.get('response'))
                or not parent_task or parent_task.status!='failed' or parent_meta.get('input_hash')!=parent.input_hash
                or parent_meta.get('split_run_id')!=parent.id or not parent_log or parent_log.status!='success'
                or parent_log.response!=parent.call.get('response')):
            raise ValueError('HUMAN_AUTHORED_CORRECTION_PROOF_INVALID')
        if run.status=='SUCCEEDED' and (meta.get('result_hash')!=run.result_hash
                or run.result.get('human_authored_correction')!=human):
            raise ValueError('HUMAN_AUTHORED_CORRECTION_RESULT_CHANGED')
        data=parse_output(run.call.get('response'),run.inputs.get('source_contract_version'),source_window_version(run.version))
        if human.get('after_plan_hash')!=digest(data):raise ValueError('HUMAN_AUTHORED_CORRECTION_CHANGED')
        return data,None
    frozen_llm=run.inputs.get('llm') or {};template=(run.inputs.get('basis') or {}).get('template') or {}
    if (not task or task.status!='failed' or task.type!=TASK_TYPE or task.novel_id!=run.novel_id
            or task.chapter_id!=run.chapter_id or meta.get('execution_purpose')!='production'
            or meta.get('input_hash')!=run.input_hash or meta.get('split_run_id')!=run.id
            or not log or log.status!='success' or log.novel_id!=run.novel_id or log.chapter_id!=run.chapter_id
            or log.provider!=frozen_llm.get('provider') or log.model!=frozen_llm.get('model')
            or log.task_type!='split_chapter' or log.prompt_template_name!=template.get('name')
            or log.response!=run.call.get('response') or log.system_prompt!=run.inputs.get('system_prompt')
            or log.user_prompt!=run.inputs.get('user_prompt')):
        raise ValueError('AUTO_REPAIR_GOVERNANCE_ROOT_PROOF_INVALID')
    data=parse_output(log.response,run.inputs.get('source_contract_version'),source_window_version(run.version))
    return data,log


def _duplicates_repaired_root(db,current,data,basis):
    candidate_hash=digest(data);seen=set()
    for child in db.query(Run).filter_by(chapter_id=current.chapter_id).all():
        governance=((child.inputs.get('auto_repair') or {}).get('governance') or {})
        root_id=governance.get('root_run_id')
        if not root_id or root_id in seen or root_id==current.id:continue
        seen.add(root_id);root=db.get(Run,root_id)
        if (not root or root.version!=current.version or root.inputs.get('basis')!=basis
                or not root.call.get('response')):continue
        try:prior=parse_output(root.call['response'],root.inputs.get('source_contract_version'),source_window_version(root.version))
        except (ValueError,TypeError,KeyError):continue
        if digest(prior)==candidate_hash:return True
    return False


def _governance_context(root,root_log,predecessor,data,basis,origins,attempted,rounds,repair_plan_hint=None):
    if rounds>=MAX_REPAIR_ROUNDS_PER_ROOT_PLAN:return None
    selected,validation_error=_select_repair(data,basis,origins,attempted,repair_plan_hint)
    if not selected:return None
    governance={'version':AUTO_REPAIR_GOVERNANCE_VERSION,'root_run_id':root.id,
        'predecessor_run_id':predecessor.id,'round':rounds+1,'max_rounds':MAX_REPAIR_ROUNDS_PER_ROOT_PLAN,
        'candidate_before':deepcopy(data),'candidate_before_hash':digest(data),'origins_before':list(origins),
        'attempted_before':_key_rows(attempted),'target_keys':_key_rows(selected['target_keys']),
        'inventory_hash':digest(selected['inventory'])}
    return {'parent_run_id':root.id,'parent_llm_log_id':root_log.id if root_log else None,'original_response':root.call['response'],
        'original_plan':deepcopy(data),'violations_before':selected['findings'],'validation_error':validation_error,
        'repair_plan':selected['repair_plan'],'governance':governance}


def _governance_delta(delta,governance,attempted_after,origins_after,inventory_after):
    return {**delta,'governance':{'version':AUTO_REPAIR_GOVERNANCE_VERSION,
        'rootRunId':governance['root_run_id'],'predecessorRunId':governance['predecessor_run_id'],
        'round':governance['round'],'maxRounds':governance['max_rounds'],
        'targetKeys':deepcopy(governance['target_keys']),'attemptedKeys':_key_rows(attempted_after),
        'candidateBeforeHash':governance['candidate_before_hash'],'candidateAfterHash':delta['afterHash'],
        'originsAfter':list(origins_after),'inventoryAfterHash':digest(inventory_after)}}


def _evaluate_governance_repair(auto,raw_response,basis,source_contract_version,run_profile):
    governance=auto['governance'];before=deepcopy(governance['candidate_before'])
    origins=list(governance['origins_before']);attempted=_row_keys(governance['attempted_before'])
    target_keys=_row_keys(governance['target_keys']);repair_type=auto['repair_plan']['repair_type']
    scene_decisions=[] if any(target.get('scene_policy') for target in auto['repair_plan'].get('targets',[])) else None
    after=before;origins_after=origins;prepared=None;validator_error=None
    if raw_response==auto.get('original_response'):
        validator_error=auto.get('validation_error') or _validation_error(before,basis)
        outcome='REPAIR_NO_EFFECT'
    else:
        try:
            after=apply_auto_repair(before,auto['repair_plan'],raw_response,basis,scene_decisions)
            after=parse_output(json.dumps(after,ensure_ascii=False,separators=(',',':')),
                source_contract_version,source_window_version(run_profile))
            origins_after=_advance_origins(origins,auto['repair_plan'],raw_response)
        except ValueError as exc:
            validator_error=str(exc);outcome='STILL_INVALID'
        else:
            try:prepared=validate_plan(after,basis)
            except ValueError as exc:validator_error=str(exc)
            after_family=auto_repair_findings(after,basis,repair_type+':')
            unresolved=_finding_keys(after_family,origins_after)&target_keys
            before_codes={family for family,items in collect_repairable_inventory(before,basis).items() if items}
            error_code=(validator_error or '').split(':',1)[0].split(';',1)[0]
            if digest(after)==digest(before):outcome='REPAIR_NO_EFFECT'
            elif unresolved:outcome='STILL_INVALID'
            elif validator_error and error_code not in before_codes:outcome='NEW_VIOLATIONS'
            elif validator_error:outcome='REPAIRED_WITH_REMAINING_FINDINGS'
            else:outcome='REPAIRED'
    after_findings=auto_repair_findings(after,basis,repair_type+':')
    attempted_after=attempted|target_keys;inventory_after=collect_repairable_inventory(after,basis)
    delta=auto_repair_delta(before,after,auto['violations_before'],after_findings,
        repair_type=repair_type,outcome=outcome,validator_error=validator_error,scene_decisions=scene_decisions)
    delta=_governance_delta(delta,governance,attempted_after,origins_after,inventory_after)
    return after,origins_after,attempted_after,delta,prepared


def _governance_chain(db,head):
    auto=head.inputs.get('auto_repair') or {};governance=auto.get('governance') or {}
    root_id=governance.get('root_run_id')
    if governance.get('version')!=AUTO_REPAIR_GOVERNANCE_VERSION or not root_id:
        raise ValueError('AUTO_REPAIR_GOVERNANCE_RECEIPT_INVALID')
    chain=[];current=head;seen=set()
    while current.id!=root_id:
        if current.id in seen:raise ValueError('AUTO_REPAIR_GOVERNANCE_CYCLE')
        seen.add(current.id);child_governance=(current.inputs.get('auto_repair') or {}).get('governance') or {}
        if (child_governance.get('version')!=AUTO_REPAIR_GOVERNANCE_VERSION
                or child_governance.get('root_run_id')!=root_id):
            raise ValueError('AUTO_REPAIR_GOVERNANCE_CHAIN_CHANGED')
        chain.append(current);current=db.get(Run,child_governance.get('predecessor_run_id'))
        if not current:raise ValueError('AUTO_REPAIR_GOVERNANCE_PREDECESSOR_MISSING')
    return current,list(reversed(chain))


def _interrupted_repair_issue(run,message):
    governance=((run.inputs.get('auto_repair') or {}).get('governance') or {})
    return {'code':'REPAIR_INTERRUPTED','message':message,'governance':{
        'version':AUTO_REPAIR_GOVERNANCE_VERSION,'rootRunId':governance.get('root_run_id'),
        'predecessorRunId':governance.get('predecessor_run_id'),'round':governance.get('round'),
        'maxRounds':governance.get('max_rounds'),'targetKeys':deepcopy(governance.get('target_keys') or [])}}


def mark_repair_interruption(task,run,message):
    governance=((run.inputs.get('auto_repair') or {}).get('governance') or {})
    meta=json.loads(task.metadata_json or '{}')
    meta['auto_repair_interruption']={'version':AUTO_REPAIR_GOVERNANCE_VERSION,
        'rootRunId':governance.get('root_run_id'),'predecessorRunId':governance.get('predecessor_run_id'),
        'round':governance.get('round'),'targetKeys':deepcopy(governance.get('target_keys') or []),
        'message':message}
    task.metadata_json=json.dumps(meta,ensure_ascii=False)


def _replay_governance_head(db,head,basis):
    root,chain=_governance_chain(db,head);candidate,root_log=_root_receipt(db,root,basis)
    origins=list(range(1,len(candidate['shots'])+1));attempted=set();predecessor=root;rounds=0
    for child in chain:
        auto=child.inputs.get('auto_repair') or {};governance=auto.get('governance') or {}
        expected=_governance_context(root,root_log,predecessor,candidate,basis,origins,attempted,rounds,
            auto.get('repair_plan'))
        if not expected:raise ValueError('AUTO_REPAIR_GOVERNANCE_UNAUTHORIZED_ROUND')
        for key in ('parent_run_id','parent_llm_log_id','original_response','violations_before','repair_plan','governance'):
            if auto.get(key)!=expected.get(key):raise ValueError('AUTO_REPAIR_GOVERNANCE_PLAN_CHANGED')
        template=auto.get('template') or {}
        if (digest(child.inputs)!=child.input_hash or child.inputs.get('basis')!=basis
                or template.get('hash')!=digest(template.get('text') or '')):
            raise ValueError('AUTO_REPAIR_GOVERNANCE_INPUT_CHANGED')
        issue=(child.issues or [{}])[0]
        if issue.get('code')=='REPAIR_INTERRUPTED':
            task=db.get(Task,child.task_id);meta=json.loads(task.metadata_json or '{}') if task else {}
            expected_issue=_interrupted_repair_issue(child,issue.get('message'))
            log=db.get(LLMLog,child.call.get('llm_log_id')) if child.call.get('llm_log_id') else None
            frozen_llm=child.inputs.get('llm') or {}
            expected_marker={'version':AUTO_REPAIR_GOVERNANCE_VERSION,'rootRunId':governance['root_run_id'],
                'predecessorRunId':governance['predecessor_run_id'],'round':governance['round'],
                'targetKeys':deepcopy(governance['target_keys']),'message':issue.get('message')}
            if log and (log.status not in {'success','error'} or log.task_type!='shot_contract_auto_repair'
                    or (log.response!=child.call.get('response') if log.status=='success' else
                        (log.response or '')!=(child.call.get('response') or ''))
                    or log.system_prompt!=child.inputs.get('system_prompt')
                    or log.user_prompt!=child.inputs.get('user_prompt') or log.provider!=frozen_llm.get('provider')
                    or log.model!=frozen_llm.get('model') or log.prompt_template_name!=template.get('name')):
                raise ValueError('AUTO_REPAIR_GOVERNANCE_INTERRUPTED_CALL_CHANGED')
            if (child.status!='NEEDS_REVIEW' or issue!=expected_issue or not task
                    or task.status not in {'failed','cancelled'} or meta.get('execution_purpose')!='production'
                    or meta.get('input_hash')!=child.input_hash or meta.get('split_run_id')!=child.id
                    or meta.get('auto_repair_interruption')!=expected_marker
                    or (child.call.get('llm_log_id') and not log)):
                raise ValueError('AUTO_REPAIR_GOVERNANCE_INTERRUPTION_CHANGED')
            execution=(log.execution_metadata or {}) if log else {}
            if child.call.get('composed_response_hash') is not None:
                if not log or log.status!='success':raise ValueError('AUTO_REPAIR_GOVERNANCE_INTERRUPTED_DELTA_MISSING')
                after,origins_after,attempted_after,delta,_prepared=_evaluate_governance_repair(
                    auto,log.response,basis,child.inputs.get('source_contract_version'),child.version)
                if (child.call.get('composed_response_hash')!=digest(after)
                        or any(execution.get(key)!=value for key,value in delta.items())):
                    raise ValueError('AUTO_REPAIR_GOVERNANCE_INTERRUPTED_DELTA_CHANGED')
                candidate,origins,attempted=after,origins_after,attempted_after
            else:
                if execution and (execution.get('outcome')!='VALIDATING' or execution.get('afterHash') is not None
                        or execution.get('operation')!='SHOT_CONTRACT_AUTO_REPAIR'
                        or execution.get('rootRunId')!=root.id or execution.get('predecessorRunId')!=predecessor.id
                        or execution.get('candidateBeforeHash')!=digest(candidate)):
                    raise ValueError('AUTO_REPAIR_GOVERNANCE_INTERRUPTED_BASE_CHANGED')
                attempted|=_row_keys(governance['target_keys'])
            predecessor=child;rounds+=1
            continue
        expected_system,expected_user=render_auto_repair_prompts(template,candidate,auto['repair_plan'])
        log=db.get(LLMLog,child.call.get('llm_log_id'));task=db.get(Task,child.task_id)
        meta=json.loads(task.metadata_json or '{}') if task else {}
        expected_task_status='completed' if child.status=='SUCCEEDED' else 'failed'
        frozen_llm=child.inputs.get('llm') or {}
        if (child.status not in {'NEEDS_REVIEW','SUCCEEDED'} or not task or task.status!=expected_task_status
                or task.type!=TASK_TYPE or task.novel_id!=child.novel_id or task.chapter_id!=child.chapter_id
                or meta.get('execution_purpose')!='production' or meta.get('input_hash')!=child.input_hash
                or meta.get('split_run_id')!=child.id
                or not log or log.status!='success' or log.task_type!='shot_contract_auto_repair'
                or log.novel_id!=child.novel_id or log.chapter_id!=child.chapter_id
                or log.provider!=frozen_llm.get('provider') or log.model!=frozen_llm.get('model')
                or log.response!=child.call.get('response') or log.system_prompt!=expected_system
                or log.user_prompt!=expected_user or log.prompt_template_name!=template.get('name')):
            raise ValueError('AUTO_REPAIR_GOVERNANCE_PROVENANCE_INVALID')
        after,origins_after,attempted_after,delta,prepared=_evaluate_governance_repair(
            auto,log.response,basis,child.inputs.get('source_contract_version'),child.version)
        execution=log.execution_metadata or {}
        if (child.call.get('composed_response_hash')!=digest(after)
                or any(execution.get(key)!=value for key,value in delta.items())
                or execution.get('operation')!='SHOT_CONTRACT_AUTO_REPAIR'
                or execution.get('parentRunId')!=root.id
                or execution.get('originalResponseHash')!=digest(root.call.get('response'))
                or execution.get('repairResponseHash')!=digest(log.response)
                or execution.get('template')!={key:template[key] for key in ('id','name','version','hash')}
                or execution.get('candidateBeforeHash')!=digest(candidate)
                or execution.get('rootRunId')!=root.id
                or execution.get('predecessorRunId')!=predecessor.id):
            raise ValueError('AUTO_REPAIR_GOVERNANCE_DELTA_CHANGED')
        if child.status=='SUCCEEDED':
            if not prepared or child.result.get('auto_repair')!=delta or meta.get('auto_repair')!=delta:
                raise ValueError('AUTO_REPAIR_GOVERNANCE_SUCCESS_CHANGED')
        else:
            if prepared or issue.get('code')!=delta['outcome'] or issue.get('repair')!=delta:
                raise ValueError('AUTO_REPAIR_GOVERNANCE_FAILURE_CHANGED')
        candidate,origins,attempted=after,origins_after,attempted_after
        predecessor=child;rounds+=1
    return {'root':root,'root_log':root_log,'candidate':candidate,'origins':origins,
        'attempted':attempted,'rounds':rounds,'predecessor':predecessor}


def source_payload(row):
    payload={key: getattr(row, key) for key in ("shot_id", "run_id", "source_start", "source_end", "source_hash", "evidence", "ranges", "bindings", "snapshot", "audio_snapshot")}
    if getattr(row,'treatment_contract',None) is not None:payload['treatment_contract']=deepcopy(row.treatment_contract)
    if getattr(row,'source_contract',None) is not None:payload['source_contract']=deepcopy(row.source_contract)
    return payload


def source_contract_version_for_run(run):
    value = run.inputs.get('source_contract_version') if run and isinstance(run.inputs, dict) else None
    try:
        expected = run_version(value,run.version if run else None)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not run or run.version != expected:
        raise HTTPException(409, 'SHOT_SPLIT_VERSION_UNSUPPORTED')
    if run.inputs.get('source_window_version')!=source_window_version(run.version):
        raise HTTPException(409,'SOURCE_WINDOW_VERSION_UNSUPPORTED')
    return value


def latest_run(db, chapter_id):
    return db.query(Run).filter_by(chapter_id=chapter_id).order_by(Run.created_at.desc(), Run.id.desc()).first()


def prior_auto_repair_context(db,novel_id,chapter_id,source_contract_version):
    previous=latest_run(db,chapter_id)
    current_profile=run_version(source_contract_version)
    if (not previous or previous.status!="NEEDS_REVIEW" or previous.inputs.get("auto_repair")
            or previous.version!=current_profile
            or previous.inputs.get("source_contract_version")!=source_contract_version
            or digest(previous.inputs)!=previous.input_hash or not previous.call.get("response")):
        return None
    basis=collect_scope(db,novel_id,chapter_id,source_contract_version,run_profile=current_profile)
    if previous.inputs.get('human_authored_correction'):
        try:data,log=_root_receipt(db,previous,basis);validate_plan(data,basis)
        except ValueError:
            if 'data' not in locals():return None
            return _governance_context(previous,log,previous,data,basis,list(range(1,len(data['shots'])+1)),set(),0)
        return None
    task=db.get(Task,previous.task_id);log=db.get(LLMLog,previous.call.get("llm_log_id")) if previous.call.get("llm_log_id") else None
    task_meta=json.loads(task.metadata_json or '{}') if task else {}
    frozen_llm=previous.inputs.get('llm') or {};template=(previous.inputs.get('basis') or {}).get('template') or {}
    if (not task or task.status!="failed" or task_meta.get("input_hash")!=previous.input_hash
            or task_meta.get("split_run_id")!=previous.id or not log or log.status!="success"
            or task_meta.get('execution_purpose')!='production' or log.provider!=frozen_llm.get('provider')
            or log.model!=frozen_llm.get('model') or log.task_type!='split_chapter'
            or log.prompt_template_name!=template.get('name')
            or log.response!=previous.call.get("response") or log.system_prompt!=previous.inputs.get("system_prompt")
            or log.user_prompt!=previous.inputs.get("user_prompt") or log.novel_id!=novel_id or log.chapter_id!=chapter_id):
        return None
    if previous.inputs.get('basis')!=basis:
        return None
    try:
        data=parse_output(log.response,source_contract_version,source_window_version(current_profile))
        validation_basis={**basis,"locked_shots":previous.inputs["locked_shots"]} if previous.inputs.get("locked_shots") is not None else basis
        validate_plan(data,validation_basis)
    except ValueError as exc:
        if 'data' not in locals():return None
        if _duplicates_repaired_root(db,previous,data,basis):return None
        return _governance_context(previous,log,previous,data,basis,list(range(1,len(data['shots'])+1)),set(),0)
    return None


def expire_split_task(db, task):
    run = db.query(Run).filter_by(task_id=task.id, status="RUNNING").first()
    if not run and task.status in {"pending", "running"} and not db.query(Run.id).filter_by(task_id=task.id).first():
        task.status, task.error_message, task.current_step, task.completed_at = "failed", "SHOT_SPLIT_LEDGER_MISSING", "分镜来源记录缺失", datetime.utcnow()
        db.commit()
        return True
    if run and (task.status not in {"pending", "running"} or run.expires_at < datetime.utcnow()):
        message=task.error_message or 'SPLIT_EXPIRED'
        if ((run.inputs.get('auto_repair') or {}).get('governance') or {}).get('version')==AUTO_REPAIR_GOVERNANCE_VERSION:
            run.status,run.issues,run.completed_at='NEEDS_REVIEW',[_interrupted_repair_issue(run,message)],datetime.utcnow()
            mark_repair_interruption(task,run,message)
        else:
            run.status,run.issues,run.completed_at='FAILED',[{"code":"SPLIT_TASK_TERMINATED","message":message}],datetime.utcnow()
        if task.status in {"pending", "running"}:
            task.status, task.error_message, task.completed_at = "failed", "SPLIT_EXPIRED", datetime.utcnow()
        db.commit()
        return True
    return False


def checked_run(db, run, basis=None):
    from app.services.narration_coverage import VERSION as treatment_version
    if not run or run.inputs.get('treatment_contract_version')!=treatment_version:
        raise HTTPException(409,'CONTRACT_UNAVAILABLE: explicit Shot Director contract rebuild required')
    return _checked_run_proof(db,run,basis)


def _checked_run_proof(db, run, basis=None, *, historical_structure=False, structure_reference=False):
    """Historical mode is only a structural lock reader, never runtime admission."""
    source_contract_version = source_contract_version_for_run(run)
    if (not run or run.status != "SUCCEEDED" or digest(run.inputs) != run.input_hash
            or digest(run.result) != run.result_hash or (not structure_reference and (not latest_run(db, run.chapter_id) or latest_run(db,run.chapter_id).id != run.id))):
        raise HTTPException(409, "SHOT_SPLIT_NOT_CURRENT")
    basis = basis or collect_scope(db, run.novel_id, run.chapter_id, source_contract_version,run_profile=run.version)
    if basis != run.inputs["basis"]:
        raise HTTPException(409, "SHOT_SPLIT_INPUTS_STALE")
    task, log = db.get(Task, run.task_id), db.get(LLMLog, run.call.get("llm_log_id")) if run.call.get("llm_log_id") else None
    controlled=run.inputs.get('controlled_degradation')
    auto_repair=run.inputs.get("auto_repair")
    human=run.inputs.get('human_authored_correction')
    expected_task_type="shot_contract_auto_repair" if auto_repair else "split_chapter"
    frozen_llm=run.inputs.get('llm') or {}
    expected_template=((auto_repair or {}).get('template') or {}) if auto_repair else (run.inputs.get('basis') or {}).get('template') or {}
    if controlled:
        if (not task or task.status!='completed' or task.type!=TASK_TYPE or task.novel_id!=run.novel_id
                or task.chapter_id!=run.chapter_id or log is not None
                or run.call.get('kind')!='DETERMINISTIC_CONTROLLED_DEGRADATION' or not run.call.get('success')):
            raise HTTPException(409,'CONTROLLED_DEGRADATION_PROVENANCE_INVALID')
    elif human:
        if (not task or task.status!='completed' or task.type!=TASK_TYPE or task.novel_id!=run.novel_id
                or task.chapter_id!=run.chapter_id or log is not None
                or run.call.get('kind')!='HUMAN_AUTHORED_PLAN_CORRECTION' or not run.call.get('success')):
            raise HTTPException(409,'HUMAN_AUTHORED_CORRECTION_PROVENANCE_INVALID')
    elif (not task or task.status != "completed" or task.type != TASK_TYPE or task.novel_id != run.novel_id or task.chapter_id != run.chapter_id
            or not log or log.status != "success" or log.novel_id != run.novel_id or log.chapter_id != run.chapter_id
            or log.provider!=frozen_llm.get('provider') or log.model!=frozen_llm.get('model')
            or log.prompt_template_name!=expected_template.get('name')
            or log.task_type != expected_task_type or log.response != run.call.get("response")
            or log.system_prompt != run.inputs["system_prompt"] or log.user_prompt != run.inputs["user_prompt"]):
        raise HTTPException(409, "SHOT_SPLIT_PROVENANCE_INVALID")
    meta = json.loads(task.metadata_json or "{}")
    if controlled:
        if (meta.get('input_hash')!=run.input_hash or meta.get('result_hash')!=run.result_hash
                or meta.get('split_run_id')!=run.id or meta.get('execution_purpose')!='production'
                or meta.get('delivery_mode')!='CONTROLLED_DEGRADATION'
                or meta.get('repair_run_id')!=controlled.get('repair_run_id')
                or meta.get('outcome')!='SUCCEEDED_WITH_DEGRADATION'):
            raise HTTPException(409,'CONTROLLED_DEGRADATION_TASK_PROOF_CHANGED')
    elif human:
        if (meta.get('input_hash')!=run.input_hash or meta.get('result_hash')!=run.result_hash
                or meta.get('split_run_id')!=run.id or meta.get('execution_purpose')!='production'
                or meta.get('delivery_mode')!='HUMAN_AUTHORED_PLAN_CORRECTION'):
            raise HTTPException(409,'HUMAN_AUTHORED_CORRECTION_TASK_PROOF_CHANGED')
    elif (meta.get("input_hash") != run.input_hash or meta.get("result_hash") != run.result_hash
            or meta.get("split_run_id") != run.id or meta.get("execution_purpose") != "production"):
        raise HTTPException(409, "SHOT_SPLIT_TASK_PROOF_CHANGED")
    if set(run.result.get("sources", {})) != {s.id for s in db.query(Shot).filter_by(chapter_id=run.chapter_id)}:
        raise HTTPException(409, "SHOT_SPLIT_MEMBERSHIP_CHANGED")
    try:
        controlled_validation=None
        if controlled:
            from app.services.controlled_degradation_service import replay as replay_controlled_degradation
            raw_output,controlled_validation,expected_degradation=replay_controlled_degradation(db,run)
            if run.result.get('controlled_degradation')!=expected_degradation:
                raise ValueError('CONTROLLED_DEGRADATION_RESULT_CHANGED')
        elif human:
            raw_output,_human_log=_root_receipt(db,run,basis)
        elif auto_repair and auto_repair.get('governance'):
            replayed=_replay_governance_head(db,run,basis)
            raw_output=replayed['candidate']
        elif auto_repair:
            template=auto_repair.get("template") or {}
            if (template.get("hash")!=digest(template.get("text") or "") or log.prompt_template_name!=template.get("name")
                    or historical_structure):
                raise ValueError("SHOT_CONTRACT_REPAIR_TEMPLATE_PROOF_INVALID")
            parent=db.get(Run,auto_repair.get("parent_run_id"));parent_log=db.get(LLMLog,auto_repair.get("parent_llm_log_id"))
            parent_task=db.get(Task,parent.task_id) if parent else None
            parent_meta=json.loads(parent_task.metadata_json or '{}') if parent_task else {}
            if (not parent or parent.novel_id!=run.novel_id or parent.chapter_id!=run.chapter_id or parent.status!="NEEDS_REVIEW"
                    or digest(parent.inputs)!=parent.input_hash or not parent_task or parent_task.status!="failed"
                    or parent_meta.get("input_hash")!=parent.input_hash or parent_meta.get("split_run_id")!=parent.id
                    or parent.call.get("response")!=auto_repair.get("original_response")
                    or not parent_log or parent_log.status!="success" or parent_log.response!=auto_repair.get("original_response")
                    or parent.call.get("llm_log_id")!=parent_log.id or parent_log.system_prompt!=parent.inputs.get("system_prompt")
                    or parent_log.user_prompt!=parent.inputs.get("user_prompt")):
                raise ValueError("SHOT_CONTRACT_REPAIR_PARENT_PROOF_INVALID")
            original=parse_output(auto_repair["original_response"],source_contract_version,source_window_version(run.version))
            repair_type=auto_repair["repair_plan"]["repair_type"]
            original_findings=auto_repair_findings(original,basis,repair_type+':')
            scene_aware=any(target.get("scene_policy") for target in auto_repair["repair_plan"].get("targets",[]))
            policy_versions={target['scene_policy'].get('version') for target in auto_repair['repair_plan'].get('targets',[])
                if target.get('scene_policy')}
            options={'scene_aware':scene_aware}
            if scene_aware and len(policy_versions)==1:options['scene_policy_version']=next(iter(policy_versions))
            if (original_findings!=auto_repair.get("violations_before")
                    or build_auto_repair_plan(original_findings,original,basis,**options)!=auto_repair.get("repair_plan")):
                raise ValueError("SHOT_CONTRACT_REPAIR_PLAN_PROOF_INVALID")
            scene_decisions=[] if scene_aware else None
            raw_output=apply_auto_repair(original,auto_repair["repair_plan"],log.response,basis,scene_decisions)
            findings=auto_repair_findings(raw_output,basis,repair_type+':')
            replay_delta=auto_repair_delta(original,raw_output,auto_repair["violations_before"],findings,
                repair_type=repair_type,outcome="REPAIRED",scene_decisions=scene_decisions)
            if (run.result.get("auto_repair")!=replay_delta or run.call.get("composed_response_hash")!=digest(raw_output)
                    or not log.execution_metadata or log.execution_metadata.get("outcome")!="REPAIRED"
                    or log.execution_metadata.get("beforeHash")!=replay_delta["beforeHash"]
                    or log.execution_metadata.get("afterHash")!=replay_delta["afterHash"]
                    or log.execution_metadata.get("repairType")!=replay_delta["repairType"]
                    or log.execution_metadata.get("attempt")!=1 or log.execution_metadata.get("budget")!=1
                    or log.execution_metadata.get("parentRunId")!=parent.id
                    or log.execution_metadata.get("originalResponseHash")!=digest(auto_repair["original_response"])
                    or log.execution_metadata.get("repairResponseHash")!=digest(log.response)
                    or log.execution_metadata.get("violationsBefore")!=replay_delta["violationsBefore"]
                    or log.execution_metadata.get("violationsAfter")!=replay_delta["violationsAfter"]
                    or log.execution_metadata.get("sceneDecisions")!=replay_delta.get("sceneDecisions")
                    or log.execution_metadata.get("template")!={key:template[key] for key in ("id","name","version","hash")}
                    or meta.get("auto_repair")!=replay_delta):
                raise ValueError("SHOT_CONTRACT_REPAIR_DELTA_PROOF_INVALID")
        else:
            raw_output = read_historical_output(log.response) if historical_structure else parse_output(
                log.response,source_contract_version,source_window_version(run.version))
        validation_basis={**basis,'locked_shots':run.inputs['locked_shots']} if run.inputs.get('locked_shots') is not None else basis
        prepared = validate_plan(raw_output, validation_basis, historical_structure=historical_structure,
            controlled_degradation=controlled_validation)
        if run.result["summary"] != {key:raw_output[key] for key in ("chapter","characters","scenes","props")}:
            raise ValueError("OUTPUT_SUMMARY_CHANGED")
        sources = sorted(run.result["sources"].values(), key=lambda value:value["snapshot"]["index"])
        if len(prepared) != len(sources):
            raise ValueError("OUTPUT_COUNT_CHANGED")
        for item, source in zip(prepared,sources):
            planned, stored = item["shot"], source["snapshot"]
            if (source["source_start"] != item["start"] or source["source_end"] != item["end"] or source["ranges"] != item["ranges"]
                    or source["evidence"] != item['evidence'] or source["bindings"] != item["bindings"]
                    or ('source_contract' in source) != (item['source_contract'] is not None)
                    or source.get('source_contract') != item['source_contract']
                    or stored["index"] != planned["id"] or stored["description"] != planned["description"]
                    or stored["video_description"] != planned["video_description"] or stored["scene"] != planned["scene"]
                    or stored["continuity_mode"] != planned["continuity_mode"] or stored["estimated_duration"] != planned["duration"]
                    or source["audio_snapshot"] != [AudioDriveRepository(db)._normalize_event_payload(e,e["order"]) for e in item["audio"]]
                    or any(json.loads(stored[key]) != planned[key] for key in ("characters","props","dialogues"))):
                raise ValueError("PUBLISHED_SOURCE_DIFFERS_FROM_VALIDATED_LLM_OUTPUT")
            if not historical_structure:
                from app.services.shot_treatment_contract import make_contract
                contract=source.get('treatment_contract') or {}
                event_ids=[b['event_id'] for b in contract.get('event_bindings',[])]
                if contract!=make_contract(planned,item['treatment_coverage'],event_ids):
                    raise ValueError('TREATMENT_PUBLICATION_DIFFERS_FROM_DIRECTOR')
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, f"SHOT_SPLIT_OUTPUT_PROOF_INVALID: {exc}") from exc
    return basis


def checked_source(db, shot, *, basis=None, run_checked=False):
    row = db.get(ShotSource, shot.id)
    if not row:
        raise HTTPException(409, "LEGACY_SHOT_NEEDS_REBUILD")
    run = db.get(Run, row.run_id)
    if run_checked and (not latest_run(db,shot.chapter_id) or latest_run(db,shot.chapter_id).id != row.run_id):
        raise HTTPException(409, "SHOT_SPLIT_NOT_CURRENT")
    if not run_checked:
        checked_run(db, run, basis)
    payload = source_payload(row)
    if digest(payload) != row.seal or run.result.get("sources", {}).get(shot.id) != payload:
        raise HTTPException(409, "SHOT_SOURCE_CHANGED_NEEDS_REBUILD")
    content = run.inputs["basis"]["source"]["content"]
    if row.source_hash != run.inputs["basis"]["source"]["hash"] or any(content[r["start"]:r["end"]] != r["text"] for r in row.ranges):
        raise HTTPException(409, "SHOT_SOURCE_RANGE_INVALID")
    from app.services.shot_revision_service import effective_source
    return effective_source(db, shot, row)


def source_response(row):
    contract=deepcopy(getattr(row,'source_contract',None))
    return {"shotId": row.shot_id, "splitRunId": row.run_id, "sourceStart": row.source_start, "sourceEnd": row.source_end,
        "sourceHash": row.source_hash, "sourceEvidence": row.evidence, "sourceRanges": row.ranges,
        "sourceContract":contract, "sourceContractVersion":contract.get('version') if contract else None,
        "sourceCitations":contract.get('citation_evidence') if contract else None,
        "sourceCitationRanges":contract.get('citation_ranges') if contract else None,
        "offsetUnit": "UNICODE_CODE_POINT", "assetBindings": row.bindings, "seal": row.seal,
        "revision": getattr(row, 'revision', 0), "revisionId": getattr(row, 'revision_id', None),
        "origin": getattr(row, 'origin', 'LLM_SPLIT'), "baseSeal": getattr(row, 'base_seal', row.seal)}


def supersede_rebuild_barrier(db,run,reason):
    from app.models.chapter_governance import ChapterLifecycle
    lifecycle=db.get(ChapterLifecycle,run.chapter_id)
    if not lifecycle or not lifecycle.rebuild_id:return None
    old=lifecycle.rebuild_id
    lifecycle.origin_evidence={**(lifecycle.origin_evidence or {}),'rebuildSupersession':{
        'rebuildId':old,'splitRunId':run.id,'splitInputHash':run.input_hash,'reason':reason,
        'at':datetime.utcnow().isoformat()}}
    lifecycle.rebuild_id=None
    return old


def publish_human_authored_run(db,run):
    if not run or run.status!='NEEDS_REVIEW' or latest_run(db,run.chapter_id).id!=run.id:
        raise HTTPException(409,'HUMAN_AUTHORED_CORRECTION_NOT_CURRENT')
    basis=collect_scope(db,run.novel_id,run.chapter_id,run.inputs.get('source_contract_version'),run_profile=run.version)
    try:data,_log=_root_receipt(db,run,basis);prepared=validate_plan(data,basis)
    except ValueError as exc:raise HTTPException(409,'HUMAN_AUTHORED_CORRECTION_NOT_VALID: '+str(exc)) from exc
    no_active_shot_tasks(db,run.chapter_id);task=db.get(Task,run.task_id)
    if not task or task.status!='failed':raise HTTPException(409,'HUMAN_AUTHORED_CORRECTION_TASK_CHANGED')
    from app.services.shot_treatment_contract import make_contract
    try:
        old_ids=[row.id for row in db.query(Shot).filter_by(chapter_id=run.chapter_id)]
        AudioDriveRepository(db).cleanup_shots_audio_drive(old_ids,commit=False)
        if old_ids:
            db.query(AppearanceShotUsage).filter(AppearanceShotUsage.shot_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(ShotSource).filter(ShotSource.shot_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(Shot).filter(Shot.id.in_(old_ids)).delete(synchronize_session=False)
        sources={};created=[]
        for item in prepared:
            planned=item['shot'];shot=Shot(id=str(uuid4()),chapter_id=run.chapter_id,index=planned['id'],
                description=planned['description'],video_description=planned['video_description'],
                characters=json.dumps(planned['characters'],ensure_ascii=False),scene=planned['scene'],
                props=json.dumps(planned['props'],ensure_ascii=False),dialogues=json.dumps(planned['dialogues'],ensure_ascii=False),
                duration=planned['duration'],estimated_duration=planned['duration'],continuity_mode=planned['continuity_mode'])
            db.add(shot);db.flush();events=[]
            for event in item['audio']:
                row=ShotAudioEvent(shot_id=shot.id,**AudioDriveRepository(db)._normalize_event_payload(event,event['order']))
                db.add(row);events.append(row)
            db.flush();source=ShotSource(shot_id=shot.id,run_id=run.id,source_start=item['start'],source_end=item['end'],
                source_hash=basis['source']['hash'],evidence=item['evidence'],ranges=item['ranges'],bindings=item['bindings'],
                snapshot=snapshot(shot),audio_snapshot=audio_snapshot(db,shot.id),source_contract=item['source_contract'],
                treatment_contract=make_contract(planned,item['treatment_coverage'],[event.id for event in events]))
            source.seal=digest(source_payload(source));db.add(source);sources[shot.id]=source_payload(source);created.append(shot)
        if any(event['type']=='NARRATION' for item in prepared for event in item['audio']):
            from app.services.narrator_profile_service import ensure_narrator
            ensure_narrator(db,run.novel_id)
        summary={key:data[key] for key in ('chapter','characters','scenes','props')};chapter=db.get(Chapter,run.chapter_id)
        chapter.parsed_data=json.dumps(summary,ensure_ascii=False);chapter.status,chapter.progress='pending',0
        for key in ('shot_images','shot_videos','transition_videos','merged_image','final_video','final_video_task_id'):
            if hasattr(chapter,key):setattr(chapter,key,None)
        run.result={'sources':sources,'summary':summary,'human_authored_correction':deepcopy(run.inputs['human_authored_correction'])}
        run.result_hash,run.status,run.completed_at=digest(run.result),'SUCCEEDED',datetime.utcnow()
        task.status,task.progress,task.current_step,task.completed_at='completed',100,'Human-authored Shot Plan validated and published',datetime.utcnow()
        task.error_message=None;task.metadata_json=json.dumps({'execution_purpose':'production',
            'delivery_mode':'HUMAN_AUTHORED_PLAN_CORRECTION','split_run_id':run.id,'input_hash':run.input_hash,
            'result_hash':run.result_hash,'decision_hash':run.call.get('decision_hash')},ensure_ascii=False)
        supersede_rebuild_barrier(db,run,'AUTHORIZED_FRESH_ROOT_HUMAN_CORRECTION_SUCCEEDED')
        db.commit()
    except Exception:db.rollback();raise
    checked_run(db,run)
    return {'splitRunId':run.id,'taskId':task.id,'status':run.status,'humanAuthoredCorrection':run.inputs['human_authored_correction'],
        'shots':[{**ShotRepository(db).to_response(shot),'source':source_response(db.get(ShotSource,shot.id))} for shot in created]}


def split_state(db, novel_id, chapter_id):
    if not db.query(Chapter.id).filter_by(id=chapter_id, novel_id=novel_id).first():
        raise HTTPException(404, "章回不存在")
    run, basis, gate_error = latest_run(db, chapter_id), None, None
    try:
        basis = collect_scope(db, novel_id, chapter_id, OWNERSHIP_VERSION)
    except (HTTPException, ValueError) as exc:
        gate_error = exc.detail if isinstance(exc, HTTPException) else str(exc)
    ready, error = False, None
    if run:
        try:
            checked_run(db, run)
            ready = True
        except (HTTPException, ValueError) as exc:
            error = exc.detail if isinstance(exc, HTTPException) else str(exc)
    try:
        no_active_shot_tasks(db, chapter_id)
        active_task = db.get(Task,run.task_id) if run else None
        if run and run.status == "RUNNING" and run.expires_at > datetime.utcnow() and active_task and active_task.status == "running":
            raise HTTPException(409,"CHAPTER_SPLIT_ALREADY_RUNNING")
    except HTTPException as exc:
        gate_error = gate_error or exc.detail
    shots = []
    for shot in db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index, Shot.id):
        record = db.get(ShotSource, shot.id)
        state, problem = "NEEDS_REBUILD" if record else "LEGACY", error
        if ready:
            try:
                record = checked_source(db, shot, run_checked=True)
                state, problem = "READY", None
            except HTTPException as exc:
                problem = exc.detail
        shots.append({"shotId": shot.id, "index": shot.index, "status": state, "issue": problem,
            "completionDisposition":getattr(shot,'completion_disposition','NORMAL'),
            "source": source_response(record) if record else None})
    return {"canSplit": basis is not None and gate_error is None, "splitBlocker": gate_error, "scope": basis["scope"] if basis else None,
        "latestRunId": run.id if run else None, "runStatus": run.status if run else "NOT_SPLIT", "issues": run.issues if run else [],
        "runVersion":run.version if run else None,
        "treatmentContractVersion":run.inputs.get('treatment_contract_version') if run else None,
        "sourceContractVersion":run.inputs.get('source_contract_version') if run else None,
        "sourceWindowVersion":run.inputs.get('source_window_version') if run else None,
        "phase5Ready": bool(ready and shots and all(s["status"] == "READY" for s in shots)), "shots": shots}


class ChapterShotSplitService:
    def __init__(self, db, llm=None):
        self.db, self.llm = db, llm

    def guard(self, run_id, token):
        db = self.db
        # Acquire a write fence before checking other records and publishing.
        count = db.query(Run).filter(Run.id == run_id, Run.status == "RUNNING", Run.expires_at >= datetime.utcnow()).update({
            "expires_at": datetime.utcnow()+timedelta(minutes=15)}, synchronize_session=False)
        if count != 1:
            raise RuntimeError("SHOT_SPLIT_EXECUTION_FENCED")
        db.expire_all()
        run = db.get(Run, run_id); task = db.get(Task, run.task_id)
        if not task or task.status != "running" or task.claim_token != token or digest(run.inputs) != run.input_hash:
            raise RuntimeError("SHOT_SPLIT_TASK_CHANGED")
        from app.services.rebuild_context import stage_parent
        stage_parent(db, run.chapter_id)
        meta = json.loads(task.metadata_json or "{}")
        if (task.type != TASK_TYPE or task.novel_id != run.novel_id or task.chapter_id != run.chapter_id
                or meta.get("input_hash") != run.input_hash or meta.get("split_run_id") != run.id or meta.get("execution_purpose") != "production"):
            raise RuntimeError("SHOT_SPLIT_TASK_BINDING_CHANGED")
        source_contract_version=source_contract_version_for_run(run)
        if (collect_scope(db, run.novel_id, run.chapter_id, source_contract_version,run_profile=run.version) != run.inputs["basis"]
                or previous_shots(db, run.chapter_id) != run.inputs["previous_shots"]):
            raise RuntimeError("SHOT_SPLIT_INPUTS_CHANGED")
        from app.services.shot_treatment_contract import load_director_increment
        if run.inputs.get('treatment_prompt')!=load_director_increment():
            raise RuntimeError('SOURCE_TREATMENT_PROMPT_CHANGED')
        no_active_shot_tasks(db, run.chapter_id)
        task.heartbeat_at = datetime.utcnow()
        return run, task

    async def split(self, novel_id, chapter_id, *, repair_previous=True, preserve_structure=False, source_contract_version=None):
        previous=latest_run(self.db,chapter_id)
        if previous and previous.status=='RUNNING':
            task=self.db.get(Task,previous.task_id)
            if task and (task.status not in {'pending','running'} or previous.expires_at<datetime.utcnow()):
                expire_split_task(self.db,task);previous=latest_run(self.db,chapter_id)
        try:current_profile=run_version(source_contract_version)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        if (repair_previous and not preserve_structure and previous and previous.status=="NEEDS_REVIEW"
                and previous.version==current_profile and previous.inputs.get("auto_repair")):
            governance=(previous.inputs.get('auto_repair') or {}).get('governance')
            if governance:
                basis=collect_scope(self.db,novel_id,chapter_id,source_contract_version,run_profile=current_profile)
                try:state=_replay_governance_head(self.db,previous,basis)
                except ValueError as exc:raise HTTPException(409,f'AUTO_REPAIR_GOVERNANCE_PROOF_INVALID: {exc}') from exc
                context=_governance_context(state['root'],state['root_log'],state['predecessor'],state['candidate'],
                    basis,state['origins'],state['attempted'],state['rounds'])
                if context:
                    return await self._run_auto_repair_chain(novel_id,chapter_id,source_contract_version,context,None)
            repair=(previous.issues or [{}])[0].get("repair") or {}
            return {"success":False,"message":"SHOT_CONTRACT_REPAIR_BUDGET_EXHAUSTED","data":{
                "splitRunId":previous.id,"taskId":previous.task_id,"status":previous.status,
                "autoRepair":{**repair,"outcome":repair.get("outcome") or "STILL_INVALID","budgetExhausted":True}}}
        if previous and previous.version!=current_profile:repair_previous=False
        existing=(prior_auto_repair_context(self.db,novel_id,chapter_id,source_contract_version)
            if repair_previous and not preserve_structure else None)
        if existing:
            return await self._run_auto_repair_chain(novel_id,chapter_id,source_contract_version,existing,None)
        first=await self._split_once(novel_id,chapter_id,repair_previous=repair_previous,
            preserve_structure=preserve_structure,source_contract_version=source_contract_version)
        context=first.pop("_auto_repair_context",None)
        if not context:return first
        return await self._run_auto_repair_chain(novel_id,chapter_id,source_contract_version,context,first)

    async def _run_auto_repair_chain(self,novel_id,chapter_id,source_contract_version,context,fallback):
        current=fallback
        while context:
            try:
                current=await self._split_once(novel_id,chapter_id,repair_previous=False,
                    preserve_structure=False,source_contract_version=source_contract_version,_auto_repair=context)
            except HTTPException as exc:
                result=current or {"success":False,"message":"SHOT_CONTRACT_REPAIR_UNAVAILABLE","data":{
                    "splitRunId":context["governance"]["predecessor_run_id"],"status":"NEEDS_REVIEW"}}
                result.setdefault('data',{})['autoRepair']={"outcome":"UNAVAILABLE","detail":exc.detail,
                    "attempt":0,"budget":1,"violationsBefore":len(context["violations_before"]),
                    'governance':context['governance']}
                return result
            context=current.pop('_auto_repair_context',None)
        return current

    async def _split_once(self, novel_id, chapter_id, *, repair_previous=True, preserve_structure=False,
                          source_contract_version=None, _auto_repair=None, _run_profile=None):
        db = self.db
        try:
            selected_run_version=run_version(source_contract_version,_run_profile)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        from app.services.rebuild_context import stage_parent
        parent_task_id = stage_parent(db, chapter_id)
        for active in db.query(Run).filter_by(chapter_id=chapter_id, status="RUNNING").all():
            task = db.get(Task, active.task_id)
            if task:
                expire_split_task(db, task)
            else:
                active.status, active.issues, active.completed_at = "FAILED", [{"code":"TASK_MISSING"}], datetime.utcnow()
                db.commit()
        basis = collect_scope(db,novel_id,chapter_id,source_contract_version,run_profile=selected_run_version)
        no_active_shot_tasks(db, chapter_id)
        previous, repair = latest_run(db,chapter_id), None
        if _auto_repair:
            governance=_auto_repair.get('governance')
            if governance:
                if (not previous or previous.id!=governance.get('predecessor_run_id')
                        or previous.status!='NEEDS_REVIEW'):
                    raise HTTPException(409,'SHOT_CONTRACT_REPAIR_PARENT_CHANGED')
            elif (not previous or previous.id!=_auto_repair.get("parent_run_id")
                    or previous.status!="NEEDS_REVIEW" or previous.call.get("response")!=_auto_repair.get("original_response")):
                raise HTTPException(409,"SHOT_CONTRACT_REPAIR_PARENT_CHANGED")
        locked_shots=None;structure_source_id=None;structure_conversion=None
        if preserve_structure:
            reference=previous
            if previous and previous.status!='SUCCEEDED' and previous.inputs.get('structure_lock_source_run_id'):
                parent_task=db.get(Task,previous.task_id)
                meta=json.loads(parent_task.metadata_json or '{}') if parent_task else {}
                if digest(previous.inputs)!=previous.input_hash or meta.get('input_hash')!=previous.input_hash:
                    raise HTTPException(409,'STRUCTURE_LOCK_PROOF_CHANGED')
                reference=db.get(Run,previous.inputs['structure_lock_source_run_id'])
            if not reference or reference.status!='SUCCEEDED' or reference.chapter_id!=chapter_id:
                raise HTTPException(409,'STRUCTURE_LOCK_REQUIRES_SUCCESSFUL_SOURCE')
            legacy=reference.inputs.get('treatment_contract_version') is None
            reference_source_contract_version=source_contract_version_for_run(reference)
            _checked_run_proof(db,reference,historical_structure=legacy,structure_reference=True)
            if (reference.inputs.get('auto_repair') or {}).get('governance'):
                raw=_replay_governance_head(db,reference,reference.inputs['basis'])['candidate']
            else:
                raw=read_historical_output(reference.call['response']) if legacy else parse_output(
                    reference.call['response'],reference_source_contract_version,source_window_version(reference.version))
            locked_shots=deepcopy(raw['shots'])
            if reference_source_contract_version != source_contract_version:
                if reference_source_contract_version is not None and source_contract_version is None:
                    raise HTTPException(409,'STRUCTURE_LOCK_SOURCE_CONTRACT_DOWNGRADE_FORBIDDEN')
                if reference_source_contract_version is not None or source_contract_version != OWNERSHIP_VERSION:
                    raise HTTPException(409,'STRUCTURE_LOCK_SOURCE_CONTRACT_UNSUPPORTED')
                converted=[]
                content=reference.inputs['basis']['source']['content']
                for old,item in zip(locked_shots,validate_plan(raw,reference.inputs['basis'],historical_structure=legacy)):
                    current=deepcopy(old)
                    citations=current.pop('source_evidence')
                    current['source_citations']=citations
                    current['source_ownership']={'text':content[item['start']:item['end']]}
                    converted.append(current)
                locked_shots=converted
                structure_conversion={'from':None,'to':OWNERSHIP_VERSION,'shots':deepcopy(converted),
                    'source_run_id':reference.id,'source_input_hash':reference.input_hash,'source_result_hash':reference.result_hash}
            if source_window_version(selected_run_version):
                if reference.version!=selected_run_version:
                    structure_conversion={**(structure_conversion or {}),
                        'from_run_version':reference.version,'to_run_version':selected_run_version,
                        'source_window_version':source_window_version(selected_run_version),
                        'source_run_id':reference.id,'source_input_hash':reference.input_hash,
                        'source_result_hash':reference.result_hash,'shots':deepcopy(locked_shots)}
            structure_source_id=reference.id
            for stored in reference.result['sources'].values():
                shot=db.get(Shot,stored['shot_id'])
                if not shot or snapshot(shot)!=stored['snapshot']:
                    raise HTTPException(409,'STRUCTURE_LOCK_CHANGED: use an explicit authored revision')
        if (not _auto_repair and repair_previous and previous and previous.status == "NEEDS_REVIEW"
                and previous.version==selected_run_version
                and previous.inputs.get('source_contract_version') == source_contract_version
                and previous.inputs.get("basis",{}).get("source") == basis["source"]
                and previous.inputs.get("basis",{}).get("scope") == basis["scope"] and previous.call.get("response")):
            log = db.get(LLMLog,previous.call.get("llm_log_id")) if previous.call.get("llm_log_id") else None
            if log and log.status == "success" and log.response == previous.call["response"]:
                try:
                    validate_plan(parse_output(log.response,source_contract_version,source_window_version(selected_run_version)),basis)
                except ValueError as exc:
                    repair = {"run_id":previous.id,"llm_log_id":log.id,"response":log.response,"validation_error":str(exc)}
        validation_basis={**basis,'locked_shots':locked_shots} if locked_shots is not None else basis
        auto_template=None
        if _auto_repair:
            auto_template=resolve_auto_repair_template(db,novel_id)
            system,user=render_auto_repair_prompts(auto_template,_auto_repair["original_plan"],_auto_repair["repair_plan"])
        else:
            system, user = request_prompts(validation_basis, repair)
        llm = self.llm or LLMService()
        from app.services.narration_coverage import VERSION as treatment_version
        from app.services.shot_treatment_contract import load_director_increment
        inputs = {"basis": basis, "system_prompt": system, "user_prompt": user, "previous_shots": previous_shots(db, chapter_id),
            "repair": repair, "repair_previous": repair_previous,
            "treatment_contract_version":treatment_version, "treatment_prompt":load_director_increment(), "locked_shots":locked_shots,
            "structure_lock_source_run_id":structure_source_id, "structure_lock_conversion":structure_conversion,
            "previous_chapter_resources": {key:getattr(db.get(Chapter,chapter_id),key) for key in ("parsed_data","shot_images","shot_videos","transition_videos","final_video","status","progress")},
            "llm": {"provider": llm.provider, "model": llm.model, "max_tokens": basis["policy"]["definition"]["max_tokens"], "temperature": 0.2}}
        if _auto_repair:
            inputs["auto_repair"]={"version":"shot-contract-auto-repair-v1","attempt":1,"budget":1,
                "parent_run_id":_auto_repair["parent_run_id"],"parent_llm_log_id":_auto_repair["parent_llm_log_id"],
                "original_response":_auto_repair["original_response"],"violations_before":_auto_repair["violations_before"],
                "repair_plan":_auto_repair["repair_plan"],"template":auto_template}
            if _auto_repair.get('governance'):
                inputs['auto_repair']['governance']=deepcopy(_auto_repair['governance'])
        if source_contract_version is not None:inputs['source_contract_version']=source_contract_version
        if source_window_version(selected_run_version):inputs['source_window_version']=source_window_version(selected_run_version)
        rid, tid, token = str(uuid4()), str(uuid4()), str(uuid4())
        task_meta={"execution_purpose":"production","split_run_id":rid,"input_hash":digest(inputs)}
        if _auto_repair:
            task_meta["auto_repair"]={"repair_type":_auto_repair["repair_plan"]["repair_type"],"attempt":1,"budget":1}
            if _auto_repair.get('governance'):
                task_meta['auto_repair'].update(root_run_id=_auto_repair['governance']['root_run_id'],
                    predecessor_run_id=_auto_repair['governance']['predecessor_run_id'],
                    round=_auto_repair['governance']['round'],max_rounds=MAX_REPAIR_ROUNDS_PER_ROOT_PLAN)
        task = Task(id=tid, novel_id=novel_id, chapter_id=chapter_id, type=TASK_TYPE, status="running", claim_token=token, parent_task_id=parent_task_id,
            name=(f"分镜契约自动修复：{basis['source']['title']}" if _auto_repair else f"ChapterScope分镜拆分：{basis['source']['title']}"),
            current_step="执行分镜契约定向修复" if _auto_repair else "生成章回分镜规划", started_at=datetime.utcnow(), heartbeat_at=datetime.utcnow(),
            metadata_json=json.dumps(task_meta, ensure_ascii=False))
        run = Run(id=rid, novel_id=novel_id, chapter_id=chapter_id, task_id=tid, version=selected_run_version, status="RUNNING",
            inputs=inputs, input_hash=digest(inputs), expires_at=datetime.utcnow()+timedelta(minutes=15))
        db.add_all([run, task])
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback(); raise HTTPException(409, "CHAPTER_SPLIT_ALREADY_RUNNING") from exc
        operation = None
        data=prepared=repair_delta=candidate_after=origins_after=attempted_after=None
        try:
            call_task_type="shot_contract_auto_repair" if _auto_repair else "split_chapter"
            call_template_name=auto_template["name"] if _auto_repair else basis["template"]["name"]
            operation = asyncio.create_task(llm.chat_completion(system_prompt=system, user_content=user, temperature=0.2,
                max_tokens=inputs["llm"]["max_tokens"], response_format="json_object", task_type=call_task_type,
                prompt_template_name=call_template_name, novel_id=novel_id, chapter_id=chapter_id))
            while True:
                done, _ = await asyncio.wait({operation}, timeout=15)
                if done:
                    response = operation.result(); break
                self.guard(rid, token); db.commit()
            db.expire_all()
            run = db.get(Run,rid)
            run.call = {**run.call, "llm_log_id": response.get("llm_log_id"), "response": response.get("content"), "success": response.get("success"), "error": response.get("error")}
            db.commit()
            run, task = self.guard(rid, token)
            db.commit()
            if not response.get("success"):
                raise RuntimeError(response.get("error") or "SHOT_SPLIT_LLM_FAILED")
            log = db.get(LLMLog, response.get("llm_log_id")) if response.get("llm_log_id") else None
            if (not log or log.status != "success" or log.response != response["content"] or log.system_prompt != system
                    or log.user_prompt != user or log.novel_id != novel_id or log.chapter_id != chapter_id
                    or log.provider!=inputs['llm']['provider'] or log.model!=inputs['llm']['model']
                    or log.task_type != call_task_type or log.prompt_template_name != call_template_name):
                raise RuntimeError("SHOT_SPLIT_LLM_LOG_UNVERIFIED")
            if _auto_repair and _auto_repair.get('governance'):
                governance=_auto_repair['governance'];base_metadata={
                    "operation":"SHOT_CONTRACT_AUTO_REPAIR","repairType":_auto_repair['repair_plan']['repair_type'],
                    "attempt":1,"budget":1,"violationsBefore":len(_auto_repair['violations_before']),
                    "violationsAfter":None,"outcome":"VALIDATING","beforeHash":digest(_auto_repair['original_plan']),
                    "afterHash":None,"parentRunId":_auto_repair['parent_run_id'],
                    "rootRunId":governance['root_run_id'],"predecessorRunId":governance['predecessor_run_id'],
                    "candidateBeforeHash":governance['candidate_before_hash'],
                    "originalResponseHash":digest(_auto_repair['original_response']),
                    "repairResponseHash":digest(response['content']),"template":{"id":auto_template['id'],
                        "name":auto_template['name'],"version":auto_template['version'],"hash":auto_template['hash']}}
                update_log_execution_metadata(db,log.id,base_metadata)
                candidate_after,origins_after,attempted_after,repair_delta,prepared=_evaluate_governance_repair(
                    _auto_repair,response['content'],validation_basis,source_contract_version,selected_run_version)
                data=candidate_after
                run=db.get(Run,rid);run.call={**run.call,'composed_response_hash':digest(data)}
                update_log_execution_metadata(db,log.id,{**base_metadata,**repair_delta},commit=False);db.commit();db.expire_all()
                if prepared is None:
                    raise AutoRepairReview(repair_delta['outcome'],
                        repair_delta.get('validatorError') or repair_delta['outcome'],repair_delta)
            elif _auto_repair:
                original=_auto_repair["original_plan"];before_findings=_auto_repair["violations_before"]
                repair_type=_auto_repair["repair_plan"]["repair_type"]
                scene_decisions=([] if repair_type==BOUNDARY_REPAIR_TYPE
                    and any(target.get("scene_policy") for target in _auto_repair["repair_plan"].get("targets",[])) else None)
                base_metadata={"operation":"SHOT_CONTRACT_AUTO_REPAIR","repairType":repair_type,
                    "attempt":1,"budget":1,"violationsBefore":len(before_findings),"violationsAfter":None,
                    "outcome":"VALIDATING","beforeHash":digest(original),"afterHash":None,
                    "parentRunId":_auto_repair["parent_run_id"],
                    "originalResponseHash":digest(_auto_repair["original_response"]),
                    "repairResponseHash":digest(response["content"]),
                    "template":{"id":auto_template["id"],"name":auto_template["name"],
                        "version":auto_template["version"],"hash":auto_template["hash"]}}
                update_log_execution_metadata(db,log.id,base_metadata)
                if response["content"]==_auto_repair["original_response"]:
                    repair_delta=auto_repair_delta(original,original,before_findings,before_findings,
                        repair_type=repair_type,outcome="REPAIR_NO_EFFECT",validator_error=_auto_repair["validation_error"],
                        scene_decisions=scene_decisions)
                    update_log_execution_metadata(db,log.id,{**base_metadata,**repair_delta})
                    raise AutoRepairReview("REPAIR_NO_EFFECT","SHOT_CONTRACT_REPAIR_NO_EFFECT",repair_delta)
                try:
                    data=apply_auto_repair(original,_auto_repair["repair_plan"],response["content"],validation_basis,scene_decisions)
                except ValueError as repair_exc:
                    repair_delta=auto_repair_delta(original,original,before_findings,before_findings,
                        repair_type=repair_type,outcome="STILL_INVALID",validator_error=str(repair_exc),
                        scene_decisions=scene_decisions)
                    update_log_execution_metadata(db,log.id,{**base_metadata,**repair_delta})
                    raise AutoRepairReview("STILL_INVALID",str(repair_exc),repair_delta) from repair_exc
                after_findings=auto_repair_findings(data,validation_basis,repair_type+':')
                try:
                    prepared=validate_plan(data,validation_basis)
                except ValueError as validation_exc:
                    error_code=str(validation_exc).split(':',1)[0].split(';',1)[0]
                    before_codes={item["code"] for item in before_findings}
                    outcome="REPAIR_NO_EFFECT" if digest(data)==digest(original) else (
                        "NEW_VIOLATIONS" if error_code not in before_codes else "STILL_INVALID")
                    repair_delta=auto_repair_delta(original,data,before_findings,after_findings,
                        repair_type=repair_type,outcome=outcome,validator_error=str(validation_exc),
                        scene_decisions=scene_decisions)
                    update_log_execution_metadata(db,log.id,{**base_metadata,**repair_delta})
                    raise AutoRepairReview(outcome,str(validation_exc),repair_delta) from validation_exc
                repair_delta=auto_repair_delta(original,data,before_findings,after_findings,
                    repair_type=repair_type,outcome="REPAIRED",scene_decisions=scene_decisions)
                update_log_execution_metadata(db,log.id,{**base_metadata,**repair_delta})
                run=db.get(Run,rid);run.call={**run.call,"composed_response_hash":digest(data)};db.commit()
            else:
                data = parse_output(response["content"],source_contract_version,source_window_version(selected_run_version))
                prepared = validate_plan(data, validation_basis)
            run, task = self.guard(rid, token)
            final_log = db.get(LLMLog,response["llm_log_id"])
            if (not final_log or final_log.status != "success" or final_log.response != response["content"]
                    or final_log.system_prompt != system or final_log.user_prompt != user
                    or final_log.novel_id != novel_id or final_log.chapter_id != chapter_id
                    or final_log.provider!=inputs['llm']['provider'] or final_log.model!=inputs['llm']['model']
                    or final_log.task_type!=call_task_type or final_log.prompt_template_name!=call_template_name
                    or run.call.get("response") != response["content"] or run.call.get("llm_log_id") != final_log.id):
                raise RuntimeError("SHOT_SPLIT_LLM_LOG_CHANGED_BEFORE_PUBLICATION")
            old_ids = [s["shot"]["id"] for s in inputs["previous_shots"]]
            AudioDriveRepository(db).cleanup_shots_audio_drive(old_ids, commit=False)
            db.query(AppearanceShotUsage).filter(AppearanceShotUsage.shot_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(ShotSource).filter(ShotSource.shot_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(Shot).filter(Shot.id.in_(old_ids)).delete(synchronize_session=False)
            created, sources = [], {}
            for index, item in enumerate(prepared, 1):
                planned = item["shot"]
                shot = Shot(id=str(uuid4()), chapter_id=chapter_id, index=index, description=planned["description"], video_description=planned["video_description"],
                    characters=json.dumps(planned["characters"],ensure_ascii=False), scene=planned["scene"], props=json.dumps(planned["props"],ensure_ascii=False),
                    dialogues=json.dumps(planned["dialogues"],ensure_ascii=False), duration=planned["duration"], estimated_duration=planned["duration"], continuity_mode=planned["continuity_mode"])
                db.add(shot); db.flush()
                created_events=[]
                for event in item["audio"]:
                    audio_event=ShotAudioEvent(shot_id=shot.id, **AudioDriveRepository(db)._normalize_event_payload(event, event["order"]))
                    db.add(audio_event);created_events.append(audio_event)
                db.flush()
                from app.services.shot_treatment_contract import make_contract
                source = ShotSource(shot_id=shot.id, run_id=rid, source_start=item["start"], source_end=item["end"], source_hash=basis["source"]["hash"],
                    evidence=item['evidence'], ranges=item["ranges"], bindings=item["bindings"], snapshot=snapshot(shot), audio_snapshot=audio_snapshot(db,shot.id),
                    treatment_contract=make_contract(planned,item['treatment_coverage'],[event.id for event in created_events]),
                    source_contract=item['source_contract'])
                payload = source_payload(source); source.seal = digest(payload)
                db.add(source); sources[shot.id] = payload; created.append(shot)
            if any(event['type'] == 'NARRATION' for item in prepared for event in item['audio']):
                from app.services.narrator_profile_service import ensure_narrator
                ensure_narrator(db, novel_id)
            chapter = db.get(Chapter, chapter_id)
            chapter.parsed_data = json.dumps({key: data[key] for key in ("chapter", "characters", "scenes", "props")}, ensure_ascii=False)
            chapter.status, chapter.progress = "pending", 0
            for key in ("shot_images", "shot_videos", "transition_videos", "merged_image", "final_video", "final_video_task_id"):
                if hasattr(chapter,key): setattr(chapter,key,None)
            run.result = {"sources": sources, "summary": {key:data[key] for key in ("chapter", "characters", "scenes", "props")}}
            if repair_delta:run.result["auto_repair"]=repair_delta
            run.result_hash, run.status, run.completed_at = digest(run.result), "SUCCEEDED", datetime.utcnow()
            final_meta={"execution_purpose":"production","split_run_id":rid,"input_hash":run.input_hash,"result_hash":run.result_hash}
            if repair_delta:final_meta["auto_repair"]=repair_delta
            task.metadata_json = json.dumps(final_meta,ensure_ascii=False)
            task.status, task.progress, task.current_step, task.completed_at = "completed", 100, (
                "分镜契约自动修复完成并发布" if repair_delta else "ChapterScope分镜与原文来源已发布"), datetime.utcnow()
            db.commit()
            return {"success": True, "data": {**run.result["summary"], "splitRunId": rid, "taskId": tid,
                "treatmentContractVersion":treatment_version,
                "sourceContractVersion":source_contract_version,
                "sourceWindowVersion":source_window_version(selected_run_version),
                **({"autoRepair":repair_delta} if repair_delta else {}),
                "shots": [{**ShotRepository(db).to_response(shot), "source": source_response(db.get(ShotSource,shot.id))} for shot in created]}}
        except BaseException as exc:
            db.rollback()
            row, current_task = db.get(Run,rid), db.get(Task,tid)
            auto_context=None;issue={"code":"NEEDS_REVIEW","message":str(exc) or "SPLIT_INTERRUPTED"}
            if isinstance(exc,AutoRepairReview):
                issue={"code":exc.outcome,"message":str(exc),"repair":exc.metadata}
            elif isinstance(exc,SplitReview) and data is not None:
                inventory=collect_repairable_inventory(data,validation_basis)
                findings=[item for family in REPAIR_FAMILY_ORDER for item in inventory[family]]
                if (row and _auto_repair is None and repair is None and not preserve_structure
                        and response.get("success") and response.get("llm_log_id")):
                    root_log=db.get(LLMLog,response['llm_log_id'])
                    if not _duplicates_repaired_root(db,row,data,validation_basis):
                        auto_context=_governance_context(row,root_log,row,data,validation_basis,
                            list(range(1,len(data['shots'])+1)),set(),0)
                issue={"code":"NEEDS_REVIEW","message":str(exc),"violationInventory":findings,
                    "repairClassification":"AUTO_REPAIRABLE" if auto_context else "HUMAN_REQUIRED",
                    'repairInventory':inventory}
            governed_interruption=bool(_auto_repair and _auto_repair.get('governance')
                and not isinstance(exc,AutoRepairReview))
            if governed_interruption and row:
                if row.status=='RUNNING':
                    issue=_interrupted_repair_issue(row,str(exc) or 'SPLIT_INTERRUPTED')
                    if current_task:mark_repair_interruption(current_task,row,issue['message'])
                else:issue=(row.issues or [issue])[0]
            if row and row.status == "RUNNING":
                row.status = "NEEDS_REVIEW" if governed_interruption or isinstance(exc, (SplitReview, ValueError)) else "FAILED"
                row.issues, row.completed_at = [issue], datetime.utcnow()
                if current_task and current_task.status == "running" and current_task.claim_token == token:
                    current_task.status, current_task.error_message, current_task.completed_at = "failed", str(exc) or "SPLIT_INTERRUPTED", datetime.utcnow()
                    current_task.current_step = (("分镜契约自动修复待复核" if _auto_repair else "分镜规划待复核")
                        if row.status == "NEEDS_REVIEW" else "分镜拆分失败")
                db.commit()
            if (isinstance(exc,AutoRepairReview) and _auto_repair and _auto_repair.get('governance')
                    and row and candidate_after is not None):
                governance=_auto_repair['governance'];root=db.get(Run,governance['root_run_id'])
                root_log=(db.get(LLMLog,root.call.get('llm_log_id'))
                    if root and root.call.get('llm_log_id') else None)
                auto_context=_governance_context(root,root_log,row,candidate_after,validation_basis,
                    origins_after,attempted_after,governance['round']) if root and (
                        root_log or root.inputs.get('human_authored_correction')) else None
            if isinstance(exc, asyncio.CancelledError): raise
            if not isinstance(exc, Exception): raise
            result={"success":False,"message":str(exc) or "SPLIT_INTERRUPTED","data":{
                "splitRunId":rid,"taskId":tid,"status":row.status if row else "FAILED"}}
            if isinstance(exc,AutoRepairReview):result["data"]["autoRepair"]=exc.metadata
            if auto_context:result["_auto_repair_context"]=auto_context
            return result
        finally:
            if operation and not operation.done():
                operation.cancel()
                try: await operation
                except BaseException: pass
