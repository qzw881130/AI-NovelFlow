"""R-AR1: one-shot, policy-bounded repair for deterministic Shot contract failures."""
from copy import deepcopy
import json
import re

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.novel import Novel
from app.repositories.prompt_template import PromptTemplateRepository
from app.schemas.chapter_shot_split import parse_repair_output
from app.services.chapter_asset_parse_service import digest


VERSION = "shot-contract-auto-repair-v1"
TEMPLATE_TYPE = "shot_contract_repair"
CLOSURE_REPAIR_TYPE = "SHOT_VISIBLE_CHARACTER_CLOSURE"
BOUNDARY_REPAIR_TYPE = "SHOT_CROSSES_APPEARANCE_BOUNDARY"
BUDGET = 1
SCENE_POLICY_VERSION = "source-span-aware-scene-v1"
CREATIVE_SCENE_POLICY_VERSION = "source-span-aware-scene-v2"
SAME_SCENE = "SAME_SCENE"
SOURCE_SPAN_AWARE_SCENE_CHANGE = "SOURCE_SPAN_AWARE_SCENE_CHANGE"
CREATIVE_COMPLETION = "CREATIVE_COMPLETION"
SCENE_UNRESOLVED = "SCENE_UNRESOLVED"


class AutoRepairReview(ValueError):
    def __init__(self, outcome, message, metadata):
        super().__init__(message)
        self.outcome = outcome
        self.metadata = metadata


def finding_key(finding):
    return digest({key: finding.get(key) for key in (
        "code", "shot_index", "field", "block", "declared_characters",
        "description_characters", "missing_characters", "unexpected_characters", "boundary", "evidence_range",
    )})


def classify(findings, validation_error):
    if not findings:return "HUMAN_REQUIRED"
    if str(validation_error).startswith(CLOSURE_REPAIR_TYPE + ":") and all(
        finding.get("code") == CLOSURE_REPAIR_TYPE
        and finding.get("field") == "description"
        and finding.get("missing_characters")
        and not finding.get("unexpected_characters")
        and not finding.get("duplicate_characters")
        for finding in findings
    ):return "AUTO_REPAIRABLE"
    if str(validation_error).startswith(BOUNDARY_REPAIR_TYPE + ":") and all(
        finding.get("code")==BOUNDARY_REPAIR_TYPE and type(finding.get("boundary")) is int
        and isinstance(finding.get("evidence_range"),list) and len(finding["evidence_range"])==2
        for finding in findings
    ):return "AUTO_REPAIRABLE"
    return "HUMAN_REQUIRED"


def _occurrences(content, text):
    result=[];cursor=0
    while text:
        start=content.find(text,cursor)
        if start<0:break
        result.append((start,start+len(text)));cursor=start+1
    return result


def _scene_support(basis,start,end):
    content=basis["source"]["content"];result=[]
    for binding in basis["scope"]["scenes"]["bindings"]:
        source_evidence=(binding["membershipEvidence"] if "membershipEvidence" in binding else
            binding["sourceEvidence"] if "sourceEvidence" in binding else binding.get("source_evidence") or [])
        matched=[]
        for quote in source_evidence:
            text=quote.get("text") if isinstance(quote,dict) else None
            ranges=_occurrences(content,text) if text else []
            if len(ranges)==1 and start<=ranges[0][0] and ranges[0][1]<=end:
                matched.append({"text":text,"start":ranges[0][0],"end":ranges[0][1]})
        if matched:result.append({"name":binding["name"],"evidence":matched})
    return result


