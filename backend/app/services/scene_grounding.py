"""Read-only Scene grounding audit; Chapter membership is not occurrence proof."""
import json
import re

from fastapi import HTTPException

from app.models.chapter_shot_split import ChapterShotSplitRun
from app.models.llm_log import LLMLog
from app.models.novel import Chapter
from app.models.task import Task
from app.schemas.chapter_shot_split import parse_output
from app.services.chapter_asset_parse_service import digest, source_hash
from app.services.chapter_scope import locate_ranges, ownership_source, run_version, source_window_version

DIRECT_LOCAL = "DIRECT_LOCAL"
CONTEXT_INFERRED = "CONTEXT_INFERRED"
SCENE_TRANSITION = "SCENE_TRANSITION"
SCENE_UNRESOLVED = "SCENE_UNRESOLVED"
VERSION = "scene-grounding-audit-v1"
TRANSITION_PATTERN = re.compile(
    r"同到|来到|到得|直至|入店|入帐|出城|出庄|回寨|回涿郡|投庄|投青州|投广宗|投颍川|"
    r"前去|星夜投|径赴|来见|引见|遂引军北行|行无二日|往救"
)


def membership_evidence(binding):
    """Representative Chapter membership witnesses, never an exhaustive occurrence ledger."""
    if "membershipEvidence" in binding:return binding["membershipEvidence"]
    if "sourceEvidence" in binding:return binding["sourceEvidence"]
    return binding.get("source_evidence") or []


def _occurrences(content, value):
    result=[];cursor=0
    while value:
        start=content.find(value,cursor)
        if start<0:break
        result.append((start,start+len(value)));cursor=start+1
    return result


def classify_plan(plan, basis, *, auto_eligible=True):
    content=basis["source"]["content"]
    bindings=basis["scope"]["scenes"]["bindings"]
    names=[row["name"] for row in bindings]
    evidence={row["name"]:membership_evidence(row) for row in bindings}
    rows=[];previous=None
    for shot in plan.get("shots") or []:
        if "source_ownership" in shot:
            source=ownership_source(content,shot)["ownership_range"]
        else:
            ranges=locate_ranges(content,shot["source_evidence"]);source={"start":ranges[0]["start"],
                "end":ranges[-1]["end"],"text":content[ranges[0]["start"]:ranges[-1]["end"]]}
        start,end=source["start"],source["end"]
        local=[]
        for name,quotes in evidence.items():
            for quote in quotes:
                text=quote.get("text") if isinstance(quote,dict) else None
                ranges=_occurrences(content,text) if text else []
                if len(ranges)==1 and start<=ranges[0][0] and ranges[0][1]<=end:
                    local.append({"scene":name,"text":text,"range":[ranges[0][0],ranges[0][1]]})
        supported={item["scene"] for item in local}
        mentioned={name for name in names if name in source["text"]}
        other=sorted((supported|mentioned)-{shot["scene"]})
        transition_cues=sorted(set(TRANSITION_PATTERN.findall(source["text"])))
        contiguous=bool(previous and previous["range"][1]<=start
            and not content[previous["range"][1]:start].strip())
        reason=None
        if other:
            classification,reason=SCENE_TRANSITION,"OTHER_SCENE_SIGNAL_IN_SPAN"
        elif shot["scene"] in supported:
            classification,reason=DIRECT_LOCAL,"UNIQUE_LOCAL_MEMBERSHIP_EVIDENCE"
        elif transition_cues:
            classification,reason=SCENE_TRANSITION,"EXPLICIT_TRANSITION_CUE"
        elif (contiguous and previous["classification"] in {DIRECT_LOCAL,CONTEXT_INFERRED}
                and previous["scene"]==shot["scene"]):
            classification,reason=CONTEXT_INFERRED,"ADJACENT_SAME_SCENE_CONTINUITY"
        elif contiguous and previous["classification"]==SCENE_TRANSITION and shot["scene"] in previous["possibleNextScenes"]:
            classification,reason=CONTEXT_INFERRED,"ADJACENT_TRANSITION_TARGET_CONTINUITY"
        else:
            classification,reason=SCENE_UNRESOLVED,"NO_LOCAL_PROOF_OR_SAFE_CONTINUITY"
        row={"shotIndex":shot["id"],"range":[start,end],"scene":shot["scene"],
            "classification":classification,"reason":reason,
            "autoAuthorized":bool(auto_eligible and classification==DIRECT_LOCAL),
            "membershipEvidence":local,"sceneNameMentions":sorted(mentioned),"otherSceneSignals":other,
            "transitionCues":transition_cues,"possibleNextScenes":other}
        rows.append(row);previous=row
    counts={key:sum(item["classification"]==key for item in rows)
        for key in (DIRECT_LOCAL,CONTEXT_INFERRED,SCENE_TRANSITION,SCENE_UNRESOLVED)}
    return {"version":VERSION,"bindingEvidenceSemantic":"CHAPTER_MEMBERSHIP_REPRESENTATIVE",
        "bindingEvidenceIsOccurrenceProof":False,"autoAuthorization":[DIRECT_LOCAL],
        "auditEligibleForAuthorization":bool(auto_eligible),
        "diagnosticOnly":[CONTEXT_INFERRED],"failClosed":[SCENE_TRANSITION,SCENE_UNRESOLVED],
        "transitionCueSemantic":"HEURISTIC_DIAGNOSTIC_NOT_OCCURRENCE_PROOF",
        "counts":{**counts,"HUMAN_REQUIRED":len(rows)-counts[DIRECT_LOCAL],"total":len(rows)},"shots":rows}


