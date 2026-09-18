"""The Chapter-only input and deterministic grounding contract for Shot splitting."""
from copy import deepcopy
import json
from pathlib import Path
import re
from fastapi import HTTPException
from app.models.novel import Novel, Chapter, Character
from app.models.task import Task
from app.models.prompt_template import PromptTemplate
from app.models.asset_resolution import AssetResolutionRun
from app.models.appearance_timeline import AppearanceTimelineRun
from app.services.asset_resolution_service import binding_state
from app.services.appearance_timeline_service import timeline_response
from app.services.chapter_asset_parse_service import digest, source_hash
from app.services.prompt_builder import get_style
from app.services.source_speech import direct_speech_matches, direct_speech_quotes

VERSION = "chapter-scope-shot-split-v1.0.1"
OWNERSHIP_VERSION = "chapter-shot-ownership-v2"
OWNERSHIP_RUN_VERSION = "chapter-scope-shot-split-v2.0.0"
SOURCE_WINDOW_RUN_VERSION = "chapter-scope-shot-split-v2.1.0"
SCENE_BOUNDARY_RUN_VERSION = "chapter-scope-shot-split-v2.2.0"
SOURCE_WINDOW_VERSION = "appearance-source-windows-v1"
TASK_TYPE = "chapter_shot_split"
POLICY_PATH = Path(__file__).resolve().parents[2] / "prompt_templates/chapter_scope_split.json"
OWNERSHIP_POLICY_PATH = Path(__file__).resolve().parents[2] / "prompt_templates/chapter_shot_ownership_v2.json"
SOURCE_WINDOW_CONTRACT = {
    'version':SOURCE_WINDOW_VERSION,
    'scope':'PER_VISIBLE_CHARACTER_NOT_GLOBAL',
    'offset_unit':'UNICODE_CODE_POINT',
    'end_exclusive':True,
}