def _scene_policy(basis,parent_scene,windows,version=None):
    if version is None:
        from app.services.chapter_scope import SCENE_BOUNDARY_RUN_VERSION
        version=(CREATIVE_SCENE_POLICY_VERSION if basis.get('version')==SCENE_BOUNDARY_RUN_VERSION
            else SCENE_POLICY_VERSION)
    states=[SAME_SCENE,SOURCE_SPAN_AWARE_SCENE_CHANGE,SCENE_UNRESOLVED]
    if version==CREATIVE_SCENE_POLICY_VERSION:states.insert(2,CREATIVE_COMPLETION)
    elif version!=SCENE_POLICY_VERSION:raise ValueError('SHOT_CONTRACT_REPAIR_SCENE_POLICY_VERSION_UNSUPPORTED')
    return {"version":version,"mode":"SOURCE_SPAN_AWARE","parent_scene":parent_scene,
        "allowed_scenes":[binding["name"] for binding in basis["scope"]["scenes"]["bindings"]],
        "states":states,
        "windows":[{"start":window["start"],"end":window["end"],
            "supported_scenes":_scene_support(basis,window["start"],window["end"])} for window in windows]}


def build_plan(findings,original_plan=None,basis=None,*,scene_aware=True,scene_policy_version=None):
    if classify(findings, findings[0].get("message") if findings else "") != "AUTO_REPAIRABLE":
        raise ValueError("SHOT_CONTRACT_REPAIR_NOT_ELIGIBLE")
    repair_type=findings[0]["code"];targets=[]
    if repair_type==CLOSURE_REPAIR_TYPE:
        for finding in findings:
            targets.append({"shot_index":finding["shot_index"],"field":finding["field"],
                "declared_characters":finding["declared_characters"],
                "described_characters":finding["description_characters"],
                "missing_characters":finding["missing_characters"],
                "required_operation":"ADD_MISSING_CHARACTER_VISUAL_LINES"})
    else:
        if not original_plan or not basis:raise ValueError("SHOT_CONTRACT_REPAIR_CONTEXT_REQUIRED")
        content=basis["source"]["content"]
        for shot_index in sorted({item["shot_index"] for item in findings}):
            group=[item for item in findings if item["shot_index"]==shot_index]
            ranges={tuple(item["evidence_range"]) for item in group}
            if len(ranges)!=1 or not 1<=shot_index<=len(original_plan["shots"]):
                raise ValueError("SHOT_CONTRACT_REPAIR_BOUNDARY_AMBIGUOUS")
            start,end=next(iter(ranges));boundaries=sorted({item["boundary"] for item in group})
            points=[start,*boundaries,end]
            original_shot=deepcopy(original_plan["shots"][shot_index-1])
            windows=[{"start":left,"end":right,"text":content[left:right]} for left,right in zip(points,points[1:])]
            target={"shot_index":shot_index,"original_shot":original_shot,
                "source_range":[start,end],"hard_boundaries":[{"offset":offset,
                    "affected_characters":[item["character"] for item in group if item["boundary"]==offset],
                    "before":[item["before"] for item in group if item["boundary"]==offset],
                    "after":[item["after"] for item in group if item["boundary"]==offset]} for offset in boundaries],
                "required_windows":windows,"required_operation":"REPLACE_SHOT_WITH_BOUNDARY_SAFE_SHOTS"}
            if scene_aware:target["scene_policy"]=_scene_policy(
                basis,original_shot["scene"],windows,scene_policy_version)
            targets.append(target)
    creative_scene_policy=any((target.get('scene_policy') or {}).get('version')==CREATIVE_SCENE_POLICY_VERSION
        for target in targets)
    preserve=(["story","existing_character_lines","scene","action","camera","source_contract",
        "source_evidence","duration","audio","treatments","declared_characters","all_non_target_shots"]
        if repair_type==CLOSURE_REPAIR_TYPE else
        ["story","exact_target_source_coverage","source_order","total_duration","visible_character_union",
         "prop_union",*([] if scene_aware else ["scene"]),
          *(["scene_policy_provenance"] if creative_scene_policy else
            ["source_grounded_scene_policy"] if scene_aware else []),"all_non_target_shots","all_non_target_fields"])
    forbidden=(["delete_declared_character","hide_character_to_evade_validation","add_character","change_story",
        "change_source","change_non_target_field"] if repair_type==CLOSURE_REPAIR_TYPE else
        ["omit_target_source","overlap_source","cross_hard_boundary","add_story","add_character_or_prop",
          "delete_original_visible_character",*(["change_scene"] if not scene_aware else
          ["unbound_scene",*(["scene_contradicts_explicit_source"] if creative_scene_policy else
            ["ungrounded_scene_change"]),"cross_chapter_scene_fallback"]),
         "change_total_duration","change_non_target_shot"])
    return {
        "version": VERSION,
        "repair_type": repair_type,
        "attempt": 1,
        "budget": BUDGET,
        "targets": targets,
        "preserve":preserve,
        "forbidden":forbidden,
    }


