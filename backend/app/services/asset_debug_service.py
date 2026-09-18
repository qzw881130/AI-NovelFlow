"""Bounded, read-only provenance traversal over explicit persisted IDs.

Recorded facts, JSON/hash integrity, and today's runtime admission are separate.
This service never resolves assets, repairs records, reconciles tasks or polls providers.
"""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import HTTPException
from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.models.chapter_asset_parse import ChapterAssetParseRun, ChapterAssetCandidate
from app.models.asset_resolution import (AssetResolutionRun, AssetResolutionDecision, ChapterCharacterBinding,
    ChapterSceneBinding, ChapterPropBinding, ChapterCharacterAppearanceEvent, CharacterIdentity, CharacterAlias)
from app.models.appearance_timeline import AppearanceTimelineRun, CharacterAppearance, AppearanceEventReview
from app.models.appearance_generation import AppearanceGeneration, AppearanceImageRevision
from app.models.chapter_shot_split import ChapterShotSplitRun, ShotSource
from app.models.resolved_shot_assets import ResolvedShotAssets, ResolvedImageVersion, ShotAssetHead, ShotAppearanceDemand
from app.models.rsa_media import RsaImageAttempt, RsaMediaArtifact
from app.models.chapter_governance import ChapterLifecycle, ChapterRebuildRun
from app.models.audio_drive import ShotAudioEvent, AudioEventTTSAsset, ShotAudioTimeline, ShotAudioTimelineEvent
from app.services.chapter_asset_parse_service import digest
from app.services.evidence_reader import read_record, safe_value, public_evidence, sha_text, MAX_DISPLAY_CHARS, decode_evidence

MODELS = {
    'chapter': Chapter, 'lifecycle': ChapterLifecycle, 'rebuild': ChapterRebuildRun,
    'shot': Shot, 'source': ShotSource, 'split': ChapterShotSplitRun,
    'parse': ChapterAssetParseRun, 'candidate': ChapterAssetCandidate,
    'resolution': AssetResolutionRun, 'decision': AssetResolutionDecision,
    'character_binding': ChapterCharacterBinding, 'scene_binding': ChapterSceneBinding, 'prop_binding': ChapterPropBinding,
    'appearance_event': ChapterCharacterAppearanceEvent, 'appearance_review': AppearanceEventReview, 'timeline': AppearanceTimelineRun,
    'character': Character, 'identity': CharacterIdentity, 'alias': CharacterAlias, 'scene': Scene, 'prop': Prop,
    'appearance': CharacterAppearance, 'appearance_generation': AppearanceGeneration, 'appearance_image': AppearanceImageRevision,
    'asset_head': ShotAssetHead, 'rsa': ResolvedShotAssets, 'image_version': ResolvedImageVersion, 'demand': ShotAppearanceDemand,
    'media_attempt': RsaImageAttempt, 'media_artifact': RsaMediaArtifact, 'task': Task, 'llm_log': LLMLog,
    'audio_event': ShotAudioEvent, 'tts_asset': AudioEventTTSAsset, 'audio_timeline': ShotAudioTimeline, 'audio_timeline_event': ShotAudioTimelineEvent,
}
LABELS = {
    'chapter':'章回原文', 'lifecycle':'结构来源', 'rebuild':'显式重建', 'shot':'分镜', 'source':'分镜原文来源', 'split':'分镜拆分记录',
    'parse':'素材解析记录', 'candidate':'素材候选', 'resolution':'已有角色归一化与素材关联', 'decision':'身份决策',
    'character_binding':'本章角色关联', 'scene_binding':'本章场景关联', 'prop_binding':'本章道具关联',
    'appearance_event':'角色外观事件', 'appearance_review':'外观事件人工复核', 'timeline':'角色外观时间线',
    'character':'全局角色', 'identity':'角色实体类型', 'alias':'角色别名', 'scene':'全局场景', 'prop':'全局道具',
    'appearance':'角色外观', 'appearance_generation':'角色外观生成', 'appearance_image':'角色外观图片版本',
    'asset_head':'当前最终资产指针', 'rsa':'分镜最终资产', 'image_version':'冻结参考图版本', 'demand':'角色外观用量凭证',
    'media_attempt':'分镜/关键帧生成', 'media_artifact':'派生图像版本', 'task':'任务', 'llm_log':'LLM调用',
    'audio_event':'音频事件', 'tts_asset':'TTS音频版本', 'audio_timeline':'音频时间线', 'audio_timeline_event':'时间线音频片段',
}
ASSET_KINDS = {'characters':'character', 'scenes':'scene', 'props':'prop'}


def obj(value):
    return value if isinstance(value, dict) else {}


def items(value):
    return value if isinstance(value, list) else []