def load_policy():
    raw = POLICY_PATH.read_text(encoding="utf-8")
    value = json.loads(raw)
    for key in ("version", "system_suffix", "user_template", "boundary_instruction", "repair_instruction"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError("CHAPTER_SCOPE_PROMPT_INVALID")
    if any(type(value.get(key)) is not int or value[key] < 1 for key in ("max_source_characters", "max_tokens")):
        raise ValueError("CHAPTER_SCOPE_LIMITS_INVALID")
    return {"file": "prompt_templates/chapter_scope_split.json", "hash": digest(raw), "definition": value}


def load_ownership_policy():
    raw = OWNERSHIP_POLICY_PATH.read_text(encoding='utf-8')
    value = json.loads(raw)
    if (value.get('version') != OWNERSHIP_VERSION
            or value.get('run_version') != OWNERSHIP_RUN_VERSION
            or not isinstance(value.get('system_suffix'), str) or not value['system_suffix'].strip()
            or not isinstance(value.get('compatible_template_hashes'), list)
            or not value['compatible_template_hashes']
            or any(not isinstance(item, str) or not item for item in value['compatible_template_hashes'])
            or not isinstance(value.get('scene_boundary_template_hashes'), list)
            or not value['scene_boundary_template_hashes']
            or any(not isinstance(item, str) or not item for item in value['scene_boundary_template_hashes'])):
        raise ValueError('SHOT_OWNERSHIP_PROMPT_INVALID')
    return {'file':'prompt_templates/chapter_shot_ownership_v2.json','hash':digest(raw),'definition':value}


def run_version(source_contract_version=None, run_profile=None):
    if source_contract_version is None:
        if run_profile not in (None,VERSION):raise ValueError(f'SHOT_SPLIT_VERSION: {run_profile}')
        return VERSION
    if source_contract_version == OWNERSHIP_VERSION:
        if run_profile is None:return SCENE_BOUNDARY_RUN_VERSION
        if run_profile in {OWNERSHIP_RUN_VERSION,SOURCE_WINDOW_RUN_VERSION,SCENE_BOUNDARY_RUN_VERSION}:return run_profile
        raise ValueError(f'SHOT_SPLIT_VERSION: {run_profile}')
    raise ValueError(f'SOURCE_CONTRACT_VERSION: {source_contract_version}')


def source_window_version(run_profile):
    return SOURCE_WINDOW_VERSION if run_profile in {SOURCE_WINDOW_RUN_VERSION,SCENE_BOUNDARY_RUN_VERSION} else None


def _logical_selection(selection):
    return {key:deepcopy(selection.get(key)) for key in (
        'kind','appearanceId','sourceEventIds','sourceChapterId','reason')}


def build_source_windows(target,content,timeline_run_id):
    characters=[];hard={};unresolved=[]
    for character in target.get('characters',[]):
        segments=character.get('segments') or []
        logical=[_logical_selection(item.get('selection') or {}) for item in segments]
        if any(item.get('kind')=='UNRESOLVED' for item in logical):
            unresolved.append({'character_id':character['characterId'],'name':character['name']})
            continue
        if len(segments)<2 or len({digest(item) for item in logical})<2:continue
        windows=[]
        for ordinal,(segment,selection) in enumerate(zip(segments,logical),1):
            identity={'version':SOURCE_WINDOW_VERSION,'timeline_run_id':timeline_run_id,
                'character_id':character['characterId'],'ordinal':ordinal,'start':segment['start'],'end':segment['end'],
                'selection':selection}
            windows.append({'window_id':'asw-'+digest(identity)[:24],'start':segment['start'],'end':segment['end'],
                'selection':selection,'opening_text':content[segment['start']:min(segment['end'],segment['start']+48)],
                'closing_text':content[max(segment['start'],segment['end']-48):segment['end']]})
            if ordinal>1:hard.setdefault(segment['start'],[]).append(character['name'])
        characters.append({'character_id':character['characterId'],'name':character['name'],'windows':windows})
    if not characters and not unresolved:return None
    return {'version':SOURCE_WINDOW_VERSION,'offset_unit':'UNICODE_CODE_POINT','end_exclusive':True,
        'timeline_run_id':timeline_run_id,'hard_boundaries':[{'offset':offset,'characters':names} for offset,names in sorted(hard.items())],
        'characters':characters,'unresolved_characters':unresolved,'contract':deepcopy(SOURCE_WINDOW_CONTRACT)}


def collect_scope(db, novel_id, chapter_id, source_contract_version=None, run_profile=None):
    try:
        selected_run_version=run_version(source_contract_version,run_profile)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    chapter = db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).populate_existing().first()
    novel = db.get(Novel, novel_id)
    if not chapter or not novel:
        raise HTTPException(404, "章回不存在")
    try:
        policy = load_policy()
    except (ValueError, OSError) as exc:
        raise HTTPException(409,f"CHAPTER_SCOPE_POLICY_INVALID: {exc}") from exc
    if not chapter.content or not chapter.content.strip():
        raise HTTPException(409, "CHAPTER_SOURCE_EMPTY")
    if len(chapter.content) > policy["definition"]["max_source_characters"]:
        raise HTTPException(409, "CHAPTER_SOURCE_TOO_LONG: 不截断原文，请先拆分章回")
    scope = binding_state(db, novel_id, chapter_id)
    if not scope["phase2Ready"]:
        raise HTTPException(409, {"code": "CHAPTER_BINDINGS_NOT_READY", "assets": {k: v["status"] for k,v in scope["assets"].items()}})
    for kind, item in scope["assets"].items():
        run = db.get(AssetResolutionRun, item["runId"])
        task = db.get(Task, run.task_id) if run else None
        if not run or digest(run.inputs) != run.input_hash or not task or task.status != "completed":
            raise HTTPException(409, f"BINDING_RECEIPT_INVALID: {kind}")
        item["bindings"] = sorted(item["bindings"], key=lambda b: b["assetId"])
        if kind == "characters":
            for binding in item["bindings"]:
                binding["groupSizeHint"] = db.get(Character,binding["assetId"]).identity.group_size_hint
        names = [b["name"] for b in item["bindings"]]
        if len(names) != len(set(names)):
            raise HTTPException(409, f"CHAPTER_BINDING_NAME_AMBIGUOUS: {kind}")
    timeline, timeline_run, boundaries, target = None, None, [], None
    if scope["assets"]["characters"]["bindings"]:
        timeline_run = db.query(AppearanceTimelineRun).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(
            AppearanceTimelineRun.created_at.desc(), AppearanceTimelineRun.id.desc()).first()
        if not timeline_run or timeline_response(db, timeline_run)["effectiveStatus"] not in {"SUCCEEDED", "NEEDS_REVIEW"}:
            raise HTTPException(409, "APPEARANCE_TIMELINE_NOT_CURRENT")
        timeline = {"run_id": timeline_run.id, "input_hash": timeline_run.input_hash, "result_hash": digest(timeline_run.result), "version": timeline_run.resolver_version}
        target = next(c for c in timeline_run.result["chapters"] if c["chapterId"] == chapter_id)
        boundaries = [{"character_id": c["characterId"], "name": c["name"], "segments": [
            {"start": s["start"], "end": s["end"], "logical_status": s["selection"]["kind"],
             "opening_text": chapter.content[s["start"]:min(s["end"],s["start"]+48)],
             "closing_text": chapter.content[max(s["start"],s["end"]-48):s["end"]]} for s in c["segments"]]} for c in target["characters"]]
    template = db.get(PromptTemplate, novel.chapter_split_prompt_template_id) if novel.chapter_split_prompt_template_id else db.query(PromptTemplate).filter_by(type="chapter_split", is_system=True, is_active=True).order_by(PromptTemplate.id).first()
    if not template or template.type != "chapter_split" or not template.is_active or not template.template:
        raise HTTPException(409, "CHAPTER_SPLIT_TEMPLATE_REQUIRED")
    style, style_template = get_style(db, novel, "character")
    result = {"version": selected_run_version, "novel_id": novel_id, "chapter_id": chapter_id,
        "source": {"title": chapter.title, "content": chapter.content, "hash": source_hash(chapter)},
        "scope": scope["assets"], "timeline": timeline, "appearance_boundaries": boundaries, "policy": policy,
        "template": {"id": template.id, "name": template.name, "text": template.template, "hash": digest(template.template)},
        "style": {"text": style, "template_id": style_template.id if style_template else None}}
    if source_contract_version == OWNERSHIP_VERSION:
        try:
            ownership_policy = load_ownership_policy()
        except (ValueError, OSError) as exc:
            raise HTTPException(409, f'SHOT_OWNERSHIP_PROMPT_INVALID: {exc}') from exc
        if result['template']['hash'] not in ownership_policy['definition']['compatible_template_hashes']:
            raise HTTPException(409, 'SHOT_OWNERSHIP_TEMPLATE_INCOMPATIBLE')
        if (selected_run_version==SCENE_BOUNDARY_RUN_VERSION
                and result['template']['hash'] not in ownership_policy['definition']['scene_boundary_template_hashes']):
            raise HTTPException(409,'SHOT_SCENE_TEMPLATE_INCOMPATIBLE')
        result['source_contract_version'] = OWNERSHIP_VERSION
        result['source_contract_policy'] = ownership_policy
        if source_window_version(selected_run_version):
            windows=build_source_windows(target or {},chapter.content,timeline_run.id if timeline else None)
            result['source_window_contract']={'version':SOURCE_WINDOW_VERSION,'hash':digest(SOURCE_WINDOW_CONTRACT),
                'definition':deepcopy(SOURCE_WINDOW_CONTRACT)}
            result['source_windows']=windows or {'version':SOURCE_WINDOW_VERSION,'offset_unit':'UNICODE_CODE_POINT',
                'end_exclusive':True,'timeline_run_id':timeline_run.id if timeline else None,'hard_boundaries':[],
                'characters':[],'unresolved_characters':[],'contract':deepcopy(SOURCE_WINDOW_CONTRACT)}
    return result