def resolve_template(db, novel_id):
    novel = db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    repo = PromptTemplateRepository(db)
    configured = novel.shot_contract_repair_prompt_template_id
    template = repo.get_by_id(configured) if configured else repo.get_default_system_template(TEMPLATE_TYPE)
    if (not template or template.type != TEMPLATE_TYPE or not template.is_active
            or not isinstance(template.template, str) or not template.template.strip()):
        code = "SHOT_CONTRACT_REPAIR_TEMPLATE_INVALID" if configured else "SHOT_CONTRACT_REPAIR_TEMPLATE_REQUIRED"
        raise HTTPException(409, code)
    return {
        "id": template.id,
        "name": template.name,
        "type": template.type,
        "version": VERSION,
        "hash": digest(template.template),
        "text": template.template,
        "configured": bool(configured),
    }


def render_prompts(template, original_plan, repair_plan):
    payload = {
        "contract_version": VERSION,
        "original_shot_plan": original_plan,
        "repair_plan": repair_plan,
    }
    return template["text"], json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _insert_character_lines(description, additions):
    header = re.search(r"^[ \t]*Characters[ \t]*[:：][ \t]*", description, flags=re.M | re.I)
    if not header:
        raise ValueError("SHOT_CHARACTER_DESCRIPTION_FORMAT")
    action = re.search(r"^[ \t]*Action[ \t]*[:：]", description[header.end():], flags=re.M | re.I)
    if not action:
        raise ValueError("SHOT_CHARACTER_DESCRIPTION_FORMAT")
    position = header.end() + action.start()
    prefix, suffix = description[:position], description[position:]
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += "\n"
    lines = "".join(f"- {item['name']}: {item['visual_description']}\n" for item in additions)
    return prefix + lines + suffix


def _apply_closure_response(original_plan,repair_plan,parsed):
    expected={(item["shot_index"],item["field"]):item for item in repair_plan["targets"]}
    actual={(item["shot_index"],item["field"]):item for item in parsed["repairs"]}
    if len(actual)!=len(parsed["repairs"]) or set(actual)!=set(expected):
        raise ValueError("SHOT_CONTRACT_REPAIR_TARGETS_CHANGED")
    result=deepcopy(original_plan)
    for key,target in expected.items():
        repair=actual[key];expected_names=target["missing_characters"]
        actual_names=[item["name"] for item in repair["characters"]]
        if len(actual_names)!=len(set(actual_names)) or actual_names!=expected_names:
            raise ValueError("SHOT_CONTRACT_REPAIR_CHARACTERS_CHANGED")
        shot_index,field=key
        if shot_index<1 or shot_index>len(result["shots"]):raise ValueError("SHOT_CONTRACT_REPAIR_TARGET_MISSING")
        result["shots"][shot_index-1][field]=_insert_character_lines(
            result["shots"][shot_index-1][field],repair["characters"])
    return result