def log_references(kind, row):
    """Only registered saved ID fields; text/time similarity cannot establish a link."""
    refs=[]
    if kind=='parse':
        refs.extend((obj(c).get('llmLogId'),f'calls[{i}].llmLogId') for i,c in enumerate(items(row.get('calls'))))
    if kind=='decision':refs.append((obj(row.get('call')).get('llmLogId'),'call.llmLogId'))
    if kind=='split':refs.append((obj(row.get('call')).get('llm_log_id'),'call.llm_log_id'))
    if kind=='media_attempt':refs.append((obj(obj(row.get('execution')).get('prompt')).get('llm_log_id'),'execution.prompt.llm_log_id'))
    if kind=='appearance_generation':refs.append((obj(obj(row.get('execution')).get('llm')).get('log_id'),'execution.llm.log_id'))
    if kind=='shot':
        refs.extend((obj(c).get('llm_log_id'),f'video_director_plan.ai_calls[{i}].llm_log_id') for i,c in enumerate(items(obj(row.get('video_director_plan')).get('ai_calls'))))
    if kind=='task':
        meta=obj(row.get('metadata_json'))
        for clip,records in obj(obj(meta.get('h3_prompt_gate')).get('clips')).items():
            refs.extend((obj(r).get('llm_log_id'),f'metadata_json.h3_prompt_gate.clips.{clip}[{i}].llm_log_id') for i,r in enumerate(items(records)))
        plan=decode_evidence(obj(obj(meta.get('execution')).get('working_shot')).get('video_director_plan'),dict)['value']
        refs.extend((obj(c).get('llm_log_id'),f'metadata_json.execution.working_shot.video_director_plan.ai_calls[{i}].llm_log_id') for i,c in enumerate(items(obj(plan).get('ai_calls'))))
    return [(identity,path) for identity,path in refs if isinstance(identity,str) and identity]


def probe(operation):
    try:
        return {'state':'PASS', 'result':safe_value(operation()), 'issue':None}
    except HTTPException as exc:
        return {'state':'FAIL', 'result':None, 'issue':safe_value(exc.detail)}
    except (ValueError, RuntimeError, KeyError, TypeError, AttributeError, OSError) as exc:
        return {'state':'FAIL', 'result':None, 'issue':safe_value(str(exc))}