def request_prompts(basis, repair=None):
    template, policy = basis["template"], basis["policy"]["definition"]
    system = template["text"].replace("{每个分镜对应拆分故事字数}", "100").replace("{图像风格}", basis["style"]["text"]).replace("##STYLE##", basis["style"]["text"])
    payload = {"chapter_title": basis["source"]["title"], "chapter_text": basis["source"]["content"],
        "asset_bindings": basis["scope"], "appearance_boundaries": basis["appearance_boundaries"], "narration_allowed": True}
    for kind, group in basis["scope"].items():
        payload["allowed_"+kind] = [row["name"] for row in group["bindings"]]
    if repair:
        payload["previous_rejected_attempt"] = repair
    from app.services.shot_treatment_contract import load_director_increment
    increment=load_director_increment()['definition']
    suffix=increment['system_suffix']+increment.get('dialogue_evidence_suffix','')
    if basis.get('locked_shots') is not None:
        payload['locked_shots']=basis['locked_shots']
        suffix+=increment['structure_lock_suffix']
    if basis.get('source_contract_version') == OWNERSHIP_VERSION:
        payload['source_contract_version'] = OWNERSHIP_VERSION
        suffix += basis['source_contract_policy']['definition']['system_suffix']
    if basis.get('source_windows') is not None:
        payload['source_windows']=basis['source_windows']
    return system + policy["system_suffix"] + "\n" + policy["boundary_instruction"] + ("\n" + policy["repair_instruction"] if repair else "") + suffix, policy["user_template"].format_map({"payload": json.dumps(payload, ensure_ascii=False)})