def _scene_decision(basis,target,item,left,right):
    policy=target["scene_policy"]
    expected=_scene_policy(basis,target["original_shot"]["scene"],target["required_windows"],policy.get('version'))
    if policy!=expected:raise ValueError("SHOT_CONTRACT_REPAIR_SCENE_POLICY_CHANGED")
    proposed=item["scene"];parent=policy["parent_scene"];allowed=set(policy["allowed_scenes"])
    support=_scene_support(basis,left,right);supported={row["name"] for row in support}
    span=basis['source']['content'][left:right]
    mentioned={binding['name'] for binding in basis['scope']['scenes']['bindings'] if binding['name'] in span}
    state=reason=None
    if proposed not in allowed:
        state,reason=SCENE_UNRESOLVED,"SCENE_OUTSIDE_CHAPTER_SCOPE"
    elif proposed==parent:
        if ((supported and supported!={parent}) or (policy['version']==CREATIVE_SCENE_POLICY_VERSION
                and mentioned and mentioned!={parent})):
            state,reason=SCENE_UNRESOLVED,"PARENT_SCENE_CONTRADICTED_BY_CHILD_SPAN"
        else:state,reason=SAME_SCENE,"PARENT_SUBSPAN_INHERITANCE"
    elif supported=={proposed} and (policy['version']!=CREATIVE_SCENE_POLICY_VERSION
            or not mentioned or mentioned=={proposed}):
        state,reason=SOURCE_SPAN_AWARE_SCENE_CHANGE,"UNIQUE_CHILD_SPAN_SCENE_EVIDENCE"
    elif supported or (policy['version']==CREATIVE_SCENE_POLICY_VERSION and mentioned):
        state,reason=SCENE_UNRESOLVED,("SCENE_SIGNAL_REQUIRES_DIRECT_GROUNDING"
            if policy['version']==CREATIVE_SCENE_POLICY_VERSION else "NO_UNIQUE_CHILD_SPAN_SCENE_SUPPORT")
    elif policy["version"]==CREATIVE_SCENE_POLICY_VERSION:
        state,reason=CREATIVE_COMPLETION,"SOURCE_SILENT_CREATIVE_COMPLETION"
    else:
        state,reason=SCENE_UNRESOLVED,"NO_UNIQUE_CHILD_SPAN_SCENE_SUPPORT"
    binding=next((row for row in basis["scope"]["scenes"]["bindings"] if row["name"]==proposed),None)
    result={"version":policy["version"],"replacementId":item["id"],"sourceRange":[left,right],
        "parentScene":parent,"proposedScene":proposed,"state":state,"reason":reason,
        "sceneAssetId":binding.get("assetId") if binding and state!=SCENE_UNRESOLVED else None,
        "supportedScenes":support}
    if policy['version']==CREATIVE_SCENE_POLICY_VERSION:
        result['grounding']=("CREATIVE_COMPLETION" if state==CREATIVE_COMPLETION else
            "SOURCE_EXPLICIT" if state==SOURCE_SPAN_AWARE_SCENE_CHANGE else
            "SOURCE_CONSTRAINED" if state==SAME_SCENE else "SOURCE_UNRESOLVED")
        result['sceneNameMentions']=sorted(mentioned)
    return result


def _scene_summary(original,shots):
    used=[]
    for shot in shots:
        if shot["scene"] not in used:used.append(shot["scene"])
    return [name for name in original if name in used]+[name for name in used if name not in original]