def classify_run(db, novel_id, chapter_id, run_id):
    run=db.query(ChapterShotSplitRun).filter_by(id=run_id,novel_id=novel_id,chapter_id=chapter_id).first()
    if not run:raise HTTPException(404,"分镜拆分记录不存在")
    task=db.get(Task,run.task_id)
    if run.inputs.get("auto_repair"):raise HTTPException(409,"SCENE_GROUNDING_REQUIRES_FULL_SHOT_PLAN")
    try:expected_version=run_version(run.inputs.get("source_contract_version"),run.version)
    except ValueError as exc:raise HTTPException(409,"SCENE_GROUNDING_RUN_VERSION_UNSUPPORTED") from exc
    if (run.version!=expected_version
            or run.inputs.get("source_window_version")!=source_window_version(run.version)):
        raise HTTPException(409,"SCENE_GROUNDING_RUN_VERSION_UNSUPPORTED")
    if digest(run.inputs)!=run.input_hash:raise HTTPException(409,"SHOT_SPLIT_INPUT_CHANGED")
    try:meta=json.loads(task.metadata_json or "{}") if task else {}
    except (TypeError,ValueError):meta={}
    if (run.status!="NEEDS_REVIEW" or not task or task.status!="failed" or task.type!="chapter_shot_split"
            or task.novel_id!=novel_id or task.chapter_id!=chapter_id or meta.get("execution_purpose")!="production"
            or meta.get("split_run_id")!=run.id or meta.get("input_hash")!=run.input_hash):
        raise HTTPException(409,"SCENE_GROUNDING_REJECTED_RUN_REQUIRED")
    log=db.get(LLMLog,run.call.get("llm_log_id")) if run.call.get("llm_log_id") else None
    if (not run.call.get("success") or not log or log.status!="success" or log.task_type!="split_chapter"
            or log.response!=run.call.get("response")
            or log.system_prompt!=run.inputs.get("system_prompt") or log.user_prompt!=run.inputs.get("user_prompt")
            or log.novel_id!=novel_id or log.chapter_id!=chapter_id):
        raise HTTPException(409,"SHOT_SPLIT_PROVENANCE_INVALID")
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
    current=bool(chapter and source_hash(chapter)==run.inputs["basis"]["source"]["hash"])
    try:
        plan=parse_output(log.response,run.inputs.get("source_contract_version"),run.inputs.get("source_window_version"))
        report=classify_plan(plan,run.inputs["basis"],auto_eligible=current)
    except (KeyError,TypeError,ValueError) as exc:
        raise HTTPException(409,"SCENE_GROUNDING_PLAN_INVALID: "+str(exc)) from exc
    report.update(splitRunId=run.id,splitRunStatus=run.status,sourceHash=run.inputs["basis"]["source"]["hash"],
        sourceCurrent=current)
    return report