class AssetDebugService:
    def __init__(self, db, novel_id, max_nodes=400):
        self.db, self.novel_id, self.max_nodes = db, novel_id, max(1, min(max_nodes, 1200))
        title = db.execute(select(Novel.title).where(Novel.id == novel_id)).first()
        if not title:
            raise HTTPException(404, '小说不存在')
        self.novel_title = title[0]
        self.cache, self.nodes, self.edges, self.queue = {}, {}, [], deque()
        self.diagnostics, self.truncated, self.roots = [], False, []
        self.scope = {'novelId':novel_id, 'novelTitle':self.novel_title, 'chapterId':None, 'shotId':None, 'taskId':None, 'rsaId':None}

    def _read(self, kind, identity):
        if kind not in MODELS:
            raise HTTPException(404, '未知证据类型')
        key = (kind, identity)
        if key not in self.cache:
            self.cache[key] = read_record(self.db, MODELS[kind], identity)
        return self.cache[key]

    def _books(self, kind, identity, seen=None):
        seen = set() if seen is None else seen
        key = (kind, identity)
        if not identity or key in seen or len(seen)>24:
            return set()
        seen.add(key)
        saved = self._read(kind, identity)
        if saved is None:
            return set()
        row, books = saved['record'], set()
        if row.get('novel_id'):
            books.add(row['novel_id'])
        if kind == 'chapter':
            return books
        if row.get('chapter_id'):
            books |= self._books('chapter',row['chapter_id'],set(seen))
        if row.get('source_chapter_id'):
            books |= self._books('chapter',row['source_chapter_id'],set(seen))
        # Ownership FKs, not arbitrary references or names. Missing ownership stays unknown.
        owners = {
            'candidate':[('parse','run_id')], 'decision':[('resolution','run_id')],
            'source':[('split','run_id'),('shot','shot_id')], 'asset_head':[('shot','shot_id'),('rsa','rsa_id')],
            'appearance_review':[('appearance_event','event_id')],
            'appearance_image':[('appearance','appearance_id'),('appearance_generation','generation_id')],
            'media_artifact':[('rsa','rsa_id'),('media_attempt','task_id')],
            'audio_event':[('shot','shot_id')], 'audio_timeline':[('shot','shot_id')],
            'audio_timeline_event':[('audio_timeline','timeline_id')], 'tts_asset':[('audio_event','audio_event_id')],
            'task':[('shot','shot_id'),('character','character_id'),('scene','scene_id'),('prop','prop_id')],
        }
        for parent, field in owners.get(kind, []):
            if row.get(field):
                books |= self._books(parent,row[field],set(seen))
        return books

    def _require(self, kind, identity):
        saved = self._read(kind, identity)
        if saved is None or self._books(kind,identity) != {self.novel_id}:
            raise HTTPException(404, '记录不存在或所属小说无法确认')
        return saved

    def _select_ids(self, kind, field, value, limit=None):
        table = MODELS[kind].__table__
        primary = list(table.primary_key.columns)[0]
        order = [table.c.created_at.desc(), primary] if 'created_at' in table.c else [primary]
        count = limit or self.max_nodes
        rows = self.db.execute(select(primary).where(table.c[field] == value).order_by(*order).limit(count+1)).scalars().all()
        if len(rows)>count:
            self.truncated = True
        return rows[:count]

    def _summary(self, kind, identity, saved):
        row = saved['record']
        issues = [{'field':field,'code':info['state'],'message':info.get('error')} for field,info in saved['jsonFields'].items()
                  if info['state'] in {'INVALID_JSON','WRONG_TYPE','TOO_LARGE'}]
        availability = 'CORRUPT' if any(i['code'] != 'TOO_LARGE' for i in issues) else 'LIMITED' if issues else 'AVAILABLE'
        facts = {k:row[k] for k in ('novel_id','chapter_id','shot_id','task_id','character_id','appearance_id','rsa_id','rsa_hash','revision',
            'source_hash','input_hash','result_hash','definition_hash','seal','resolver_version','parser_version','source_start','source_end',
            'event_key','change_type','source_event_id','previous_appearance_id','stage','frame_index','error','last_error') if row.get(k) is not None}
        label = row.get('name') or row.get('title') or row.get('event_key') or ''
        if kind == 'shot': label = f"Shot #{row.get('index')}"
        if kind == 'decision':
            call, plan = obj(row.get('call')), obj(row.get('plan'))
            label = obj(row.get('candidate')).get('name') or identity
            facts.update(candidateName=label, assetType=row.get('asset_type'), resolution=row.get('resolution'),
                matchType=row.get('match_type'), matchedId=row.get('asset_id'), confidence=row.get('confidence'), llmUsed=row.get('llm_used'),
                promptVersion=call.get('templateVersion'), promptHash=call.get('templateHash'), metrics=plan.get('metrics'), manualAction=row.get('manual_action'))
        if kind == 'llm_log':
            label = row.get('task_type') or row.get('model') or identity
            facts.update(provider=row.get('provider'), model=row.get('model'), promptTemplateName=row.get('prompt_template_name'),
                durationSeconds=row.get('duration'), tokenUsage=row.get('usage_metrics'), error=row.get('error_message'))
        if kind == 'parse':
            facts['calls'] = [{k:c.get(k) for k in ('assetType','llmLogId','status','candidateCount','emptyConfirmed')}
                              | {'templateVersion':obj(c.get('template')).get('contractVersion'),'templateHash':obj(c.get('template')).get('hash')}
                              for c in items(row.get('calls')) if isinstance(c,dict)]
            facts['sourceTitle'] = row.get('source_title')
        if kind == 'rsa':
            facts['blockers'] = obj(row.get('data')).get('blockers')
            facts['selections'] = [{k:c.get(k) for k in ('character_id','appearance_id','reference_image_id','selection')}
                                   for c in items(obj(row.get('data')).get('characters')) if isinstance(c,dict)]
        if kind in {'media_attempt','appearance_generation'}:
            execution, inputs = obj(row.get('execution')), obj(row.get('inputs'))
            facts.update(phase=execution.get('phase'), submission=execution.get('submit'),
                uploads=execution.get('uploads'), graphProof=execution.get('graph_proof'),
                promptTemplate=inputs.get('template') and {k:obj(inputs['template']).get(k) for k in ('id','name','source_hash')},
                localPrompt=inputs.get('prompt_template') and {k:obj(inputs['prompt_template']).get(k) for k in ('file','version','hash')})
            # The entire graph belongs in the detail view, not every summary row.
            if isinstance(facts.get('submission'),dict):
                facts['submission'] = {k:v for k,v in facts['submission'].items() if k not in {'graph','workflow'}}
        if kind == 'media_artifact':
            facts.update(image=obj(row.get('data')).get('image'),parents=obj(row.get('data')).get('parents'))
        if kind == 'image_version':
            facts.update(origin=obj(row.get('data')).get('origin'),snapshot=obj(row.get('data')).get('snapshot'))
        if kind == 'appearance_image':
            facts.update(imageUrl=row.get('image_url'),sha256=row.get('sha256'),generationId=row.get('generation_id'))
        if kind == 'lifecycle':facts.update(origin=row.get('origin'),originEvidence=row.get('origin_evidence'),rebuildId=row.get('rebuild_id'))
        if kind == 'task':
            facts.update(taskType=row.get('type'),parentTaskId=row.get('parent_task_id'),promptId=row.get('comfyui_prompt_id'),
                         currentStep=row.get('current_step'),error=row.get('error_message'))
        return {'key':f'{kind}:{identity}','kind':kind,'id':identity,'label':f'{LABELS[kind]} · {label}' if label else LABELS[kind],
            'availability':availability,'recordStatus':row.get('status') or row.get('validation_status') or row.get('tts_status') or 'RECORDED',
            'createdAt':safe_value(row.get('created_at')),'facts':safe_value(facts),'issues':issues}

    def _add(self, kind, identity, origin=None, path=None):
        if not isinstance(identity,str) or not identity:
            return None
        key = f'{kind}:{identity}'
        if origin:
            edge = {'from':origin,'to':key,'path':path}
            if edge not in self.edges:self.edges.append(edge)
            if key == origin:self.diagnostics.append({'code':'SELF_REFERENCE','key':key,'path':path})
        if key in self.nodes:return key
        if len(self.nodes)>=self.max_nodes:
            self.truncated=True
            return key
        saved = self._read(kind,identity)
        availability = 'MISSING' if saved is None else 'OUT_OF_SCOPE' if self._books(kind,identity)!={self.novel_id} else None
        if availability:
            self.nodes[key]={'key':key,'kind':kind,'id':identity,'label':LABELS[kind], 'availability':availability,
                'recordStatus':'UNKNOWN','facts':{},'issues':[{'code':availability,'message':'记录缺失' if availability=='MISSING' else '所属小说无法确认，未展开记录'}]}
        else:
            self.nodes[key]=self._summary(kind,identity,saved)
            self.queue.append((kind,identity))
        return key

    def _expand(self, kind, identity):
        row = self._read(kind,identity)['record']; key=f'{kind}:{identity}'
        def link(target, value, path):return self._add(target,value,key,path)
        def children(target, field, value, path, limit=None):
            for child in self._select_ids(target,field,value,limit):link(target,child,path)
        for log_id,path in log_references(kind,row):link('llm_log',log_id,path)
        # Explicit stable ownership and producer columns shared by the ledgers.
        for field,target in (('chapter_id','chapter'),('source_chapter_id','chapter'),('character_id','character'),('scene_id','scene'),('prop_id','prop')):
            if kind!='chapter':link(target,row.get(field),field)
        if kind not in {'task','chapter'}:link('task',row.get('task_id'),'task_id')
        if kind not in {'shot','source','asset_head'}:link('shot',row.get('shot_id'),'shot_id')
        if kind == 'chapter':
            link('lifecycle',identity,'chapter_asset_lifecycle.chapter_id')
        elif kind == 'lifecycle':link('rebuild',row.get('rebuild_id'),'rebuild_id')
        elif kind == 'shot':
            link('source',identity,'shot_sources.shot_id');link('asset_head',identity,'shot_asset_heads.shot_id')
            for field in ('image_task_id','video_task_id'):link('task',row.get(field),field)
            for target in ('rsa','media_attempt','task','audio_event','audio_timeline'):
                children(target,'shot_id',identity,f'{MODELS[target].__tablename__}.shot_id')
        elif kind == 'asset_head':link('rsa',row.get('rsa_id'),'rsa_id')
        elif kind == 'source':
            link('split',row.get('run_id'),'run_id')
            for collection,values in obj(row.get('bindings')).items():
                target={'characters':'character_binding','voice_characters':'character_binding','scenes':'scene_binding','props':'prop_binding'}.get(collection)
                if target:
                    for i,binding in enumerate(items(values)):link(target,obj(binding).get('id'),f'bindings.{collection}[{i}].id')
        elif kind == 'split':
            basis=obj(obj(row.get('inputs')).get('basis'))
            link('timeline',obj(basis.get('timeline')).get('run_id'),'inputs.basis.timeline.run_id')
            for group,entry in obj(basis.get('scope')).items():
                link('resolution',obj(entry).get('runId'),f'inputs.basis.scope.{group}.runId')
        elif kind == 'parse':
            for i,call in enumerate(items(row.get('calls'))):link('llm_log',obj(call).get('llmLogId'),f'calls[{i}].llmLogId')
        elif kind == 'candidate':link('parse',row.get('run_id'),'run_id')
        elif kind == 'resolution':
            for name,entry in obj(obj(row.get('inputs')).get('kinds')).items():
                link('parse',obj(entry).get('parse_run_id'),f'inputs.kinds.{name}.parse_run_id')
        elif kind == 'decision':
            link('resolution',row.get('run_id'),'run_id');link('candidate',row.get('candidate_id'),'candidate_id')
            link(ASSET_KINDS.get(row.get('asset_type'),'character'),row.get('asset_id'),'asset_id')
            link('llm_log',obj(row.get('call')).get('llmLogId'),'call.llmLogId')
        elif kind.endswith('_binding'):
            link('resolution',row.get('resolution_run_id'),'resolution_run_id')
            for i,p in enumerate(items(row.get('provenance'))):
                for field,target in (('decision_id','decision'),('candidate_id','candidate'),('parse_run_id','parse')):
                    link(target,obj(p).get(field),f'provenance[{i}].{field}')
        elif kind == 'timeline':
            for i,chapter in enumerate(items(obj(row.get('inputs')).get('chapters'))):
                link('resolution',obj(chapter).get('resolution_run_id'),f'inputs.chapters[{i}].resolution_run_id')
                for j,entry in enumerate(items(obj(chapter).get('events'))):
                    link('appearance_event',obj(obj(entry).get('proposal')).get('id'),f'inputs.chapters[{i}].events[{j}].proposal.id')
                    link('appearance_review',obj(obj(entry).get('review')).get('id'),f'inputs.chapters[{i}].events[{j}].review.id')
        elif kind == 'appearance_event':
            for target,field in (('candidate','candidate_id'),('resolution','resolution_run_id'),('appearance','resolved_appearance_id')):link(target,row.get(field),field)
            children('appearance_review','event_id',identity,'appearance_event_reviews.event_id')
        elif kind == 'appearance_review':link('appearance_event',row.get('event_id'),'event_id')
        elif kind == 'character':
            link('identity',identity,'character_identities.character_id')
            children('alias','character_id',identity,'character_aliases.character_id')
        elif kind == 'appearance':
            for target,field in (('appearance_event','source_event_id'),('appearance','previous_appearance_id'),('appearance_image','reference_image_revision_id')):link(target,row.get(field),field)
            children('appearance_generation','appearance_id',identity,'appearance_generations.appearance_id')
        elif kind == 'appearance_image':
            link('appearance',row.get('appearance_id'),'appearance_id');link('appearance_generation',row.get('generation_id'),'generation_id')
        elif kind == 'appearance_generation':
            link('appearance',row.get('appearance_id'),'appearance_id');link('task',identity,'id = Task.id')
            link('llm_log',obj(obj(row.get('execution')).get('llm')).get('log_id'),'execution.llm.log_id')
            link('timeline',obj(obj(row.get('inputs')).get('timeline')).get('run_id'),'inputs.timeline.run_id')
            for i,usage in enumerate(items(obj(row.get('inputs')).get('usage_ids'))):link('demand',usage,f'inputs.usage_ids[{i}]')
            children('appearance_image','generation_id',identity,'appearance_image_revisions.generation_id')
        elif kind == 'rsa':
            logic=obj(obj(row.get('inputs')).get('logical')); data=obj(row.get('data'))
            link('split',obj(logic.get('source')).get('split_run_id'),'inputs.logical.source.split_run_id')
            link('timeline',obj(logic.get('timeline')).get('run_id'),'inputs.logical.timeline.run_id')
            for i,actor in enumerate(items(logic.get('characters'))):
                for target,field in (('character','character_id'),('appearance','appearance_id'),('timeline','timeline_run_id')):link(target,obj(actor).get(field),f'inputs.logical.characters[{i}].{field}')
                link('character_binding',obj(obj(actor).get('binding')).get('id'),f'inputs.logical.characters[{i}].binding.id')
                for j,eid in enumerate(items(obj(obj(actor).get('selection')).get('sourceEventIds'))):link('appearance_event',eid,f'inputs.logical.characters[{i}].selection.sourceEventIds[{j}]')
            scene=obj(logic.get('scene'));link('scene',scene.get('scene_id'),'inputs.logical.scene.scene_id')
            link('scene_binding',obj(scene.get('binding')).get('id'),'inputs.logical.scene.binding.id')
            for i,prop in enumerate(items(logic.get('props'))):
                link('prop',obj(prop).get('prop_id'),f'inputs.logical.props[{i}].prop_id')
                link('prop_binding',obj(obj(prop).get('binding')).get('id'),f'inputs.logical.props[{i}].binding.id')
            for slot,ref in obj(data.get('references')).items():link('image_version',obj(ref).get('image_revision_id'),f'data.references.{slot}.image_revision_id')
            for i,demand in enumerate(items(data.get('demands'))):link('demand',obj(demand).get('id'),f'data.demands[{i}].id')
        elif kind == 'image_version':
            origin=obj(obj(row.get('data')).get('origin'))
            target={'CHARACTER_BASE':'character','CHARACTER_APPEARANCE':'appearance','SCENE':'scene','PROP':'prop'}.get(origin.get('kind'))
            if target:link(target,origin.get('asset_id'),'data.origin.asset_id')
            link('appearance_image',origin.get('appearance_image_revision_id'),'data.origin.appearance_image_revision_id')
            link('task',origin.get('reported_task_id'),'data.origin.reported_task_id')
        elif kind == 'demand':
            link('rsa',row.get('rsa_id'),'rsa_id');link('appearance',row.get('appearance_id'),'appearance_id')
        elif kind == 'media_attempt':
            link('task',identity,'id = Task.id');link('rsa',row.get('rsa_id'),'rsa_id')
            link('media_artifact',row.get('artifact_id'),'artifact_id')
            link('llm_log',obj(obj(row.get('execution')).get('prompt')).get('llm_log_id'),'execution.prompt.llm_log_id')
            self._parents(link,obj(row.get('inputs')).get('parents'),'inputs.parents')
        elif kind == 'media_artifact':
            link('media_attempt',row.get('task_id'),'task_id');link('rsa',row.get('rsa_id'),'rsa_id')
            self._parents(link,obj(row.get('data')).get('parents'),'data.parents')
        elif kind == 'task':
            link('task',row.get('parent_task_id'),'parent_task_id')
            meta=obj(row.get('metadata_json'))
            for target,field in (('rsa','rsa_id'),('rebuild','rebuild_id'),('audio_event','audio_event_id')):link(target,meta.get(field),f'metadata_json.{field}')
            for field in ('source_pin','rsa_binding'):
                pin=obj(meta.get(field))
                link('split',pin.get('split_run_id'),f'metadata_json.{field}.split_run_id')
                link('rsa',pin.get('rsa_id'),f'metadata_json.{field}.rsa_id')
                for i,image in enumerate(items(pin.get('images'))):link('media_artifact',obj(image).get('id'),f'metadata_json.{field}.images[{i}].id')
            for sid,pin in obj(meta.get('source_pins')).items():
                link('shot',sid,f'metadata_json.source_pins.{sid}')
                link('split',obj(pin).get('split_run_id'),f'metadata_json.source_pins.{sid}.split_run_id')
            for i,sid in enumerate(items(meta.get('shot_ids'))):link('shot',sid,f'metadata_json.shot_ids[{i}]')
            for i,video in enumerate(items(obj(meta.get('merge_inputs')).get('videos'))):link('task',obj(video).get('task_id'),f'metadata_json.merge_inputs.videos[{i}].task_id')
            for target in ('parse','resolution','timeline','split','rsa','rebuild'):
                children(target,'task_id',identity,f'{MODELS[target].__tablename__}.task_id',1)
            for target in ('media_attempt','appearance_generation'):
                if self._read(target,identity):link(target,identity,'ledger.id = Task.id')
        elif kind == 'rebuild':
            stage_kinds={'CANDIDATES':'parse','BINDINGS':'resolution','TIMELINE':'timeline','SHOT_SOURCE':'split','RSA':'rsa'}
            for i,step in enumerate(items(row.get('steps'))):
                target=stage_kinds.get(obj(step).get('stage'));receipt=obj(step).get('receipt')
                if not target:continue
                payloads=receipt if isinstance(receipt,list) else [receipt]
                for j,payload in enumerate(payloads):
                    data=obj(obj(payload).get('data'));field='splitRunId' if target=='split' else 'id'
                    path=f'steps[{i}].receipt'+(f'[{j}]' if isinstance(receipt,list) else '')+'.data.'+field
                    link(target,data.get(field),path)
        elif kind == 'audio_event':
            link('character',row.get('voice_owner_character_id'),'voice_owner_character_id')
            link('character',row.get('visible_speaker_character_id'),'visible_speaker_character_id')
            children('tts_asset','audio_event_id',identity,'audio_event_tts_assets.audio_event_id')
        elif kind == 'tts_asset':
            link('audio_event',row.get('audio_event_id'),'audio_event_id');link('character',row.get('voice_id'),'voice_id')
            link('task',obj(row.get('config_json')).get('task_id'),'config_json.task_id')
        elif kind == 'audio_timeline':children('audio_timeline_event','timeline_id',identity,'shot_audio_timeline_events.timeline_id')
        elif kind == 'audio_timeline_event':
            link('audio_timeline',row.get('timeline_id'),'timeline_id');link('audio_event',row.get('audio_event_id'),'audio_event_id');link('tts_asset',row.get('tts_asset_id'),'tts_asset_id')

    @staticmethod
    def _parents(link, parents, path):
        for i,parent in enumerate(items(parents)):
            if obj(parent).get('kind')=='ARTIFACT':link('media_artifact',parent.get('id'),f'{path}[{i}].id')
            elif obj(parent).get('kind')=='IMAGE_VERSION':link('image_version',obj(parent.get('reference')).get('image_revision_id'),f'{path}[{i}].reference.image_revision_id')

    def chapter(self, chapter_id, shot_id=None, rsa_id=None):
        self._require('chapter',chapter_id);self.scope.update(chapterId=chapter_id,shotId=shot_id,rsaId=rsa_id)
        self.roots.append(self._add('chapter',chapter_id))
        if rsa_id:
            rsa=self._require('rsa',rsa_id)['record']
            if rsa.get('chapter_id')!=chapter_id or (shot_id and rsa.get('shot_id')!=shot_id):raise HTTPException(404,'最终资产不属于所选分镜/章回')
            self.scope['shotId']=rsa['shot_id'];self.roots.append(self._add('rsa',rsa_id))
        elif shot_id:
            shot=self._require('shot',shot_id)['record']
            if shot.get('chapter_id')!=chapter_id:raise HTTPException(404,'分镜不属于当前章回')
            self.roots.append(self._add('shot',shot_id))
        else:
            for kind in ('parse','resolution','timeline','split','rebuild','shot','character_binding','scene_binding','prop_binding','appearance_event'):
                for identity in self._select_ids(kind,'chapter_id',chapter_id):self._add(kind,identity,self.roots[0],f'{MODELS[kind].__tablename__}.chapter_id')
            # Includes AMBIGUOUS/failed decisions which intentionally have no Binding.
            for rid in self._select_ids('resolution','chapter_id',chapter_id):
                for did in self._select_ids('decision','run_id',rid):self._add('decision',did,f'resolution:{rid}','asset_resolution_decisions.run_id')
            for rid in self._select_ids('parse','chapter_id',chapter_id):
                for cid in self._select_ids('candidate','run_id',rid):self._add('candidate',cid,f'parse:{rid}','chapter_asset_candidates.run_id')
        return self._finish()

    def task(self, task_id):
        task=self._require('task',task_id)['record']
        self.scope.update(taskId=task_id,chapterId=task.get('chapter_id'),shotId=task.get('shot_id'))
        self.roots.append(self._add('task',task_id))
        return self._finish()

    def anchor(self, kind, identity):
        row=self._require(kind,identity)['record']
        self.scope.update(chapterId=row.get('chapter_id') or row.get('source_chapter_id'),shotId=row.get('shot_id'))
        self.roots.append(self._add(kind,identity))
        if kind=='llm_log':
            self._log_producers(identity,row)
        return self._finish()

    def _log_producers(self, log_id, log):
        for kind in ('parse','split','media_attempt','appearance_generation','task','shot','decision'):
            table=MODELS[kind].__table__;pk=list(table.primary_key.columns)[0]
            query=select(pk)
            if kind=='shot':
                query=query.join(Chapter,Chapter.id==table.c.chapter_id).where(Chapter.novel_id==self.novel_id)
            elif kind=='decision':
                query=query.join(AssetResolutionRun,AssetResolutionRun.id==table.c.run_id).where(AssetResolutionRun.novel_id==self.novel_id)
                if log.get('chapter_id'):query=query.where(AssetResolutionRun.chapter_id==log['chapter_id'])
            else:query=query.where(table.c.novel_id==self.novel_id)
            if log.get('chapter_id') and 'chapter_id' in table.c:query=query.where(table.c.chapter_id==log['chapter_id'])
            ids=self.db.execute(query.order_by(pk).limit(self.max_nodes+1)).scalars().all()
            if len(ids)>self.max_nodes:self.truncated=True
            for identity in ids[:self.max_nodes]:
                saved=self._read(kind,identity)
                if saved and any(ref==log_id for ref,_ in log_references(kind,saved['record'])):
                    self._add(kind,identity)

    @classmethod
    def from_task(cls, db, task_id, max_nodes=400):
        saved=read_record(db,Task,task_id)
        if saved is None:raise HTTPException(404,'任务不存在')
        row=saved['record'];book=row.get('novel_id')
        if not book:
            for kind,field in (('chapter','chapter_id'),('character','character_id'),('scene','scene_id'),('prop','prop_id')):
                if row.get(field):
                    owner=read_record(db,MODELS[kind],row[field])
                    if owner and owner['record'].get('novel_id'):book=owner['record']['novel_id'];break
        if not book:raise HTTPException(409,'TASK_SCOPE_UNRESOLVED: 未记录可验证的小说归属')
        return cls(db,book,max_nodes).task(task_id)

    def _finish(self):
        while self.queue:
            kind,identity=self.queue.popleft()
            self._expand(kind,identity)
        current={}
        if self.scope.get('chapterId'):
            from app.services.chapter_governance import pipeline_state
            check=probe(lambda:pipeline_state(self.db,self.novel_id,self.scope['chapterId']))
            if check['result']:
                check['result']={k:check['result'].get(k) for k in ('origin','condition','needsRebuild','structuralReady','missingStages','timelineStatus')}
            current['chapter']=check
        if self.scope.get('shotId'):
            from app.services.runtime_gate import runtime_checks
            check=probe(lambda:runtime_checks(self.db,self.scope['shotId']))
            current['shot']=check['result'] if check['state']=='PASS' else {'shotId':self.scope['shotId'],'checks':{},'issue':check['issue']}
        nodes=list(self.nodes.values())
        return {'version':'asset-debug-v1','readOnly':True,'readAt':datetime.now(timezone.utc).isoformat(),'scope':self.scope,
            'roots':self.roots,'nodes':nodes,'edges':self.edges,'current':current,'diagnostics':self.diagnostics,
            'coverage':{'truncated':self.truncated,'nodeLimit':self.max_nodes,'nodeCount':len(nodes),
                'missingNodes':[n['key'] for n in nodes if n['availability']=='MISSING'],
                'invalidNodes':[n['key'] for n in nodes if n['availability'] in {'CORRUPT','LIMITED'}],
                'scopeConflicts':[n['key'] for n in nodes if n['availability']=='OUT_OF_SCOPE']}}

    def record(self, kind, identity):
        saved=self._require(kind,identity);row=saved['record'];summary=self._summary(kind,identity,saved)
        checks=[]
        for field,hash_field in (('inputs','input_hash'),('data','result_hash'),('result','result_hash'),('definition','definition_hash')):
            if row.get(hash_field) and row.get(field) is not None:
                actual=digest(row[field]);checks.append({'code':f'{field.upper()}_HASH','state':'PASS' if actual==row[hash_field] else 'FAIL','expected':row[hash_field],'actual':actual})
        if kind in {'image_version','media_artifact'} and row.get('data') is not None:
            actual=digest(row['data']);checks.append({'code':'RECORD_SEAL','state':'PASS' if actual==row.get('seal') else 'FAIL','expected':row.get('seal'),'actual':actual})
        current={'state':'NOT_CHECKED','issue':'此记录的存在或哈希自洽不等于当前生成准入'}
        if summary['availability'] in {'CORRUPT','LIMITED'}:
            current={'state':'FAIL','issue':'证据缺失、损坏或超出检查上限'}
        elif kind in {'rsa','source','shot','media_artifact','image_version','parse','timeline','resolution'}:
            def verify():
                if kind=='rsa':
                    from app.services.resolved_shot_assets_service import require_frozen_rsa
                    require_frozen_rsa(self.db,row['shot_id'],identity,row['result_hash'])
                elif kind in {'source','shot'}:
                    from app.services.chapter_governance import require_source
                    require_source(self.db,row['shot_id'] if kind=='source' else identity)
                elif kind=='media_artifact':
                    from app.services.rsa_media_contract import artifact_proof
                    artifact_proof(self.db,identity,rsa_id=row['rsa_id'],rsa_hash=obj(row['data']).get('rsa_hash'))
                elif kind=='image_version':
                    from app.services.resolved_asset_images import verify_image_version,reference_for
                    verify_image_version(self.db,reference_for(self.db.get(ResolvedImageVersion,identity)))
                elif kind=='parse':
                    from app.services.chapter_asset_parse_service import run_response
                    result=run_response(self.db,self.db.get(ChapterAssetParseRun,identity),detail=False)
                    if not result['phase1Ready']:raise HTTPException(409,result['effectiveStatus'])
                elif kind=='resolution':
                    from app.services.asset_resolution_service import resolution_response
                    result=resolution_response(self.db,self.db.get(AssetResolutionRun,identity))
                    if not result['phase2Ready']:raise HTTPException(409,result['effectiveStatus'])
                elif kind=='timeline':
                    from app.services.appearance_timeline_service import timeline_response
                    result=timeline_response(self.db,self.db.get(AppearanceTimelineRun,identity),detail=False)
                    if not result['phase3Ready']:raise HTTPException(409,result['effectiveStatus'])
                return True
            current=probe(verify)
        return {**summary,'record':safe_value(row),'jsonFields':{k:public_evidence(v,False) for k,v in saved['jsonFields'].items()},
            'textFields':{k:{'sha256':sha_text(v),'length':len(v),'truncated':len(v)>MAX_DISPLAY_CHARS}
                          for k,v in row.items() if isinstance(v,str) and len(v)>256},'hashChecks':checks,'currentGate':current}