def _apply_boundary_response(original_plan,repair_plan,parsed,basis,scene_decisions=None):
    if not basis:raise ValueError("SHOT_CONTRACT_REPAIR_CONTEXT_REQUIRED")
    from app.services.chapter_scope import ownership_source
    content=basis["source"]["content"];expected={item["shot_index"]:item for item in repair_plan["targets"]}
    actual={item["shot_index"]:item for item in parsed["repairs"]}
    if len(actual)!=len(parsed["repairs"]) or set(actual)!=set(expected):
        raise ValueError("SHOT_CONTRACT_REPAIR_TARGETS_CHANGED")
    replacements={}
    for shot_index,target in expected.items():
        rows=deepcopy(actual[shot_index]["replacements"]);old=original_plan["shots"][shot_index-1]
        if [item["id"] for item in rows]!=list(range(1,len(rows)+1)):
            raise ValueError("SHOT_CONTRACT_REPAIR_REPLACEMENT_ORDER_INVALID")
        located=[]
        for item in rows:
            source=ownership_source(content,item)["ownership_range"]
            located.append((source["start"],source["end"],item))
        if any(located[index][0]<located[index-1][1] for index in range(1,len(located))):
            raise ValueError("SHOT_CONTRACT_REPAIR_SOURCE_OVERLAP")
        start,end=target["source_range"];cursor=start
        for left,right,_ in located:
            if left<cursor or content[cursor:left].strip():raise ValueError("SHOT_CONTRACT_REPAIR_SOURCE_GAP")
            cursor=right
        if cursor>end or content[cursor:end].strip() or located[0][0]<start or located[-1][1]>end:
            raise ValueError("SHOT_CONTRACT_REPAIR_SOURCE_SCOPE_CHANGED")
        windows=target["required_windows"]
        if any(not any(window["start"]<=left and right<=window["end"] for window in windows) for left,right,_ in located):
            raise ValueError("SHOT_CONTRACT_REPAIR_BOUNDARY_STILL_CROSSED")
        if any(not any(window["start"]<=left and right<=window["end"] for left,right,_ in located) for window in windows):
            raise ValueError("SHOT_CONTRACT_REPAIR_WINDOW_NOT_COVERED")
        if set().union(*(set(item["characters"]) for _,_,item in located))!=set(old["characters"]):
            raise ValueError("SHOT_CONTRACT_REPAIR_VISIBLE_CHARACTERS_REMOVED")
        if set().union(*(set(item["props"]) for _,_,item in located))!=set(old["props"]):
            raise ValueError("SHOT_CONTRACT_REPAIR_PROPS_CHANGED")
        if target.get("scene_policy"):
            for left,right,item in located:
                decision=_scene_decision(basis,target,item,left,right)
                if scene_decisions is not None:scene_decisions.append(decision)
                if decision["state"]==SCENE_UNRESOLVED:
                    raise ValueError("SHOT_CONTRACT_REPAIR_SCENE_UNRESOLVED: "+json.dumps(decision,ensure_ascii=False))
        elif {item["scene"] for _,_,item in located}!={old["scene"]}:
            raise ValueError("SHOT_CONTRACT_REPAIR_SCENE_CHANGED")
        if sum(item["duration"] for _,_,item in located)!=old["duration"]:
            raise ValueError("SHOT_CONTRACT_REPAIR_DURATION_CHANGED")
        replacements[shot_index]=[item for _,_,item in located]
    result=deepcopy(original_plan);shots=[]
    for old in result["shots"]:
        shots.extend(replacements.get(old["id"],[old]))
    for index,item in enumerate(shots,1):item["id"]=index
    result["shots"]=shots
    if any(target.get("scene_policy") for target in repair_plan["targets"]):
        result["scenes"]=_scene_summary(result["scenes"],shots)
    return result


def apply_response(original_plan, repair_plan, raw_response, basis=None, scene_decisions=None):
    try:
        parsed = parse_repair_output(raw_response)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ValueError(f"SHOT_CONTRACT_REPAIR_OUTPUT_INVALID: {exc}") from exc
    if parsed["repair_type"] != repair_plan["repair_type"]:
        raise ValueError("SHOT_CONTRACT_REPAIR_TYPE_CHANGED")
    if repair_plan["repair_type"]==CLOSURE_REPAIR_TYPE:
        return _apply_closure_response(original_plan,repair_plan,parsed)
    if repair_plan["repair_type"]==BOUNDARY_REPAIR_TYPE:
        return _apply_boundary_response(original_plan,repair_plan,parsed,basis,scene_decisions)
    raise ValueError("SHOT_CONTRACT_REPAIR_TYPE_UNSUPPORTED")


def delta(before_plan, after_plan, before_findings, after_findings, *, repair_type, outcome, validator_error=None,
          scene_decisions=None):
    before_keys = {finding_key(item) for item in before_findings}
    after_keys = {finding_key(item) for item in after_findings}
    result={
        "version": VERSION,
        "repairType": repair_type,
        "attempt": 1,
        "budget": BUDGET,
        "beforeHash": digest(before_plan),
        "afterHash": digest(after_plan),
        "changed": digest(before_plan) != digest(after_plan),
        "violationsBefore": len(before_findings),
        "violationsAfter": len(after_findings),
        "resolved": len(before_keys - after_keys),
        "introduced": len(after_keys - before_keys),
        "outcome": outcome,
        "validatorError": validator_error,
    }
    if scene_decisions is not None:result["sceneDecisions"]=deepcopy(scene_decisions)
    return result