class SplitReview(ValueError):
    pass


def scene_membership_evidence(binding):
    """Representative membership witnesses; key presence makes an empty list authoritative."""
    if "membershipEvidence" in binding:return binding["membershipEvidence"]
    if "sourceEvidence" in binding:return binding["sourceEvidence"]
    return binding.get("source_evidence") or []


def _exact_occurrences(content, value):
    result=[];cursor=0
    while value:
        start=content.find(value,cursor)
        if start<0:break
        result.append((start,start+len(value)));cursor=start+1
    return result


def direct_local_scene_evidence(basis,start,end):
    """Locate unique Scene membership witnesses inside one canonical Shot source span."""
    content=basis["source"]["content"];result=[];seen=set()
    for binding in basis["scope"]["scenes"]["bindings"]:
        scene_id=binding.get("assetId")
        if not scene_id:continue
        for quote in scene_membership_evidence(binding):
            text=quote.get("text") if isinstance(quote,dict) else None
            ranges=_exact_occurrences(content,text) if text else []
            if len(ranges)!=1 or not (start<=ranges[0][0] and ranges[0][1]<=end):continue
            key=(scene_id,text,*ranges[0])
            if key in seen:continue
            seen.add(key);result.append({"scene":binding["name"],"sceneAssetId":scene_id,
                "text":text,"range":[ranges[0][0],ranges[0][1]]})
    return sorted(result,key=lambda item:(item["range"][0],item["range"][1],item["sceneAssetId"],item["text"]))


def deterministic_scene_crossing(basis,start,end):
    """Return the earliest ordered pair of distinct canonical Scene witnesses, or None."""
    evidence=direct_local_scene_evidence(basis,start,end)
    for index,left in enumerate(evidence):
        for right in evidence[index+1:]:
            if left["sceneAssetId"]!=right["sceneAssetId"] and left["range"][1]<=right["range"][0]:
                return [left,right]
    return None


def project_source_whitespace(source_text,value):
    if value in source_text:return value,None
    target=''.join(value.split())
    compact=[];positions=[]
    for index,char in enumerate(source_text):
        if not char.isspace():compact.append(char);positions.append(index)
    compact=''.join(compact);matches=[];cursor=0
    while target:
        found=compact.find(target,cursor)
        if found<0:break
        matches.append(found);cursor=found+1
    if len(matches)!=1:return value,None
    offset=matches[0];left=positions[offset];right=positions[offset+len(target)-1]+1
    exact=source_text[left:right]
    if ''.join(exact.split())!=target:return value,None
    return exact,{'local_start':left,'local_end':right}


def visible_character_findings(description, characters, shot_index, video_description=None):
    """Collect every flat character-block violation without changing acceptance semantics."""
    findings=[]
    if not description.startswith("Scene:") or 'Action:' not in description or not description.split("Action:",1)[-1].strip():
        return [{"code":"SHOT_CHARACTER_DESCRIPTION_FORMAT","shot_index":shot_index,
            "field":"description","message":"SHOT_CHARACTER_DESCRIPTION_FORMAT"}]
    for field, text in [('description',description),('video_description',video_description or '')]:
        headers=list(re.finditer(r'^[ \t]*Characters[ \t]*[:：][ \t]*',text,flags=re.M|re.I))
        if field=='description' and not headers:
            findings.append({"code":"SHOT_CHARACTER_DESCRIPTION_FORMAT","shot_index":shot_index,
                "field":field,"message":"SHOT_CHARACTER_DESCRIPTION_FORMAT"})
            continue
        for index,header in enumerate(headers):
            body=re.split(r'^[ \t]*(?:Scene|Action|Characters)[ \t]*[:：]',text[header.end():],maxsplit=1,flags=re.M|re.I)[0]
            labels=[]
            for line_number,line in enumerate(body.splitlines(),1):
                if not line.strip():continue
                parsed=re.fullmatch(r'[ \t]*-[ \t]+([^:\r\n：]+?)[ \t]*[:：][ \t]*([^\r\n]*)',line)
                if not parsed or not parsed[1].strip():
                    detail={'field':field,'block':index+1,'line':line_number,'format':'characters-flat-v1'}
                    findings.append({"code":"SHOT_CHARACTER_DESCRIPTION_FORMAT","shot_index":shot_index,
                        **detail,"message":'SHOT_CHARACTER_DESCRIPTION_FORMAT: '+json.dumps(detail,ensure_ascii=False)})
                    continue
                labels.append(parsed[1].strip())
            duplicates=sorted({name for name in labels if labels.count(name)>1})
            unexpected=[name for name in labels if name not in characters]
            missing=[name for name in characters if name not in labels] if field=='description' and index==0 else []
            if duplicates or unexpected or missing:
                detail={'shot_index':shot_index,'declared_characters':characters,'description_characters':labels}
                if field!='description':detail['field']=field
                message='SHOT_VISIBLE_CHARACTER_CLOSURE: '+json.dumps(detail,ensure_ascii=False)
                findings.append({"code":"SHOT_VISIBLE_CHARACTER_CLOSURE","shot_index":shot_index,
                    "field":field,"block":index+1,"declared_characters":characters,
                    "description_characters":labels,"missing_characters":missing,
                    "unexpected_characters":unexpected,"duplicate_characters":duplicates,"message":message})
    return findings


