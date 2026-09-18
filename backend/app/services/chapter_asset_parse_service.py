"""Phase 1 extraction: one chapter snapshot, strict candidates, no global asset writes."""
import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, and_

from app.models.chapter_asset_parse import ChapterAssetParseRun as Run, ChapterAssetCandidate as Candidate
from app.models.novel import Chapter, Novel
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.repositories.prompt_template import PromptTemplateRepository
from app.schemas.chapter_asset_parse import validate_output, ParseChapterAssetsRequest
from app.services.llm_service import LLMService

PARSER_VERSION = "chapter-assets-v1.0.2"
TASK_TYPE = "chapter_asset_parse"
REQUEST_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "prompt_templates" / "chapter_asset_parse_request.json"
REPAIR_TEMPLATE_PATH = REQUEST_TEMPLATE_PATH.with_name("chapter_asset_parse_repair.json")
TEMPLATES = {
    "characters": ("character_parse_prompt_template_id", "character_parse", "V3.1.2"),
    "scenes": ("scene_parse_prompt_template_id", "scene_parse", "source-evidence-v1"),
    "props": ("prop_parse_prompt_template_id", "prop_parse", "source-evidence-v1"),
}


def digest(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_hash(chapter):
    return digest([chapter.number, chapter.title, chapter.content or ""])


class ParseFailure(Exception):
    def __init__(self, code, message, issues=None):
        super().__init__(message)
        self.code, self.issues = code, issues or []


def load_request_template():
    try:
        raw = REQUEST_TEMPLATE_PATH.read_text(encoding="utf-8")
        definition = json.loads(raw)
        required = ("version", "range_placeholder", "range_template", "user_template", "common_instructions")
        if not isinstance(definition, dict) or any(not isinstance(definition.get(key), str) or not definition[key].strip() for key in required):
            raise ValueError("missing request template fields")
        by_kind = definition.get("instructions_by_kind")
        if not isinstance(by_kind, dict) or any(not isinstance(by_kind.get(kind), str) for kind in TEMPLATES):
            raise ValueError("invalid instructions_by_kind")
        return {"file": f"prompt_templates/{REQUEST_TEMPLATE_PATH.name}", "version": definition["version"],
                "hash": digest(raw), "definition": definition}
    except (OSError, ValueError) as exc:
        raise ParseFailure("REQUEST_TEMPLATE_INVALID", f"请求模板读取或校验失败：{exc}") from exc


def load_repair_template():
    try:
        raw = REPAIR_TEMPLATE_PATH.read_text(encoding="utf-8")
        definition = json.loads(raw)
        if not isinstance(definition, dict) or any(not isinstance(definition.get(key), str) or not definition[key].strip()
                for key in ("version", "system_suffix", "user_template")):
            raise ValueError("missing repair template fields")
        return {"file": f"prompt_templates/{REPAIR_TEMPLATE_PATH.name}", "version": definition["version"],
                "hash": digest(raw), "definition": definition}
    except (OSError, ValueError) as exc:
        raise ParseFailure("REPAIR_TEMPLATE_INVALID", f"修复模板读取或校验失败：{exc}") from exc


def render_request(template, kind, chapter_id, number, title, content, system_template, repair=None):
    definition = template["definition"]
    values = {"chapter_id": chapter_id, "chapter_number": number, "chapter_title": title,
              "chapter_content": content,
              "instructions": definition["common_instructions"] + definition["instructions_by_kind"][kind]}
    try:
        source_range = definition["range_template"].format_map(values)
        user_prompt = definition["user_template"].format_map(values)
    except (KeyError, ValueError, IndexError, AttributeError) as exc:
        raise ParseFailure("REQUEST_TEMPLATE_INVALID", f"请求模板变量无效：{exc}") from exc
    system_prompt = system_template.replace(definition["range_placeholder"], source_range)
    if repair is not None:
        current = load_repair_template()
        if repair["template"] != current:
            raise ParseFailure("REPAIR_TEMPLATE_CHANGED", "修复模板与本次冻结版本不一致")
        system_prompt += "\n" + current["definition"]["system_suffix"]
        try:
            user_prompt += current["definition"]["user_template"].format_map({
                "payload": json.dumps(repair["previous_rejected_attempt"], ensure_ascii=False)})
        except (KeyError, ValueError, IndexError, AttributeError) as exc:
            raise ParseFailure("REPAIR_TEMPLATE_INVALID", f"修复模板变量无效：{exc}") from exc
    return system_prompt, user_prompt


def request_template_current(run):
    """Compare frozen inputs to current file rendering, without rewriting historical evidence."""
    try:
        template = load_request_template()
        for call in run.calls:
            system_prompt, user_prompt = render_request(template, call["assetType"], run.chapter_id,
                run.source_number, run.source_title, run.source_content, call["template"]["text"], call.get("repair"))
            if system_prompt != call["systemPrompt"] or user_prompt != call["userPrompt"]:
                return False
        return True
    except (ParseFailure, KeyError, TypeError):
        return False


def fail_run(db, run_id, code, message, issues=None):
    run = db.get(Run, run_id)
    if not run:
        return False
    task_id = run.task_id
    updated = db.query(Run).filter(Run.id == run_id, Run.status == "RUNNING").update({
        "status": "FAILED", "completed_at": datetime.utcnow(),
        "issues": [{"code": code, "message": message, "details": issues or []}],
    }, synchronize_session=False)
    if updated:
        db.query(Task).filter(Task.id == task_id, Task.status.in_(["pending", "running"])).update({
            "status": "failed", "error_message": f"{code}: {message}",
            "current_step": "章回素材解析失败", "completed_at": datetime.utcnow(),
        }, synchronize_session=False)
        db.commit()
    db.expire_all()
    return bool(updated)


def expire_run_for_task(db, task):
    run = db.query(Run).filter(Run.task_id == task.id, Run.status == "RUNNING").first()
    if run and run.expires_at < datetime.utcnow():
        return fail_run(db, run.id, "PARSE_INTERRUPTED_OR_EXPIRED", "解析超过本次调用期限，请从章回重新发起")
    return False


def run_response(db, run, detail=True):
    chapter = db.get(Chapter, run.chapter_id)
    current = bool(chapter and chapter.novel_id == run.novel_id and source_hash(chapter) == run.source_hash)
    task = db.get(Task, run.task_id)
    newer = db.query(Run).filter(Run.chapter_id == run.chapter_id, or_(
        Run.created_at > run.created_at, and_(Run.created_at == run.created_at, Run.id > run.id))).all()
    superseded = sorted(set(run.kinds).intersection(kind for other in newer for kind in other.kinds))
    request_current = request_template_current(run)
    effective = run.status
    if not current:
        effective = "STALE"
    elif run.parser_version != PARSER_VERSION:
        effective = "PARSER_OUTDATED"
    elif superseded:
        effective = "SUPERSEDED"
    elif run.status == "SUCCEEDED" and not request_current:
        effective = "PARSER_OUTDATED"
    elif run.status == "RUNNING" and (not task or task.status not in {"pending", "running"}):
        effective = "INTERRUPTED"
    elif run.status == "RUNNING" and run.expires_at < datetime.utcnow():
        effective = "EXPIRED"
    result = {
        "id": run.id, "novelId": run.novel_id, "chapterId": run.chapter_id, "taskId": run.task_id,
        "parserVersion": run.parser_version, "kinds": run.kinds, "status": run.status,
        "effectiveStatus": effective, "sourceHash": run.source_hash, "sourceCurrent": current,
        "phase1Ready": effective == "SUCCEEDED", "publishedToBook": False,
        "supersededKinds": superseded,
        "requestTemplateCurrent": request_current,
        "nextStage": "EXISTING_ASSET_RESOLUTION", "issues": run.issues,
        "createdAt": run.created_at.isoformat() + "Z",
        "completedAt": run.completed_at.isoformat() + "Z" if run.completed_at else None,
        "candidateCount": db.query(Candidate).filter(Candidate.run_id == run.id).count(),
    }
    if detail:
        result.update(
            source={"title": run.source_title, "number": run.source_number, "content": run.source_content},
            calls=run.calls,
            candidates=[{"id": row.id, "assetType": row.asset_type, "validationStatus": row.validation_status,
                         "issues": row.issues, **row.payload}
                        for row in db.query(Candidate).filter(Candidate.run_id == run.id).order_by(Candidate.asset_type, Candidate.name)],
        )
    return result


class ChapterAssetParseService:
    def __init__(self, db, llm=None):
        self.db = db
        self.llm = llm

    def _template(self, novel, kind):
        attr, template_type, version = TEMPLATES[kind]
        repo = PromptTemplateRepository(self.db)
        configured = getattr(novel, attr)
        template = repo.get_by_id(configured) if configured else repo.get_default_system_template(template_type)
        if not template or template.type != template_type or not template.is_active or not template.template.strip():
            raise ParseFailure("PARSER_TEMPLATE_UNAVAILABLE", f"{kind}解析模板不存在、未启用或类型错误")
        if "source_evidence" not in template.template or (kind == "characters" and "V3.1.2" not in template.template):
            raise ParseFailure("PARSER_TEMPLATE_INCOMPATIBLE", f"{kind}仍选择旧版模板，请在小说设置选择当前系统解析模板")
        return {"id": template.id, "name": template.name, "type": template.type,
                "contractVersion": version, "hash": digest(template.template), "text": template.template}

    def _previous_repair(self, chapter_id, source, kind, current_run_id):
        runs = self.db.query(Run).filter(Run.chapter_id == chapter_id, Run.id != current_run_id).order_by(
            Run.created_at.desc(), Run.id.desc()).all()
        previous = next((run for run in runs if kind in run.kinds), None)
        if (not previous or previous.status != "NEEDS_REVIEW" or previous.source_hash != source
                or previous.parser_version != PARSER_VERSION or not request_template_current(previous)):
            return None
        task = self.db.get(Task, previous.task_id)
        calls = [call for call in previous.calls if call.get("assetType") == kind]
        if (not task or task.status != "completed" or task.type != TASK_TYPE or task.novel_id != previous.novel_id
                or task.chapter_id != chapter_id or len(calls) != 1):
            return None
        call = calls[0]
        log = self.db.get(LLMLog, call.get("llmLogId")) if call.get("llmLogId") else None
        if (not log or log.status != "success" or log.novel_id != previous.novel_id or log.chapter_id != chapter_id
                or log.task_type != f"parse_{kind}" or log.response != call.get("response")
                or log.system_prompt != call.get("systemPrompt") or log.user_prompt != call.get("userPrompt")):
            return None
        issues = [{"candidate_id": row.id, "name": row.name, "issues": row.issues}
                  for row in self.db.query(Candidate).filter_by(run_id=previous.id, asset_type=kind).order_by(Candidate.name)
                  if row.issues]
        if not issues:
            return None
        return {"template": load_repair_template(), "previous_rejected_attempt": {
            "run_id": previous.id, "llm_log_id": log.id, "source_hash": source, "asset_type": kind,
            "response": log.response, "issues": issues}}

    async def parse(self, novel_id, chapter_id, kinds=None):
        kinds = ParseChapterAssetsRequest(kinds=kinds if kinds is not None else ["characters", "scenes", "props"]).kinds
        db = self.db
        from app.services.rebuild_context import stage_parent
        parent_task_id = stage_parent(db, chapter_id)
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()
        novel = db.get(Novel, novel_id)
        if not chapter or not novel:
            raise HTTPException(404, "小说或章回不存在")
        for active in db.query(Run).filter(Run.chapter_id == chapter_id, Run.status == "RUNNING").all():
            task = db.get(Task, active.task_id)
            if not task or task.status not in {"pending", "running"} or active.expires_at < datetime.utcnow():
                fail_run(db, active.id, "PARSE_INTERRUPTED_OR_EXPIRED", "上次解析已中断，请重新发起")
        llm = self.llm or LLMService()
        timeout = float(getattr(llm, "timeout", None) or 1800)
        run_id, task_id = str(uuid4()), str(uuid4())
        captured = (chapter.number, chapter.title, chapter.content or "")
        run = Run(id=run_id, novel_id=novel_id, chapter_id=chapter_id, task_id=task_id,
                  parser_version=PARSER_VERSION, kinds=kinds, status="RUNNING", source_number=captured[0],
                  source_title=captured[1], source_content=captured[2], source_hash=digest(list(captured)),
                  calls=[], issues=[], expires_at=datetime.utcnow() + timedelta(seconds=timeout + 60))
        task = Task(id=task_id, novel_id=novel_id, chapter_id=chapter_id, type=TASK_TYPE, status="running", parent_task_id=parent_task_id,
                    name=f"章回素材解析 · 第{captured[0]}回", started_at=datetime.utcnow(),
                    current_step="校验解析模板", metadata_json=json.dumps({"execution_purpose": "production",
                        "parse_run_id": run_id, "parser_version": PARSER_VERSION, "source_hash": run.source_hash,
                        "kinds": kinds, "published_to_book": False}, ensure_ascii=False))
        db.add_all([run, task])
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "该章回已有解析任务，请等待完成后再试")
        calls, candidates = [], []
        try:
            if not captured[2].strip():
                raise ParseFailure("EMPTY_CHAPTER", "章回正文为空，不能作为成功空素材结果")
            templates = {kind: self._template(novel, kind) for kind in kinds}
            request_template = load_request_template()
            for kind in kinds:
                template = templates[kind]
                repair = self._previous_repair(chapter_id, digest(list(captured)), kind, run_id)
                system_prompt, user_prompt = render_request(request_template, kind, chapter_id,
                    captured[0], captured[1], captured[2], template["text"], repair)
                configured_tokens = getattr(llm, "max_tokens", None)
                max_tokens = configured_tokens if configured_tokens is not None else 32768
                normalize = getattr(llm, "_normalize_max_tokens", lambda value: value)
                call = {"assetType": kind, "template": template, "requestTemplate": request_template, "repair": repair, "systemPrompt": system_prompt,
                        "userPrompt": user_prompt, "provider": getattr(llm, "provider", None),
                        "model": getattr(llm, "model", None), "maxTokens": normalize(max_tokens),
                        "temperature": float(getattr(llm, "temperature", None) or 0.3),
                        "status": "RUNNING", "llmLogId": None, "response": None}
                calls.append(call)
                self._save_calls(run_id, task_id, calls, timeout, f"正在解析{kind}")
                response = await asyncio.wait_for(llm.chat_completion(
                    system_prompt=system_prompt, user_content=user_prompt, temperature=0.3, max_tokens=32768,
                    response_format="json_object", task_type=f"parse_{kind}",
                    prompt_template_name=f"{template['name']} [{template['contractVersion']}]",
                    novel_id=novel_id, chapter_id=chapter_id,
                ), timeout=timeout + 5)
                call.update(status="RETURNED" if response.get("success") else "FAILED",
                            llmLogId=response.get("llm_log_id"), response=response.get("content"),
                            failureKind=response.get("failure_kind"))
                self._save_calls(run_id, task_id, calls, timeout, f"校验{kind}候选")
                if not response.get("success"):
                    raise ParseFailure("LLM_REQUEST_FAILED", response.get("error") or "LLM调用失败")
                log = db.get(LLMLog, call["llmLogId"]) if call["llmLogId"] else None
                if (not log or log.novel_id != novel_id or log.chapter_id != chapter_id or log.status != "success"
                        or log.provider != call["provider"] or log.model != call["model"] or log.task_type != f"parse_{kind}"
                        or log.system_prompt != system_prompt or log.user_prompt != user_prompt or log.response != call["response"]):
                    raise ParseFailure("LLM_LOG_UNVERIFIED", "实际LLM日志缺失或与本次输入/输出不符")
                try:
                    payloads = validate_output(kind, call["response"])
                except (ValidationError, ValueError, TypeError) as exc:
                    details = exc.errors(include_input=False, include_context=False) if isinstance(exc, ValidationError) else [{"message": str(exc)}]
                    call.update(status="INVALID", validationIssues=details)
                    self._save_calls(run_id, task_id, calls, timeout, "候选结构校验失败")
                    raise ParseFailure("INVALID_CANDIDATE_OUTPUT", "LLM输出不符合候选契约", details)
                for payload in payloads:
                    issues = []
                    if kind == "characters":
                        if re.search(r"手持|手握|拿着|拄着|骑着|牵着", payload["appearance"]):
                            issues.append({"code": "BASE_APPEARANCE_PROP_ACTION", "field": "appearance",
                                           "message": "基础外观含持物/骑乘动作，请检查Prop边界"})
                        for change in payload["chapter_appearances"]:
                            if re.search(r"躺在|躺下|坐在|坐下|站在|跪在|跪下|跑向|走到|手持|拿着|骑着", change["appearance_description"] or ""):
                                issues.append({"code": "APPEARANCE_SHOT_STATE", "field": f"chapter_appearances.{change['event_key']}",
                                               "message": "换装说明含临时动作/位置，请检查后重新解析"})
                    evidence_sets = [("source_evidence", payload["source_evidence"])]
                    evidence_sets.extend((f"chapter_appearances.{event['event_key']}.source_evidence", event["source_evidence"])
                                         for event in payload.get("chapter_appearances", []))
                    for field, evidence in evidence_sets:
                        for quote in evidence:
                            if quote["text"] not in captured[2]:
                                issues.append({"code": "EVIDENCE_NOT_IN_SOURCE", "field": field, "text": quote["text"]})
                    candidates.append(Candidate(run_id=run_id, asset_type=kind, name=payload["name"],
                        entity_type=payload.get("entity_type"), group_size_hint=payload.get("group_size_hint"),
                        payload=payload, validation_status="NEEDS_REVIEW" if issues else "VALIDATED", issues=issues))
                call.update(status="VALIDATED", candidateCount=len(payloads), emptyConfirmed=not payloads)
                self._save_calls(run_id, task_id, calls, timeout, f"{kind}候选结构已校验")

            state = "NEEDS_REVIEW" if any(candidate.issues for candidate in candidates) else "SUCCEEDED"
            # Acquire the write fence before publishing any candidate. A changed source or cancelled task cannot publish.
            stage_parent(db, chapter_id)
            source_exists = db.query(Chapter.id).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id,
                Chapter.number == captured[0], Chapter.title == captured[1], Chapter.content == captured[2]).exists()
            task_exists = db.query(Task.id).filter(Task.id == task_id, Task.status == "running").exists()
            changed = db.query(Run).filter(Run.id == run_id, Run.status == "RUNNING", source_exists, task_exists).update({
                "status": state, "completed_at": datetime.utcnow(),
                "issues": [{"code": "CANDIDATE_REVIEW_REQUIRED", "message": "部分候选的原文依据或外观边界需检查后重新解析"}] if state == "NEEDS_REVIEW" else [],
            }, synchronize_session=False)
            if changed != 1:
                db.rollback()
                raise ParseFailure("SOURCE_OR_TASK_CHANGED", "原文或任务状态已变化，本次候选未发布")
            db.add_all(candidates)
            db.query(Task).filter(Task.id == task_id, Task.status == "running").update({
                "status": "completed", "progress": 100, "completed_at": datetime.utcnow(),
                "current_step": f"{len(candidates)}项候选，{'待检查证据' if state == 'NEEDS_REVIEW' else '等待Phase 2身份归并'}",
            }, synchronize_session=False)
            db.commit()
        except asyncio.CancelledError:
            db.rollback()
            fail_run(db, run_id, "PARSE_CANCELLED", "解析请求中断，未发布候选")
            raise
        except Exception as exc:
            db.rollback()
            fail_run(db, run_id, getattr(exc, "code", "PARSE_EXECUTION_FAILED"), str(exc), getattr(exc, "issues", None))
        db.expire_all()
        result = run_response(db, db.get(Run, run_id))
        return {"success": result["phase1Ready"], "data": result,
                "message": "候选已持久化，等待Phase 2身份归并" if result["phase1Ready"] else f"解析未通过：{result['effectiveStatus']}"}

    def _save_calls(self, run_id, task_id, calls, timeout, step):
        copied_calls = json.loads(json.dumps(calls, ensure_ascii=False, allow_nan=False))
        changed = self.db.query(Run).filter(Run.id == run_id, Run.status == "RUNNING").update({
            "calls": copied_calls, "expires_at": datetime.utcnow() + timedelta(seconds=timeout + 60),
        }, synchronize_session=False)
        if changed != 1:
            self.db.rollback()
            raise ParseFailure("PARSE_RUN_FENCED", "解析已终止，不再接受新输出")
        self.db.query(Task).filter(Task.id == task_id, Task.status == "running").update({
            "current_step": step, "prompt_text": calls[-1]["systemPrompt"],
        }, synchronize_session=False)
        self.db.commit()

    async def parse_chapters(self, novel_id, chapters, kinds):
        results = []
        for chapter in chapters:
            response = await self.parse(novel_id, chapter.id, kinds)
            results.append(response["data"])
        ready = bool(results) and all(result["phase1Ready"] for result in results)
        return {"success": ready, "data": results, "statistics": {
            "candidates": sum(result["candidateCount"] for result in results), "chapters": len(results),
        }, "message": "章回候选已保存，请在章回页面查看；尚未发布到全局资产库"}