def is_normal_visual_shot(shot):
    return shot.get('completion_disposition') != 'DEGRADED_NARRATION_CARD'


def collect_visible_character_findings(data):
    return [finding for index,shot in enumerate(data.get('shots') or [],1)
        if is_normal_visual_shot(shot)
        for finding in visible_character_findings(shot['description'],shot['characters'],index,shot.get('video_description'))]


def collect_appearance_crossing_findings(data,basis):
    content=basis['source']['content'];boundaries={row['name']:row['segments'] for row in basis['appearance_boundaries']}
    findings=[]
    for index,shot in enumerate(data.get('shots') or [],1):
        if not is_normal_visual_shot(shot):continue
        try:source=ownership_source(content,shot)['ownership_range']
        except ValueError:continue
        start,end=source['start'],source['end']
        for name in shot.get('characters') or []:
            segments=boundaries.get(name,[])
            if any(segment['start']<=start and end<=segment['end'] for segment in segments):continue
            for before,after in zip(segments,segments[1:]):
                boundary=before['end']
                if start<boundary<end:
                    detail={'shot_index':index,'character':name,'evidence_range':[start,end],
                        'boundary':boundary,'before':deepcopy(before),'after':deepcopy(after)}
                    findings.append({'code':'SHOT_CROSSES_APPEARANCE_BOUNDARY',**detail,
                        'message':'SHOT_CROSSES_APPEARANCE_BOUNDARY: '+json.dumps({
                            'shot_index':index,'character':name,'evidence_range':[start,end],
                            'allowed_segments':segments},ensure_ascii=False)})
    return findings


def validate_visible_character_closure(description, characters, shot_index, video_description=None):
    """Shared split/revision invariant; authored wording cannot add an unbound subject."""
    findings=visible_character_findings(description,characters,shot_index,video_description)
    if findings:raise SplitReview(findings[0]['message'])


def derive_source_window_bindings(characters,start,end,basis):
    windows=basis.get('source_windows')
    if windows is None:return []
    by_name={item['name']:item for item in windows['characters']}
    result=[]
    for name in characters:
        character=by_name.get(name)
        if not character:continue
        window=next((candidate for candidate in character['windows'] if candidate['start']<=start and end<=candidate['end']),None)
        if not window:return None
        result.append({'character_id':character['character_id'],'name':name,'window_id':window['window_id'],
            'source_start':window['start'],'source_end':window['end'],'selection':deepcopy(window['selection'])})
    return result


def resolve_source_window_bindings(shot,start,end,basis,shot_index):
    windows=basis.get('source_windows')
    if windows is None:return []
    by_name={item['name']:item for item in windows['characters']}
    resolved=derive_source_window_bindings(shot['characters'],start,end,basis)
    expected_names=[name for name in shot['characters'] if name in by_name]
    if resolved is None:
        raise SplitReview('SHOT_SOURCE_WINDOW_RANGE_INVALID: '+json.dumps({
            'shot_index':shot_index,'shot_range':[start,end],'characters':expected_names},ensure_ascii=False))
    return resolved


def locate_ranges(content, evidence):
    ranges = []
    for item in evidence:
        value = item["text"]
        start = content.find(value)
        if start < 0:
            raise SplitReview("SHOT_EVIDENCE_NOT_FOUND: " + json.dumps({'evidence_text':value},ensure_ascii=False))
        if content.find(value, start+1) >= 0:
            raise SplitReview("SHOT_EVIDENCE_AMBIGUOUS")
        ranges.append({"start": start, "end": start+len(value), "text": value})
    previous = None
    for span in ranges:
        if previous is not None and (span["start"] < previous or content[previous:span["start"]].strip()):
            raise SplitReview("SHOT_EVIDENCE_NOT_CONTIGUOUS: " + json.dumps({'previous_end':previous,'next_start':span['start'],
                'omitted_text':content[previous:span['start']][:200]},ensure_ascii=False))
        previous = span["end"]
    return ranges


def _clean_evidence(value):
    return {key:value[key] for key in ('text','context_before','context_after') if value.get(key) is not None}


def locate_ownership_evidence(content, evidence, *, domain=None, kind='OWNERSHIP'):
    value = evidence['text']
    left, right = domain or (0, len(content))
    candidates, cursor = [], left
    while True:
        start = content.find(value, cursor, right)
        if start < 0:
            break
        end = start + len(value)
        cursor = start + 1
        if end > right:
            continue
        before, after = evidence.get('context_before'), evidence.get('context_after')
        if before is not None and content[max(0,start-len(before)):start] != before:
            continue
        if after is not None and content[end:end+len(after)] != after:
            continue
        candidates.append({'start':start,'end':end,'text':value})
    if not candidates:
        raise SplitReview(f'SHOT_{kind}_NOT_FOUND')
    if len(candidates) != 1:
        raise SplitReview(f'SHOT_{kind}_AMBIGUOUS')
    return candidates[0]


def ownership_source(content, shot):
    ownership_evidence = _clean_evidence(shot['source_ownership'])
    ownership_range = locate_ownership_evidence(content, ownership_evidence)
    citation_evidence = [_clean_evidence(item) for item in shot['source_citations']]
    citation_ranges=[]
    for item in citation_evidence:
        try:
            span=locate_ownership_evidence(
                content,item,domain=(ownership_range['start'],ownership_range['end']),kind='CITATION')
        except SplitReview as exc:
            if str(exc)!='SHOT_CITATION_NOT_FOUND':raise
            try:
                locate_ownership_evidence(content,item,kind='CITATION')
            except SplitReview as global_exc:
                if str(global_exc)=='SHOT_CITATION_NOT_FOUND':raise exc
            raise SplitReview('SHOT_CITATION_OUTSIDE_OWNERSHIP') from exc
        citation_ranges.append(span)
    previous_end = None
    for span in citation_ranges:
        if previous_end is not None and span['start'] < previous_end:
            raise SplitReview('SHOT_CITATION_ORDER_INVALID')
        previous_end = span['end']
    return {
        'version':OWNERSHIP_VERSION,
        'citation_evidence':citation_evidence,
        'citation_ranges':citation_ranges,
        'ownership_evidence':ownership_evidence,
        'ownership_range':ownership_range,
    }


def validate_plan(data, basis, *, historical_structure=False, controlled_degradation=None):
    content = basis["source"]["content"]
    ownership_v2 = basis.get('source_contract_version') == OWNERSHIP_VERSION
    if ownership_v2 != (data.get('source_contract_version') == OWNERSHIP_VERSION):
        raise SplitReview('SOURCE_CONTRACT_VERSION')
    if data["chapter"] != basis["source"]["title"]:
        raise SplitReview("SHOT_CHAPTER_TITLE_MISMATCH")
    allowed = {kind: {b["name"]: b for b in group["bindings"]} for kind, group in basis["scope"].items()}
    if data["unresolved_assets"]:
        for item in data["unresolved_assets"]:
            locate_ranges(content, item["source_evidence"])
        raise SplitReview("UPSTREAM_ASSET_MISSING: " + json.dumps(data["unresolved_assets"], ensure_ascii=False))
    if not data["shots"]:
        raise SplitReview("EMPTY_SHOT_OUTPUT_NOT_SUCCESS")
    used = {kind: set() for kind in allowed}
    expected_cards=(controlled_degradation or {}).get('cards') or {}
    seen_cards=set()
    all_dialogues, prepared, previous_end = [], [], 0
    boundaries = {row["name"]: row["segments"] for row in basis["appearance_boundaries"]}
    for index, raw_shot in enumerate(data["shots"], 1):
        shot=deepcopy(raw_shot)
        if shot["id"] != index:
            raise SplitReview("SHOT_ORDER_INVALID")
        source_contract = None
        try:
            if ownership_v2:
                source_contract = ownership_source(content, shot)
                ranges = [source_contract['ownership_range']]
                evidence = [source_contract['ownership_evidence']]
            else:
                ranges = locate_ranges(content, shot["source_evidence"])
                evidence = shot['source_evidence']
        except SplitReview as exc:
            raise SplitReview(f'{exc}; shot_index={index}') from exc
        start, end = ranges[0]["start"], ranges[-1]["end"]
        if start < previous_end:
            raise SplitReview("SHOT_SOURCE_OVERLAP_OR_REORDERED")
        previous_end = end
        is_card=not is_normal_visual_shot(shot)
        if is_card:
            expected=expected_cards.get(index)
            if expected is None or shot!=expected:raise SplitReview('CONTROLLED_DEGRADATION_CARD_CHANGED')
            seen_cards.add(index);bound={kind:[] for kind in ('characters','scenes','props')};source_window_bindings=[]
            if basis.get('source_windows') is not None:bound['source_windows']=[]
        else:
            if index in expected_cards:raise SplitReview('CONTROLLED_DEGRADATION_CARD_MISSING')
            names = {"characters": shot["characters"], "scenes": [shot["scene"]], "props": shot["props"]}
            bound = {}
            for kind, values in names.items():
                if len(set(values)) != len(values) or any(name not in allowed[kind] for name in values):
                    raise SplitReview(f"SHOT_ASSET_OUTSIDE_CHAPTER: {kind} {values}")
                bound[kind] = [deepcopy(allowed[kind][name]) for name in values]
                used[kind].update(values)
            for name in shot["characters"]:
                segment = next((s for s in boundaries.get(name, []) if s["start"] <= start and end <= s["end"]), None)
                if not segment:
                    raise SplitReview("SHOT_CROSSES_APPEARANCE_BOUNDARY: " + json.dumps({"shot_index":index,"character":name,
                        "evidence_range":[start,end],"allowed_segments":boundaries.get(name,[])},ensure_ascii=False))
                if segment["logical_status"] == "UNRESOLVED":
                    raise SplitReview(f"SHOT_APPEARANCE_UNRESOLVED: {index} {name}")
            source_window_bindings=resolve_source_window_bindings(shot,start,end,basis,index)
            if basis.get('source_windows') is not None:bound['source_windows']=deepcopy(source_window_bindings)
            if basis.get("version")==SCENE_BOUNDARY_RUN_VERSION:
                crossing=deterministic_scene_crossing(basis,start,end)
                if crossing:raise SplitReview("SHOT_CROSSES_SCENE_BOUNDARY: "+json.dumps({
                    "shot_index":index,"evidence_range":[start,end],
                    "proof":"ORDERED_DISTINCT_DIRECT_LOCAL_SCENE_EVIDENCE","scene_evidence":crossing},ensure_ascii=False))
            validate_visible_character_closure(shot['description'], shot['characters'], index, shot['video_description'])
        deterministic_normalizations=[];owned_text=content[start:end]
        for field,collection in (("dialogues",shot["dialogues"]),("audio_events",shot["audio_events"])):
            if [item["order"] for item in collection] != list(range(1, len(collection)+1)):
                raise SplitReview("SHOT_AUDIO_ORDER_INVALID")
            for item in collection:
                projected,receipt=project_source_whitespace(owned_text,item['text'])
                if receipt:
                    deterministic_normalizations.append({'kind':'SOURCE_WHITESPACE_RESTORED','field':field,
                        'order':item['order'],'input_hash':digest(item['text']),'output_hash':digest(projected),
                        'source_start':start+receipt['local_start'],'source_end':start+receipt['local_end']})
                    item['text']=projected
                if item['text'] not in owned_text:raise SplitReview("SHOT_AUDIO_NOT_GROUNDED")
        if deterministic_normalizations and source_contract is not None:
            source_contract={**source_contract,'deterministic_normalizations':deterministic_normalizations}
        voices, audio = set(), []
        for event in shot["audio_events"]:
            owner, visible = event["voice_owner"], event["visible_speaker"]
            if event["type"] == "NARRATION":
                if owner != "旁白" or visible is not None or event["requires_visible_lipsync"]:
                    raise SplitReview("NARRATION_BINDING_INVALID")
            else:
                if owner not in allowed["characters"]:
                    raise SplitReview("VOICE_OWNER_OUTSIDE_CHAPTER")
                voices.add(owner)
                if event["type"] == "INNER_MONOLOGUE" and (visible is not None or event["requires_visible_lipsync"]):
                    raise SplitReview("INNER_MONOLOGUE_LIPSYNC_INVALID")
                if visible is not None and (visible != owner or visible not in shot["characters"]):
                    raise SplitReview("VISIBLE_SPEAKER_OUTSIDE_SHOT")
                if event["requires_visible_lipsync"] != (visible is not None):
                    raise SplitReview("VISIBLE_SPEAKER_LIPSYNC_INVALID")
            audio.append({**event, "voice_owner_character_id": allowed["characters"][owner]["assetId"] if owner != "旁白" else None,
                "visible_speaker_character_id": allowed["characters"][visible]["assetId"] if visible else None})
        if any(d["character_name"] not in allowed["characters"] for d in shot["dialogues"]):
            raise SplitReview("DIALOGUE_OWNER_OUTSIDE_CHAPTER")
        if [(d["character_name"], d["text"]) for d in shot["dialogues"]] != [(a["voice_owner"], a["text"]) for a in audio if a["type"] == "DIALOGUE"]:
            raise SplitReview("DIALOGUE_AUDIO_EVENT_MISMATCH")
        used["characters"].update(voices)
        bound["voice_characters"] = [deepcopy(allowed["characters"][name]) for name in sorted(voices)]
        all_dialogues.extend(d["text"] for d in shot["dialogues"])
        prepared.append({"shot": shot, "start": start, "end": end, "evidence":evidence, "ranges": ranges,
                         "source_contract":source_contract, "source_window_bindings":source_window_bindings,
                          "bindings": bound, "audio": audio,
                          "completion_disposition":shot.get('completion_disposition') or 'NORMAL'})
    if seen_cards!=set(expected_cards):raise SplitReview('CONTROLLED_DEGRADATION_CARD_SET_CHANGED')
    if ownership_v2:
        cursor=0
        for item in prepared:
            if content[cursor:item['start']].strip():
                raise SplitReview('SHOT_OWNERSHIP_GAP: '+json.dumps({
                    'start':cursor,'end':item['start'],'text':content[cursor:item['start']]
                },ensure_ascii=False))
            cursor=item['end']
        if content[cursor:].strip():
            raise SplitReview('SHOT_OWNERSHIP_GAP: '+json.dumps({
                'start':cursor,'end':len(content),'text':content[cursor:]
            },ensure_ascii=False))
    for kind in allowed:
        if len(data[kind]) != len(set(data[kind])) or set(data[kind]) != used[kind]:
            raise SplitReview(f"SHOT_SUMMARY_SCOPE_MISMATCH: {kind}")
    if not historical_structure:
        from app.services.narration_coverage import validate_coverage, error_message
        coverage_data=deepcopy(data)
        coverage_data['shots']=[deepcopy(item['shot']) for item in prepared]
        if ownership_v2:
            for candidate,item in zip(coverage_data['shots'],prepared):candidate['source_evidence']=deepcopy(item['evidence'])
        report=validate_coverage(coverage_data,basis)
        if report['status']!='PASS':raise SplitReview(error_message(report))
        for item,resolved in zip(prepared,report['resolved']):item['treatment_coverage']=resolved
        locked=basis.get('locked_shots')
        if locked is not None:
            if len(locked)!=len(data['shots']):raise SplitReview('REPAIR_SCOPE_VIOLATION: shot count')
            for previous,current in zip(locked,data['shots']):
                for field in ('id','description','video_description','characters','scene','props','duration','continuity_mode','dialogues'):
                    if previous[field]!=current[field]:raise SplitReview('REPAIR_SCOPE_VIOLATION: '+field)
                if ownership_v2:
                    if ownership_source(content,previous) != ownership_source(content,current):
                        raise SplitReview('REPAIR_SCOPE_VIOLATION: source contract')
                elif locate_ranges(content,previous['source_evidence'])!=locate_ranges(content,current['source_evidence']):
                    raise SplitReview('REPAIR_SCOPE_VIOLATION: source ranges')
    return prepared
