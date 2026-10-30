"""Grid-mode production path. Legacy Shot image and Phase B services are untouched."""

import asyncio
import io
import hashlib
import json
import random
import secrets
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy.orm import Session

from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.system_config import SystemConfig
from app.models.workflow import Workflow
from app.repositories.workflow import WorkflowRepository
from app.schemas.grid_shot import GridPanel, GridShotData, dump_grid_data, dump_grid_clip_plan, load_grid_data, read_grid_clip_plan
from app.services.comfyui import ComfyUIService
from app.services.background_workers import ensure_task_active, resume_image_prompt, save_image_prompt
from app.services.file_storage import file_storage
from app.services.first_appearance_nameplates import (
    _extract_frame as extract_review_frame,
    _probe_video as probe_nameplate_video,
    build_nameplate_events,
    render_first_appearance_nameplates,
)
from app.services.grid_h3_prompt import enforce_grid_no_voice, normalize_grid_dialogue_markers, validate_grid_h3_prompt
from app.services.grid_storage import grid_asset_path, record_grid_task_inputs, save_grid_png
from app.services.llm_service import LLMService
from app.services.novel_prompt_templates import resolve_novel_prompt_template
from app.services.vision_inputs import vision_proxy
from app.utils.json_parser import safe_parse_llm_json
from app.utils.image_utils import merge_character_images
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.workflow_disconnect import disconnect_reference_chain


class GridPipelineError(ValueError):
    pass


class GridVisualReviewError(GridPipelineError):
    def __init__(self, message: str, *, category: str, result: dict | None = None):
        super().__init__(message)
        self.category = category
        self.result = result or {}


def _panel_generation_size(width: int, height: int) -> tuple[int, int]:
    # The image API rejects outputs below 655,360 pixels. Keep stored panels at
    # their grid size, but generate small 16:9 panels at a supported resolution.
    return (1280, 720) if width * height < 655_360 else (width, height)


def _json(raw, fallback):
    try:
        value = json.loads(raw or "")
        return value if isinstance(value, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _template(db: Session, novel: Novel, kind: str):
    template = resolve_novel_prompt_template(db, novel, kind)
    if not template:
        raise GridPipelineError(f"未配置 {kind} 提示词模板")
    return template


def _dialogues(shot: Shot) -> list[dict]:
    rows = _json(shot.dialogues, [])
    cast = _json(shot.characters, [])
    dialogues = []
    preceding_subjects = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        speaker = str(row.get("speaker") or row.get("character_name") or "")
        text = str(row.get("text") or "")
        delivery = row.get("delivery") or "onscreen"
        subjects = row.get("visual_subjects") or []
        if speaker == "旁白" and delivery == "offscreen":
            named = [name for name in cast if name in text]
            if not named and text.startswith(("他", "她")) and len(preceding_subjects) == 1:
                named = preceding_subjects.copy()
            elif "他的" in text and len(preceding_subjects) == 1 and preceding_subjects[0] not in named:
                named.append(preceding_subjects[0])
            if named:
                delivery, subjects = "narration", named
        if speaker == "旁白" and subjects:
            preceding_subjects = subjects
        elif speaker != "旁白":
            preceding_subjects = []
        dialogues.append({"id": f"D{i}", "speaker": speaker, "text": text,
                          "delivery": delivery, "voice_description": row.get("voice_description") or "",
                          "visual_subjects": subjects})
    return dialogues


def _required_narration_subjects(dialogue: dict, shot_characters: list[str]) -> list[str]:
    if dialogue.get("speaker") != "旁白" or dialogue.get("delivery") != "narration":
        return []
    return [name for name in dialogue.get("visual_subjects") or [] if name in shot_characters]


def _assert_narration_coverage(shot: Shot, data: GridShotData, panel_indexes: list[int],
                               dialogue_indexes: list[int]) -> None:
    dialogues = _dialogues(shot)
    visible = {name for number in panel_indexes for name in data.panels[number - 1].characters}
    for number in dialogue_indexes:
        if not 1 <= number <= len(dialogues):
            raise GridPipelineError("Clip 引用了不存在的台词")
        missing = set(_required_narration_subjects(dialogues[number - 1], _json(shot.characters, []))) - visible
        if missing:
            raise GridPipelineError(f"旁白 D{number} 描述的动作缺少可见人物：{', '.join(sorted(missing))}；请修订子格")


def _clip_dialogue_indexes(clip: dict) -> list[int]:
    return clip.get("dialogue_indexes") or [int(line["id"][1:]) for line in clip.get("dialogues", [])]


def _h3_bindings(data: GridShotData, clip: dict) -> tuple[dict, list[dict]]:
    """Keep unpictured voices separate from H3 visual Subjects."""
    names = list(dict.fromkeys(
        name for panel_index in clip["panel_indexes"]
        for name in data.panels[panel_index - 1].characters
    ))
    names.extend(name for name in dict.fromkeys(
        line["speaker"] for line in clip["dialogues"]
        if line.get("delivery") != "offscreen" and line["speaker"] != "旁白"
    ) if name not in names)
    subjects = {f"<Subject {i}>": name for i, name in enumerate(names, 1)}
    subject_for_name = {name: token for token, name in subjects.items()}
    voices = {}
    events = []
    for line in clip["dialogues"]:
        if line.get("delivery") == "offscreen":
            name = line["speaker"]
            description = str(line.get("voice_description") or "").strip()
            if not description:
                raise GridPipelineError(f"画外说话人“{name}”缺少英文声音描述")
            if name not in voices:
                voices[name] = f"Off-screen voice: {description}"
            label = voices[name]
        else:
            label = subject_for_name.get(line["speaker"], "<Narrator>")
        events.append({**line, "speaker": label})
    return subjects, events


def _panel_number(value) -> int:
    if isinstance(value, bool):
        raise GridPipelineError("格编号无效")
    try:
        return int(str(value).lstrip("D"))
    except (TypeError, ValueError) as exc:
        raise GridPipelineError("格编号无效") from exc


def _asset_refs(db: Session, novel: Novel, shot: Shot, *, separate_characters: bool = False) -> list[dict]:
    """Use only approved local asset images; never treat a sheet as a grid panel."""
    refs = []
    characters = []
    for name in _json(shot.characters, []):
        asset = db.query(Character).filter(Character.novel_id == novel.id, Character.name == name).first()
        path = url_to_local_path(asset.image_url) if asset and asset.image_url else None
        if path:
            characters.append((asset, name, path))
    if separate_characters and characters:
        # Keep the narrative anchor first, then the other speakers in dialogue
        # order. This placed the old man ahead of the non-speaking old woman in
        # Shot 7, avoiding the observed reverse-angle identity swap.
        anchor = characters[0][1]
        speaker_order = list(dict.fromkeys(line["speaker"] for line in _dialogues(shot)
                                          if line["speaker"] != "旁白"))
        ordered_names = [anchor] + [name for name in speaker_order if name != anchor]
        ordered_names += [name for _, name, _ in characters if name not in ordered_names]
        characters.sort(key=lambda item: ordered_names.index(item[1]))
        refs.extend({"role": "CHARACTER_IDENTITY", "name": name, "url": asset.image_url}
                    for asset, name, _ in characters)
    elif len(characters) == 1:
        _, name, _ = characters[0]
        refs.append({"role": "CHARACTER_IDENTITY", "name": name, "url": characters[0][0].image_url})
    elif characters:
        merged = merge_character_images(
            novel.id, shot.chapter_id, shot.index,
            [(name, path) for _, name, path in characters], file_storage,
            character_assets=[{"character_id": asset.id, "url": asset.image_url,
                               "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                              for asset, _, path in characters],
            preserve_order=True,
        )
        if not merged:
            raise GridPipelineError("多角色身份参考图合并失败")
        refs.append({"role": "CHARACTER_IDENTITY", "name": "、".join(name for _, name, _ in characters),
                     "url": local_path_to_url(merged)})
    if shot.scene:
        asset = db.query(Scene).filter(Scene.novel_id == novel.id, Scene.name == shot.scene).first()
        if asset and asset.image_url and url_to_local_path(asset.image_url):
            refs.append({"role": "SCENE", "name": shot.scene, "url": asset.image_url})
    props = _json(shot.props, [])
    if separate_characters:
        # Owned props directly prevent bag/staff swaps; the scene reference
        # already supplies architectural props such as the door.
        cast = [name for _, name, _ in characters]
        props.sort(key=lambda name: 0 if any(name.startswith(owner) for owner in cast) else 1)
        props = props[:2]
    for name in props:
        asset = db.query(Prop).filter(Prop.novel_id == novel.id, Prop.name == name).first()
        if asset and asset.image_url and url_to_local_path(asset.image_url):
            refs.append({"role": "PROP", "name": name, "url": asset.image_url})
    return refs


def _board_bindings(refs: list[dict], mapping: dict, graph: dict) -> list[tuple[str, dict]]:
    """Bind by the existing workflow's semantic slots, not graph enumeration order."""
    encoder = next((node for node in graph.values() if isinstance(node, dict) and
                    node.get("class_type") == "TextEncodeQwenImage21"), None)
    if encoder and refs and len(refs) <= 9:
        slot_ids = [str(mapping.get(key) or "") for key in (
            "character_reference_image_node_id", "scene_reference_image_node_id",
            "custom_reference_image_node_1")]
        if not all(node_id in graph and graph[node_id].get("class_type") == "LoadImage"
                   for node_id in slot_ids):
            raise GridPipelineError("Qwen 生图工作流的三张基础参考图节点未正确映射")
        inputs = encoder.setdefault("inputs", {})
        for key in list(inputs):
            if key.startswith("images.image_"):
                inputs.pop(key)
        result = []
        next_id = max(int(node_id) for node_id in graph if str(node_id).isdigit()) + 1
        for index, ref in enumerate(refs, 1):
            if index <= 3:
                node_id = slot_ids[index - 1]
            else:
                node_id = str(next_id)
                next_id += 1
                graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": ""},
                                  "_meta": {"title": f"Grid reference Picture {index}: {ref['name']}"}}
            inputs[f"images.image_{index}"] = [node_id, 0]
            result.append((node_id, ref))
        return result
    if encoder and len(refs) > 9:
        raise GridPipelineError("Qwen 宫格参考图超过 9 张；请减少角色或道具")
    result = []
    for role, key in (("CHARACTER_IDENTITY", "character_reference_image_node_id"),
                      ("SCENE", "scene_reference_image_node_id"),
                      ("PANEL_COMPOSITION", "custom_reference_image_node_1")):
        node_id = str(mapping.get(key) or "")
        ref = next((item for item in refs if item["role"] == role), None)
        if role == "PANEL_COMPOSITION" and ref is None:
            ref = next((item for item in refs if item["role"] == "PROP"), None)
        if ref and node_id in graph and graph[node_id].get("class_type") == "LoadImage":
            result.append((node_id, ref))
    return result


def _grid_asset_refs(db: Session, novel: Novel, shot: Shot, graph: dict) -> list[dict]:
    separate = any(isinstance(node, dict) and node.get("class_type") == "TextEncodeQwenImage21"
                   for node in graph.values())
    return _asset_refs(db, novel, shot, separate_characters=separate)


def _panel_asset_refs(refs: list[dict], panel: GridPanel) -> list[dict]:
    """Keep only visible identities and their owned props for a panel retry."""
    visible = set(panel.characters)
    cast = [ref["name"] for ref in refs if ref["role"] == "CHARACTER_IDENTITY"]
    filtered = []
    for ref in refs:
        if (ref["role"] == "CHARACTER_IDENTITY" and ref["name"] not in visible
                and "、" not in ref["name"]):
            continue
        owner = next((name for name in cast if ref["role"] == "PROP" and
                      ref["name"].startswith(name)), None)
        if owner and owner not in visible:
            continue
        filtered.append(ref)
    if panel.composition_reference_url and url_to_local_path(panel.composition_reference_url):
        filtered.append({"role": "PANEL_COMPOSITION", "name": f"原格 {panel.index} 场景构图",
                         "url": panel.composition_reference_url})
    return filtered


def _picture_roles(refs: list[dict]) -> str:
    if not refs:
        return ""
    cast = [ref["name"] for ref in refs if ref["role"] == "CHARACTER_IDENTITY"]
    lines = []
    for index, ref in enumerate(refs, 1):
        owner = next((name for name in cast if ref["role"] == "PROP" and
                      ref["name"].startswith(name)), None)
        suffix = f" Owned by {owner} only." if owner else ""
        lines.append(f"Picture {index}: {ref['role']} — {ref['name']}.{suffix}")
    return ("Reference image binding (each Picture is a separate input; preserve these identities and roles):\n"
            + "\n".join(lines) + "\nNever move a character-owned prop to another character.\n\n")


class GridPipeline:
    def __init__(self, db: Session, llm: LLMService | None = None):
        self.db = db
        self.llm = llm or LLMService()

    def _invalidate_shot_video(self, shot: Shot, chapter: Chapter | None = None) -> None:
        shot.video_url = None
        shot.video_status = "pending"
        parent = chapter or self.db.get(Chapter, shot.chapter_id)
        if parent:
            parent.final_video = None

    def _invalidate_panel_clips(self, shot: Shot, data: GridShotData, panel_index: int,
                                chapter: Chapter | None = None) -> None:
        """A corrected panel invalidates its consumers, not unrelated completed Clips."""
        plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=data.revision)
        if plan:
            for clip in plan["clip_plan"]:
                if panel_index in clip["panel_indexes"] or clip.get("reference_strategy") == "whole_board":
                    for key in ("prompt", "prompt_template_snapshot", "validation", "reference_images",
                                "video_url", "video_task_id"):
                        clip.pop(key, None)
            shot.video_director_plan = dump_grid_clip_plan(data, plan["clip_plan"])
        else:
            shot.video_director_plan = "{}"
        self._invalidate_shot_video(shot, chapter)

    def _active(self, task: Task | None) -> None:
        if task:
            ensure_task_active(self.db, task)

    def _complete(self, task: Task | None, result_url: str | None = None) -> None:
        if task:
            self._active(task)
            task.status, task.progress, task.current_step = "completed", 100, "已完成"
            task.result_url, task.completed_at = result_url, datetime.utcnow()

    def _failed(self, task: Task, exc: Exception) -> None:
        self.db.refresh(task, attribute_names=["status"])
        if task.status != "cancelled":
            task.status, task.error_message, task.current_step = "failed", str(exc), "执行失败"
            task.completed_at = datetime.utcnow()
            self.db.commit()

    async def _ask(self, novel: Novel, chapter: Chapter, shot: Shot | None, kind: str,
                   payload: dict, *, json_result: bool = True, image_refs: list[dict] | None = None):
        template = _template(self.db, novel, kind)
        payload = {**payload, "story_world_context": _json(novel.story_world_context, {}),
                   "novel_title": novel.title}
        result = await self.llm.chat_completion(
            system_prompt=template.template,
            user_content=json.dumps(payload, ensure_ascii=False),
            response_format="json_object" if json_result else None,
            task_type=kind, prompt_template_name=template.name,
            novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id if shot else None,
            max_tokens=7000,
            images=[vision_proxy(ref["url"], logical_id=f"Picture {i}", name=f"Picture {i}",
                                 reference_type=ref["role"], role=ref["role"])
                    for i, ref in enumerate(image_refs or [], 1)] or None,
        )
        if not result.get("success"):
            raise GridPipelineError(result.get("error") or f"{kind} 调用失败")
        content = result.get("content") or ""
        if not json_result:
            return content.strip(), template.template
        parsed = safe_parse_llm_json(content, default=None)
        if not isinstance(parsed, dict):
            raise GridPipelineError(f"{kind} 未返回 JSON 对象")
        return parsed, template.template

    async def plan_chapter(self, novel: Novel, chapter: Chapter, task: Task | None = None) -> list[Shot]:
        if self.db.query(Shot.id).filter(Shot.chapter_id == chapter.id).first():
            raise GridPipelineError("本章已有 Shot；为避免覆盖已生成素材，请先在界面检查现有结果")
        if not (chapter.content or "").strip():
            raise GridPipelineError("章节正文为空")
        resources = {
            "characters": [row.name for row in self.db.query(Character).filter(Character.novel_id == novel.id)],
            "scenes": [row.name for row in self.db.query(Scene).filter(Scene.novel_id == novel.id)],
            "props": [row.name for row in self.db.query(Prop).filter(Prop.novel_id == novel.id)],
        }
        result, _ = await self._ask(novel, chapter, None, "grid_shot_plan", {
            "operation": "chapter_shots", "chapter_title": chapter.title,
            "chapter_text": chapter.content, "approved_resources": resources,
        })
        rows = result.get("shots")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
            raise GridPipelineError("宫格叙事 Shot 数量无效")
        shots = []
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not (row.get("description") or "").strip():
                raise GridPipelineError(f"Shot {index} 缺少剧情描述")
            duration = int(row.get("duration") or 12)
            if not 4 <= duration <= 120:
                raise GridPipelineError(f"Shot {index} 时长超出范围")
            characters = row.get("characters") or []
            props = row.get("props") or []
            scene = row.get("scene") or ""
            if not isinstance(characters, list) or not set(characters) <= set(resources["characters"]):
                raise GridPipelineError(f"Shot {index} 引用了未知角色")
            if not isinstance(props, list) or not set(props) <= set(resources["props"]):
                raise GridPipelineError(f"Shot {index} 引用了未批准道具")
            if scene and scene not in resources["scenes"]:
                raise GridPipelineError(f"Shot {index} 引用了未批准场景")
            dialogues = row.get("dialogues") or []
            if not isinstance(dialogues, list):
                raise GridPipelineError(f"Shot {index} 台词格式无效")
            for line_index, line in enumerate(dialogues, 1):
                if not isinstance(line, dict) or not isinstance(line.get("text"), str) or not line["text"].strip():
                    raise GridPipelineError(f"Shot {index} 第 {line_index} 句台词为空或格式无效")
                speaker = line.get("speaker")
                if not isinstance(speaker, str) or not speaker.strip():
                    raise GridPipelineError(f"Shot {index} 第 {line_index} 句缺少说话人")
                delivery = line.get("delivery") or "onscreen"
                if speaker == "旁白":
                    delivery = "narration"
                    line["delivery"] = delivery
                if delivery not in {"onscreen", "offscreen", "narration"} or (delivery == "narration" and speaker != "旁白"):
                    raise GridPipelineError(f"Shot {index} 第 {line_index} 句声音类型无效")
                if delivery == "offscreen":
                    description = line.get("voice_description")
                    if not isinstance(description, str) or not description.strip() or any(
                        char in description for char in "()\r\n"
                    ):
                        raise GridPipelineError(f"Shot {index} 第 {line_index} 句画外声的英文声音描述无效")
                    continue
                if speaker != "旁白" and speaker not in resources["characters"]:
                    raise GridPipelineError(
                        f"Shot {index} 第 {line_index} 句说话人“{speaker}”不在已批准角色中；"
                        "若为画外人声，请标记 delivery=offscreen 并提供 voice_description"
                    )
                if speaker != "旁白" and speaker not in characters:
                    raise GridPipelineError(
                        f"Shot {index} 第 {line_index} 句说话人“{speaker}”未列入本 Shot 的 characters"
                    )
                visual_subjects = line.get("visual_subjects") or []
                if not isinstance(visual_subjects, list) or not set(visual_subjects) <= set(characters):
                    raise GridPipelineError(f"Shot {index} 第 {line_index} 句可见人物不在本 Shot 角色中")
            shot = Shot(chapter_id=chapter.id, index=index, description=f"{row.get('title') or f'Shot {index}'}｜{row['description']}",
                        duration=duration, characters=json.dumps(characters, ensure_ascii=False), scene=scene,
                        props=json.dumps(props, ensure_ascii=False), dialogues=json.dumps(dialogues, ensure_ascii=False))
            shots.append(shot)
        self.db.add_all(shots)
        self._complete(task)
        chapter.parsed_data = json.dumps({"mode": "grid", "chapter": chapter.title,
                                          "resources": resources}, ensure_ascii=False)
        self.db.commit()
        return shots

    async def plan_panels(self, novel: Novel, chapter: Chapter, shot: Shot, layout: str | None = None,
                          task: Task | None = None) -> GridShotData:
        existing = load_grid_data(shot.grid_data)
        if layout is None:
            layout = existing.layout if existing else random.choice(["2x2", "2x3"])
        if layout not in {"2x2", "2x3", "3x3"}:
            raise GridPipelineError("版式仅支持 2x2、2x3、实验性 3x3")
        rows, cols = map(int, layout.split("x"))
        panel_count = rows * cols
        dialogues = _dialogues(shot)
        result, _ = await self._ask(novel, chapter, shot, "grid_shot_plan", {
            "operation": "shot_panels", "chapter_text": chapter.content,
            "shot": {"description": shot.description, "duration": shot.duration,
                     "characters": _json(shot.characters, []), "scene": shot.scene, "props": _json(shot.props, []),
                     "dialogues": dialogues},
            "grid_rows": rows, "grid_columns": cols, "panel_count": panel_count,
            "shot_duration_seconds": shot.duration,
        })
        panel_rows = result.get("panels")
        if not isinstance(panel_rows, list) or len(panel_rows) != panel_count:
            raise GridPipelineError("LLM 返回的子格数量与版式不符")
        panels, assigned = [], []
        for index, row in enumerate(panel_rows, 1):
            if not isinstance(row, dict) or row.get("index") != index:
                raise GridPipelineError("子格编号必须从 1 连续递增")
            camera = row.get("camera") or {}
            if not isinstance(camera, dict):
                raise GridPipelineError("机位描述必须是对象")
            camera_text = "；".join(f"{key}: {value}" for key, value in camera.items() if value)
            raw_ids = row.get("dialogue_ids") or []
            # NO_VOICE is a silent marker, never a dialogue identifier.
            if raw_ids == ["NO_VOICE"]:
                raw_ids = []
            ids = [_panel_number(value) for value in raw_ids]
            visible = row.get("visible_characters") or []
            if not isinstance(visible, list) or not set(visible) <= set(_json(shot.characters, [])):
                raise GridPipelineError(f"子格 {index} 引用了未知角色")
            if visible and any(1 <= number <= len(dialogues) and
                               dialogues[number - 1]["delivery"] == "offscreen" for number in ids):
                raise GridPipelineError(f"子格 {index} 画外台词期间不得出现人物；请使用无人出镜的环境画面")
            required = {name for number in ids if 1 <= number <= len(dialogues)
                        for name in _required_narration_subjects(dialogues[number - 1], _json(shot.characters, []))}
            if not required <= set(visible):
                raise GridPipelineError(f"子格 {index} 旁白描述的可见动作缺少人物：{', '.join(sorted(required - set(visible)))}")
            assigned.extend(ids)
            panels.append(GridPanel(index=index, beat=row.get("story_beat") or "",
                                    camera=camera_text, action=row.get("action") or "",
                                    axis=str(camera.get("screen_direction") or ""),
                                    characters=visible, dialogue_indexes=ids))
        if assigned != list(range(1, len(dialogues) + 1)):
            raise GridPipelineError("逐格台词未按原顺序恰好分配一次")
        data = GridShotData(revision=(existing.revision + 1 if existing else 1), layout=layout,
                            seed=existing.seed if existing else secrets.randbelow(2**31 - 1) + 1,
                            panel_width=768, panel_height=432, panels=panels)
        raw_dialogues = _json(shot.dialogues, [])
        for number, dialogue in enumerate(dialogues):
            if (dialogue["speaker"] == "旁白" and dialogue["delivery"] == "narration"
                    and number < len(raw_dialogues) and raw_dialogues[number].get("delivery") == "offscreen"):
                raw_dialogues[number]["delivery"] = "narration"
                raw_dialogues[number]["visual_subjects"] = dialogue["visual_subjects"]
        shot.dialogues = json.dumps(raw_dialogues, ensure_ascii=False)
        shot.grid_data = dump_grid_data(data)
        shot.video_director_plan = "{}"
        if existing:
            self._invalidate_shot_video(shot, chapter)
            shot.video_task_id = None
        self._complete(task)
        self.db.commit()
        return data

    async def prepare_board(self, novel: Novel, chapter: Chapter, shot: Shot, task: Task | None = None) -> dict:
        data = self._grid(shot)
        for panel in data.panels:
            _assert_narration_coverage(shot, data, [panel.index], panel.dialogue_indexes)
        workflow = WorkflowRepository(self.db).get_active_by_type("shot")
        if not workflow:
            raise GridPipelineError("未配置激活的分镜生图工作流")
        mapping = _json(workflow.node_mapping, {})
        preview_graph = _json(workflow.workflow_json, {})
        refs = [ref for _, ref in _board_bindings(
            _grid_asset_refs(self.db, novel, shot, preview_graph), mapping, preview_graph)]
        prompt, template = await self._ask(novel, chapter, shot, "grid_image_prompt", {
            "shot": shot.description, "grid_rows": int(data.layout[0]), "grid_columns": int(data.layout[-1]),
            "panel_count": len(data.panels), "panel_width": data.panel_width,
            "panel_height": data.panel_height, "board_size": data.board_size,
            "panels": [p.model_dump(exclude_none=True) for p in data.panels],
            "reference_assets": refs,
        }, json_result=False, image_refs=refs)
        data.board_prompt = _picture_roles(refs) + prompt
        data.board_reference_images = refs
        shot.grid_data = dump_grid_data(data)
        self._complete(task)
        self.db.commit()
        return {"prompt": data.board_prompt, "referenceImages": refs, "boardSize": data.board_size,
                "templateSnapshot": template}

    @staticmethod
    def _grid(shot: Shot) -> GridShotData:
        data = load_grid_data(shot.grid_data)
        if not data:
            raise GridPipelineError("请先规划宫格子图")
        return data

    async def generate_board(self, novel: Novel, chapter: Chapter, shot: Shot,
                             task: Task | None = None) -> dict:
        data = self._grid(shot)
        for panel in data.panels:
            _assert_narration_coverage(shot, data, [panel.index], panel.dialogue_indexes)
        if not data.board_prompt:
            raise GridPipelineError("请先预览并保存整板生图提示词")
        workflow = (self.db.get(Workflow, task.workflow_id) if task and task.comfyui_prompt_id else
                    WorkflowRepository(self.db).get_active_by_type("shot"))
        if not workflow and not (task and task.comfyui_prompt_id):
            raise GridPipelineError("未配置激活的分镜生图工作流")
        comfy = ComfyUIService()
        width, height = data.board_size
        try:
            if task and task.comfyui_prompt_id:
                self._active(task)
                result = await resume_image_prompt(self.db, task, comfy)
            else:
                mapping = _json(workflow.node_mapping, {})
                graph = comfy.builder.build_shot_workflow(data.board_prompt, workflow.workflow_json, mapping,
                                                          seed=data.seed)
                for key, size in (("width_node_id", width), ("height_node_id", height)):
                    node_id = str(mapping.get(key) or "")
                    if node_id in graph:
                        inputs = graph[node_id].setdefault("inputs", {})
                        inputs["value" if "value" in inputs else key.split("_")[0]] = size
                for node in graph.values():
                    if not isinstance(node, dict):
                        continue
                    inputs = node.get("inputs") or {}
                    if node.get("class_type") == "ResolutionSelector":
                        inputs["megapixels"] = width * height / 1_000_000
                        inputs["aspect_ratio"] = f"{width}:{height}"
                bindings = _board_bindings(_grid_asset_refs(self.db, novel, shot, graph), mapping, graph)
                if [ref for _, ref in bindings] != data.board_reference_images:
                    raise GridPipelineError("整板参考素材已变化，请重新预览生图输入")
                load_nodes = [key for key, node in graph.items() if isinstance(node, dict) and node.get("class_type") == "LoadImage"]
                actual_refs = []
                for index, (node_id, ref) in enumerate(bindings):
                    uploaded = await comfy.client.upload_image(url_to_local_path(ref["url"]))
                    if not uploaded.get("success"):
                        raise GridPipelineError(f"参考图上传失败：{ref['name']}")
                    graph[node_id]["inputs"]["image"] = uploaded["filename"]
                    actual_refs.append({"picture_index": index + 1, **ref})
                for node_id in set(load_nodes) - {node_id for node_id, _ in bindings}:
                    disconnect_reference_chain(graph, node_id)
                task = task or Task(type="grid_board_image", status="running", novel_id=novel.id,
                                    chapter_id=chapter.id, shot_id=shot.id, name=f"宫格整板 Shot {shot.index}",
                                    started_at=datetime.utcnow())
                task.workflow_id, task.workflow_name, task.seed = workflow.id, workflow.name, data.seed
                record_grid_task_inputs(task, data, panel_indexes=[p.index for p in data.panels],
                                        reference_images=actual_refs, prompt_text=data.board_prompt,
                                        template_snapshot=_template(self.db, novel, "grid_image_prompt").template)
                self.db.add(task)
                self.db.commit()
                result = await comfy.generate_shot_image_with_workflow(
                    prompt=data.board_prompt, workflow_json=workflow.workflow_json,
                    node_mapping=mapping, workflow=graph, seed=data.seed,
                    on_prompt_queued=lambda prompt_id, submitted: self._save_queued(task, prompt_id, submitted),
                )
            if not result.get("success") or not result.get("image_url"):
                raise GridPipelineError(result.get("message") or "整板生成失败")
            self._active(task)
            task.progress, task.current_step = 80, "生成完成，正在保存并裁切子格"
            self.db.commit()
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.get(result["image_url"])
                response.raise_for_status()
            board = Image.open(io.BytesIO(response.content)).convert("RGB")
            self._active(task)
            rows, cols = map(int, data.layout.split("x"))
            if board.width < cols or board.height < rows:
                raise GridPipelineError(f"整板图片过小，无法切成 {rows}×{cols} 格")
            source_size = board.size
            normalized_board = Image.new("RGB", (width, height))
            crops = []
            for panel in data.panels:
                col, row = (panel.index - 1) % cols, (panel.index - 1) // cols
                box = (round(col * board.width / cols), round(row * board.height / rows),
                       round((col + 1) * board.width / cols), round((row + 1) * board.height / rows))
                crop = board.crop(box).resize((data.panel_width, data.panel_height), Image.Resampling.LANCZOS)
                normalized_board.paste(crop, (col * data.panel_width, row * data.panel_height))
                crops.append((panel, crop))
            board_bytes = io.BytesIO()
            normalized_board.save(board_bytes, format="PNG")
            data.board_image_url = save_grid_png(board_bytes.getvalue(), grid_asset_path(novel.id, chapter.id, shot.id, data.revision))
            data.board_image_task_id = task.id
            if source_size != (width, height):
                metadata = _json(task.metadata_json, {})
                metadata["board_size_normalization"] = {
                    "source": list(source_size), "saved": [width, height], "method": "split_panels_then_resize"}
                task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            for panel, crop in crops:
                output = io.BytesIO()
                crop.save(output, format="PNG")
                panel.image_url = save_grid_png(output.getvalue(), grid_asset_path(novel.id, chapter.id, shot.id,
                                                                                  data.revision, panel_index=panel.index))
                panel.image_task_id = task.id
                panel.review_status = "pending"
            shot.grid_data = dump_grid_data(data)
            shot.video_director_plan = "{}"
            self._invalidate_shot_video(shot, chapter)
            self._complete(task, data.board_image_url)
            self.db.commit()
            return {"taskId": task.id, "gridData": data.model_dump()}
        except Exception as exc:
            if task:
                self._failed(task, exc)
            raise

    def _save_queued(self, task: Task, prompt_id: str, graph: dict):
        if task.type in {"grid_board_image", "grid_panel_image"}:
            workflow = self.db.get(Workflow, task.workflow_id)
            mapping = _json(workflow.node_mapping, {}) if workflow else {}
            save_image_prompt(self.db, task, prompt_id, graph, mapping.get("save_image_node_id"))
        else:
            self._active(task)
            workflow = self.db.get(Workflow, task.workflow_id)
            mapping = _json(workflow.node_mapping, {}) if workflow else {}
            metadata = _json(task.metadata_json, {})
            metadata["video_save_node_id"] = mapping.get("video_save_node_id", "1")
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            task.comfyui_prompt_id = prompt_id
            task.workflow_json = json.dumps(graph, ensure_ascii=False)
            self.db.commit()
        task.progress = 35
        task.current_step = "已提交 ComfyUI，等待生成结果"
        self.db.commit()

    def review_panel(self, shot: Shot, index: int, status: str, note: str = "") -> GridShotData:
        data = self._grid(shot)
        if not 1 <= index <= len(data.panels) or status not in {"passed", "warning", "failed"}:
            raise GridPipelineError("子格或评审状态无效")
        if not data.panels[index - 1].image_url:
            raise GridPipelineError("此格还没有图片")
        panel = data.panels[index - 1]
        panel.review_status, panel.review_note = status, note
        shot.grid_data = dump_grid_data(data)
        if status == "failed":
            self._invalidate_panel_clips(shot, data, index)
        self.db.commit()
        return data

    def revise_panel(self, shot: Shot, index: int, *, beat: str, camera: str,
                     action: str, characters: list[str]) -> GridShotData:
        data = self._grid(shot)
        if not 1 <= index <= len(data.panels):
            raise GridPipelineError("子格不存在")
        if not all(isinstance(value, str) and value.strip() for value in (beat, camera, action)):
            raise GridPipelineError("剧情、机位和动作不能为空")
        if not isinstance(characters, list) or len(characters) != len(set(characters)) or not set(characters) <= set(_json(shot.characters, [])):
            raise GridPipelineError("可见人物必须来自本 Shot 的已批准角色")
        panel = data.panels[index - 1]
        rows = _json(shot.dialogues, [])
        for number in panel.dialogue_indexes:
            if 1 <= number <= len(rows) and rows[number - 1].get("speaker") == "旁白" and \
                    rows[number - 1].get("delivery") == "offscreen" and characters:
                rows[number - 1]["delivery"] = "narration"
                rows[number - 1]["visual_subjects"] = characters.copy()
        shot.dialogues = json.dumps(rows, ensure_ascii=False)
        if not panel.composition_reference_url and panel.image_task_id == data.board_image_task_id:
            panel.composition_reference_url = panel.image_url
        panel.beat, panel.camera, panel.action, panel.characters = beat.strip(), camera.strip(), action.strip(), characters
        _assert_narration_coverage(shot, data, [index], panel.dialogue_indexes)
        self._invalidate_panel_clips(shot, data, index)
        panel.image_url = panel.image_task_id = panel.image_prompt = None
        panel.image_reference_images = []
        panel.review_status, panel.review_note = "pending", "规划已修订，请重做此格并审核"
        shot.grid_data = dump_grid_data(data)
        self.db.commit()
        return data

    def approve_shot_panels(self, shots: list[Shot]) -> int:
        """Manually approve every pictured, unpassed panel in selected Shots."""
        grids = []
        for shot in shots:
            data = load_grid_data(shot.grid_data)
            if not data or not data.board_image_url or not data.panels or any(not p.image_url for p in data.panels):
                raise GridPipelineError(f"Shot {shot.index} 尚未生成完整宫格图，无法批量审核通过")
            grids.append((shot, data))
        count = 0
        for shot, data in grids:
            for panel in data.panels:
                if panel.review_status != "passed":
                    panel.review_status = "passed"
                    panel.review_note = "人工批量审核通过"
                    count += 1
            shot.grid_data = dump_grid_data(data)
        self.db.commit()
        return count

    def prepare_panel_retry(self, novel: Novel, shot: Shot, index: int) -> dict:
        data = self._grid(shot)
        if not 1 <= index <= len(data.panels) or not data.board_image_url:
            raise GridPipelineError("请先生成整板，再重做单格")
        workflow = WorkflowRepository(self.db).get_active_by_type("shot")
        if not workflow:
            raise GridPipelineError("未配置激活的分镜生图工作流")
        mapping = _json(workflow.node_mapping, {})
        preview_graph = _json(workflow.workflow_json, {})
        panel = data.panels[index - 1]
        refs = [ref for _, ref in _board_bindings(
            _panel_asset_refs(_grid_asset_refs(self.db, novel, shot, preview_graph), panel),
            mapping, preview_graph)]
        dialogues = _dialogues(shot)
        speakers = list(dict.fromkeys(
            dialogues[number - 1]["speaker"] for number in panel.dialogue_indexes
            if 1 <= number <= len(dialogues) and dialogues[number - 1]["speaker"] != "旁白"
            and dialogues[number - 1]["delivery"] != "offscreen"
        ))
        focus = panel.camera.split("focus_subject:", 1)[1].split("；", 1)[0] if "focus_subject:" in panel.camera else ""
        focused_speakers = [speaker for speaker in speakers if speaker in focus]
        speech_focus = (
            f"The dialogue speaker {', '.join(focused_speakers)} MUST be the sharp focal person, "
            f"with a clearly visible face and mouth. Other visible people are listeners; "
            f"if the camera calls for an over-the-shoulder foreground, keep the listener's "
            f"shoulder out of focus and never make the listener's face the focus. "
            f"Keep a travel bag or any other owned prop with its named owner; never transfer "
            f"the speaker's belongings to the listener. "
            if focused_speakers else ""
        )
        panel.image_prompt = _picture_roles(refs) + (
            f"Generate ONE cinematic 16:9 frame as a replacement for storyboard panel {index}. "
            f"Narrative beat: {panel.beat}. Camera: {panel.camera}. Action: {panel.action}. "
            f"{speech_focus}"
            f"Visible characters, exactly one instance of each: {', '.join(panel.characters) or 'none'}. "
            f"Maintain the same character identities, clothing, location, screen axis, lighting and props "
            f"as the approved panel plan. The old board crop may have incorrect blocking; follow this "
            f"panel's camera and speaker focus instead. Match each named person to the corresponding Picture identity reference; "
            f"do not clone a person, swap the middle-aged and elderly faces, or give one person's prop to another. "
            f"Use attached character references only for identity, scene image only for location, "
            f"and prop image only for appearance. If a PANEL_COMPOSITION reference is supplied, "
            f"keep its farmhouse doorway and camera geography, but add the required visible actors and action; "
            f"do not mistake the outer courtyard gate for the house interior door. Fill the entire frame. "
            f"No grid, borders, labels, text, subtitles, white background or contact sheet."
        )
        panel.image_reference_images = refs
        shot.grid_data = dump_grid_data(data)
        self.db.commit()
        return {"prompt": panel.image_prompt, "referenceImages": refs,
                "size": list(_panel_generation_size(data.panel_width, data.panel_height))}

    async def generate_panel_retry(self, novel: Novel, chapter: Chapter, shot: Shot, index: int,
                                   task: Task | None = None) -> dict:
        data = self._grid(shot)
        if not 1 <= index <= len(data.panels) or not data.panels[index - 1].image_prompt:
            raise GridPipelineError("请先预览此格重做提示词")
        panel = data.panels[index - 1]
        workflow = (self.db.get(Workflow, task.workflow_id) if task and task.comfyui_prompt_id else
                    WorkflowRepository(self.db).get_active_by_type("shot"))
        if not workflow and not (task and task.comfyui_prompt_id):
            raise GridPipelineError("未配置激活的分镜生图工作流")
        comfy = ComfyUIService()
        try:
            if task and task.comfyui_prompt_id:
                self._active(task)
                result = await resume_image_prompt(self.db, task, comfy)
            else:
                mapping = _json(workflow.node_mapping, {})
                seed = task.seed if task and task.seed else secrets.randbelow(2**31 - 1) + 1
                graph = comfy.builder.build_shot_workflow(panel.image_prompt, workflow.workflow_json, mapping, seed=seed)
                generation_width, generation_height = _panel_generation_size(data.panel_width, data.panel_height)
                for key, size in (("width_node_id", generation_width), ("height_node_id", generation_height)):
                    node_id = str(mapping.get(key) or "")
                    if node_id in graph:
                        inputs = graph[node_id].setdefault("inputs", {})
                        inputs["value" if "value" in inputs else key.split("_")[0]] = size
                bindings = _board_bindings(
                    _panel_asset_refs(_grid_asset_refs(self.db, novel, shot, graph), panel), mapping, graph)
                if [ref for _, ref in bindings] != panel.image_reference_images:
                    raise GridPipelineError("单格参考素材已变化，请重新预览生图输入")
                load_nodes = [key for key, node in graph.items() if isinstance(node, dict) and node.get("class_type") == "LoadImage"]
                refs = []
                for n, (node_id, ref) in enumerate(bindings, 1):
                    uploaded = await comfy.client.upload_image(url_to_local_path(ref["url"]))
                    if not uploaded.get("success"):
                        raise GridPipelineError(f"参考图上传失败：{ref['name']}")
                    graph[node_id]["inputs"]["image"] = uploaded["filename"]
                    refs.append({"picture_index": n, **ref})
                for node_id in set(load_nodes) - {node_id for node_id, _ in bindings}:
                    disconnect_reference_chain(graph, node_id)
                task = task or Task(type="grid_panel_image", status="running", novel_id=novel.id,
                                    chapter_id=chapter.id, shot_id=shot.id,
                                    name=f"宫格 Shot {shot.index} 子格 {index} 重做", started_at=datetime.utcnow())
                task.workflow_id, task.workflow_name, task.seed = workflow.id, workflow.name, seed
                record_grid_task_inputs(task, data, panel_indexes=[index], reference_images=refs,
                                        prompt_text=panel.image_prompt,
                                        template_snapshot="GRID_PANEL_RETRY_FROM_APPROVED_GRID_V1")
                self.db.add(task)
                self.db.commit()
                result = await comfy.generate_shot_image_with_workflow(
                    prompt=panel.image_prompt, workflow_json=workflow.workflow_json,
                    node_mapping=mapping, workflow=graph, seed=seed,
                    on_prompt_queued=lambda prompt_id, submitted: self._save_queued(task, prompt_id, submitted),
                )
            if not result.get("success") or not result.get("image_url"):
                raise GridPipelineError(result.get("message") or "子格重做失败")
            self._active(task)
            task.progress, task.current_step = 80, "生成完成，正在保存子格"
            self.db.commit()
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.get(result["image_url"])
                response.raise_for_status()
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
            self._active(task)
            if abs(image.width / image.height - 16 / 9) > .02:
                raise GridPipelineError("生成子格不是 16:9")
            output = io.BytesIO()
            image.resize((data.panel_width, data.panel_height), Image.Resampling.LANCZOS).save(output, format="PNG")
            panel.image_url = save_grid_png(output.getvalue(), grid_asset_path(novel.id, chapter.id, shot.id,
                                                                                data.revision, panel_index=index))
            panel.image_task_id = task.id
            panel.review_status, panel.review_note = "pending", None
            shot.grid_data = dump_grid_data(data)
            self._invalidate_panel_clips(shot, data, index, chapter)
            self._complete(task, panel.image_url)
            self.db.commit()
            return {"taskId": task.id, "gridData": data.model_dump()}
        except Exception as exc:
            if task:
                self._failed(task, exc)
            raise

    def replace_panel(self, novel: Novel, chapter: Chapter, shot: Shot, index: int, content: bytes) -> GridShotData:
        data = self._grid(shot)
        if not 1 <= index <= len(data.panels):
            raise GridPipelineError("子格编号无效")
        image = Image.open(io.BytesIO(content)).convert("RGB")
        if abs(image.width / image.height - 16 / 9) > 0.02:
            raise GridPipelineError("替换子图必须是 16:9")
        output = io.BytesIO()
        image.resize((data.panel_width, data.panel_height), Image.Resampling.LANCZOS).save(output, format="PNG")
        panel = data.panels[index - 1]
        panel.image_url = save_grid_png(output.getvalue(), grid_asset_path(novel.id, chapter.id, shot.id,
                                                                           data.revision, panel_index=index))
        panel.review_status, panel.review_note = "pending", None
        shot.grid_data = dump_grid_data(data)
        self._invalidate_panel_clips(shot, data, index, chapter)
        self.db.commit()
        return data

    async def plan_clips(self, novel: Novel, chapter: Chapter, shot: Shot, task: Task | None = None) -> dict:
        data = self._grid(shot)
        if any(not panel.image_url or panel.review_status == "failed" for panel in data.panels):
            raise GridPipelineError("请先生成全部子格并处理初审 FAIL 的子格")
        previous_plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=data.revision)
        if previous_plan and any(clip.get("video_url") for clip in previous_plan["clip_plan"]):
            raise GridPipelineError("已有生成的 Clip；请逐条重做，不可直接重新规划")
        dialogues = _dialogues(shot)
        for panel in data.panels:
            _assert_narration_coverage(shot, data, [panel.index], panel.dialogue_indexes)
        planning_input = {
            "shot_duration_seconds": shot.duration,
            "panel_count": len(data.panels),
            "panels": [p.model_dump() for p in data.panels], "dialogues": dialogues,
            "workflow_max_duration_seconds": 20,
        }
        result, _ = await self._ask(novel, chapter, shot, "grid_clip_plan", planning_input)
        rows = result.get("clips")
        if not isinstance(rows, list) or not rows:
            raise GridPipelineError("Clip 规划为空")
        if all(isinstance(row, dict) for row in rows):
            proposed_panels = [_panel_number(value) for row in rows
                               for value in row.get("physical_reference_panels") or []]
            missing_panels = sorted({panel.index for panel in data.panels} - set(proposed_panels))
            if missing_panels or proposed_panels != sorted(proposed_panels):
                result, _ = await self._ask(novel, chapter, shot, "grid_clip_plan", {
                    **planning_input, "previous_plan": result,
                    "repair_errors": (f"子格顺序错误或未覆盖全部子格；缺失编号：{missing_panels}。"
                                      "请重排 Clip，并为无台词子格安排 dialogue_ids=[] 的 Clip。"),
                })
                rows = result.get("clips")
                if not isinstance(rows, list) or not rows:
                    raise GridPipelineError("Clip 规划修复结果为空")
        clips, assigned, used_panels = [], [], []
        cursor = 0.0
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise GridPipelineError(f"Clip {index} 规划格式无效")
            start, end = float(row.get("start_time", -1)), float(row.get("end_time", -1))
            panels = [_panel_number(value) for value in row.get("physical_reference_panels") or []]
            raw_ids = row.get("dialogue_ids") or []
            if raw_ids == ["NO_VOICE"]:
                raw_ids = []
            ids = [_panel_number(value) for value in raw_ids]
            strategy = "split_panels"  # Whole board is an explicit later UI choice.
            if (row.get("clip_index") != index or abs(start - cursor) > 0.01
                    or not start.is_integer() or not end.is_integer()
                    or not start < end <= shot.duration + 0.01 or end - start > 20.001):
                raise GridPipelineError(f"Clip {index} 时间范围无效")
            if strategy not in {"split_panels", "whole_board"} or not panels or any(n < 1 or n > len(data.panels) for n in panels):
                raise GridPipelineError(f"Clip {index} 参考图无效")
            if panels != list(range(panels[0], panels[-1] + 1)):
                raise GridPipelineError(f"Clip {index} 的子格必须连续")
            used_panels.extend(panels)
            assigned.extend(ids)
            clip_dialogues = [dialogues[i - 1] for i in ids if 1 <= i <= len(dialogues)]
            if len(clip_dialogues) != len(ids):
                raise GridPipelineError("Clip 引用了不存在的台词")
            if any(line["delivery"] == "offscreen" for line in clip_dialogues):
                if len(panels) != 1 or data.panels[panels[0] - 1].characters:
                    raise GridPipelineError(f"Clip {index} 含画外台词，必须只用一格无人出镜的环境画面")
            for dialogue in clip_dialogues:
                required = _required_narration_subjects(dialogue, _json(shot.characters, []))
                if not set(required) <= {name for panel in panels for name in data.panels[panel - 1].characters}:
                    raise GridPipelineError(f"Clip {index} 旁白描述的动作缺少可见人物：{', '.join(required)}")
            duration = round(end - start, 3)
            spacing = duration / (len(ids) + 1) if ids else 0
            timed = [{**dialogue, "start_time": round(max(.1, spacing * (j + .35)), 2),
                      "end_time": round(min(duration, spacing * (j + .85)), 2)}
                     for j, dialogue in enumerate(clip_dialogues)]
            clips.append({"clip_index": index, "start_time": start, "end_time": end,
                          "duration": duration, "panel_indexes": panels, "reference_strategy": strategy,
                          "dialogue_indexes": ids, "dialogues": timed,
                          "camera_and_action": row.get("camera_and_action") or "",
                          "continuity_to_previous": row.get("continuity_to_previous") or ""})
            cursor = end
        if abs(cursor - shot.duration) > .01 or assigned != list(range(1, len(dialogues) + 1)):
            raise GridPipelineError("Clip 未完整覆盖 Shot 时长及原文台词")
        if sorted(used_panels) != used_panels or set(used_panels) != {p.index for p in data.panels}:
            raise GridPipelineError("Clip 必须按顺序覆盖全部子格")
        shot.video_director_plan = dump_grid_clip_plan(data, clips)
        self._complete(task)
        self.db.commit()
        return read_grid_clip_plan(shot.video_director_plan, grid_revision=data.revision)

    def _clip(self, shot: Shot, index: int) -> tuple[GridShotData, dict, dict]:
        data = self._grid(shot)
        plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=data.revision)
        if not plan or not 1 <= index <= len(plan["clip_plan"]):
            raise GridPipelineError("请先规划当前修订的 Clip")
        return data, plan, plan["clip_plan"][index - 1]

    def _clip_refs(self, data: GridShotData, clip: dict) -> list[dict]:
        strategy = clip["reference_strategy"]
        panel_indexes = clip["panel_indexes"]
        if any(line.get("delivery") == "offscreen" for line in clip.get("dialogues", [])):
            if strategy != "split_panels" or len(panel_indexes) != 1:
                raise GridPipelineError("画外声 Clip 只能使用一格无人环境子格，不能整板直传")
            if data.panels[panel_indexes[0] - 1].characters:
                raise GridPipelineError("画外声 Clip 的参考子格必须无人出镜")
        reviewed_indexes = range(1, len(data.panels) + 1) if strategy == "whole_board" else panel_indexes
        if any(data.panels[index - 1].review_status == "failed" for index in reviewed_indexes):
            raise GridPipelineError("参考子格初审 FAIL，不能编译或生成 H3 Clip")
        if strategy == "whole_board" and any(
            panel.image_task_id != data.board_image_task_id for panel in data.panels
        ):
            raise GridPipelineError("整板不包含重做后的子格，请改用裁切子格参考")
        urls = [data.board_image_url] if strategy == "whole_board" else [data.panels[index - 1].image_url for index in panel_indexes]
        if not urls or any(not url or not url_to_local_path(url) for url in urls):
            raise GridPipelineError("H3 实际参考图缺失")
        return [{"picture_index": i, "role": "GRID_BOARD" if strategy == "whole_board" else "GRID_PANEL",
                 "panel_index": None if strategy == "whole_board" else clip["panel_indexes"][i-1], "url": url}
                for i, url in enumerate(urls, 1)]

    async def _review_clip_video(self, novel: Novel, chapter: Chapter, shot: Shot,
                                 data: GridShotData, clip: dict, path: str,
                                 evidence_urls: list[str] | None = None) -> dict:
        """Check actual video frames against the approved visible people contract."""
        _, _, duration = await asyncio.to_thread(probe_nameplate_video, path)
        expected = list(dict.fromkeys(name for number in clip["panel_indexes"]
                                      for name in data.panels[number - 1].characters))
        base = (file_storage._get_story_dir(novel.id) / f"chapter_{chapter.id[:8]}" / "reviews"
                if novel.id and chapter.id else Path(path).parent)
        directory = base / f"grid_shot_{shot.index}_c{clip['clip_index']}_{secrets.token_hex(6)}"
        directory.mkdir(parents=True, exist_ok=True)
        images = []
        for ref in clip["reference_images"]:
            images.append(await asyncio.to_thread(
                vision_proxy, ref["url"], logical_id=f"REFERENCE_{ref['picture_index']}",
                name=f"已审核子格 {ref.get('panel_index') or '整板'}", role="approved_reference"))
        for index, fraction in enumerate((.1, .35, .65, .9), 1):
            frame = directory / f"frame_{index}.jpg"
            await asyncio.to_thread(extract_review_frame, Path(path), min(duration - .02, duration * fraction), frame)
            if evidence_urls is not None and frame.is_file():
                evidence_urls.append(local_path_to_url(str(frame)))
            images.append(await asyncio.to_thread(
                vision_proxy, frame, logical_id=f"VIDEO_FRAME_{index}",
                name=f"成片帧 {index}", role="generated_video_frame"))
        response = await self.llm.chat_completion(
                system_prompt=(
                    "你是宫格 Clip 成片视觉验收员。前面的图片是批准的参考子格，后四张按时间排序是实际视频帧。"
                    "只根据视频帧判断画面实际出现的人物，不把参考图人物当成视频帧。"
                    "核对预期可见角色、明显多余人物、人物身份和原文描述的可见动作。"
                    "若预期为空而任一视频帧出现清晰人物，必须 FAIL；若出现明显错误身份，也必须 FAIL。"
                    "抽帧无法证明动作缺失时用 WARNING，不凭单帧推断整段无动作。"
                    "只返回 JSON：{\"overall\":\"PASS|WARNING|FAIL\",\"unexpected_people\":true|false,"
                    "\"missing_subjects\":[],\"summary\":\"具体可见证据\"}。"
                ),
                user_content=json.dumps({"shot": shot.description, "clip_index": clip["clip_index"],
                                         "expected_visible_characters": expected,
                                         "panels": [data.panels[i - 1].model_dump(include={"index", "beat", "action", "characters"})
                                                    for i in clip["panel_indexes"]]}, ensure_ascii=False),
                response_format="json_object", task_type="grid_clip_visual_review",
                novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, images=images,
            )
        if not response.get("success"):
            raise GridVisualReviewError(response.get("error") or "成片视觉验收调用失败",
                                        category="execution_error", result={"llm_log_id": response.get("log_id")})
        result = safe_parse_llm_json(response.get("content") or "", default=None)
        if not isinstance(result, dict) or result.get("overall") not in {"PASS", "WARNING", "FAIL"}:
            raise GridVisualReviewError("成片视觉验收结果无效", category="execution_error",
                                        result={"llm_log_id": response.get("log_id")})
        if result["overall"] == "FAIL" or result.get("unexpected_people") is True:
            raise GridVisualReviewError(f"成片视觉验收未通过：{result.get('summary') or '人物与分镜不符'}",
                                        category="rejected", result={**result, "overall": "FAIL",
                                                                     "llm_log_id": response.get("log_id")})
        return {"overall": result["overall"], "summary": str(result.get("summary") or "")[:500],
                "missing_subjects": result.get("missing_subjects") or [],
                "llm_log_id": response.get("log_id")}

    async def prepare_clip(self, novel: Novel, chapter: Chapter, shot: Shot, index: int,
                           strategy: str | None = None, task: Task | None = None) -> dict:
        data, plan, clip = self._clip(shot, index)
        _assert_narration_coverage(shot, data, clip["panel_indexes"], _clip_dialogue_indexes(clip))
        canonical = {line["id"]: line for line in _dialogues(shot)}
        for line in clip["dialogues"]:
            source = canonical.get(line.get("id"))
            if source and source["delivery"] == "narration":
                line["delivery"] = "narration"
                line["visual_subjects"] = source["visual_subjects"]
        if any(line.get("visual_subjects") for line in clip["dialogues"]):
            clip["camera_and_action"] = "\n".join(
                f"格 {number}：{data.panels[number - 1].beat}；机位：{data.panels[number - 1].camera}；"
                f"动作：{data.panels[number - 1].action}"
                for number in clip["panel_indexes"])
        if strategy:
            if strategy not in {"split_panels", "whole_board"}:
                raise GridPipelineError("未知的参考图策略")
            clip["reference_strategy"] = strategy
        refs = self._clip_refs(data, clip)
        subjects, dialogue_events = _h3_bindings(data, clip)
        payload = {"clip_duration_seconds": clip["duration"], "shot": shot.description,
                   "camera_and_action": clip["camera_and_action"],
                   "panels": [data.panels[i-1].model_dump() for i in clip["panel_indexes"]],
                   "physical_pictures": refs, "subject_definitions": subjects,
                   "dialogues": dialogue_events, "music_policy": "None",
                   "reference_strategy": clip["reference_strategy"]}
        if not dialogue_events:
            payload["no_voice"] = True
            payload["camera_and_action"] = payload["camera_and_action"].replace("说完后", "").replace("回答结束后", "")
        prompt, template = await self._ask(novel, chapter, shot, "grid_h3_phase_b", payload,
                                           json_result=False, image_refs=refs)
        prompt = normalize_grid_dialogue_markers(prompt, dialogue_events)
        if not dialogue_events:
            prompt = enforce_grid_no_voice(prompt)
        try:
            checks = validate_grid_h3_prompt(prompt, subjects, dialogue_events,
                                             [r["picture_index"] for r in refs], clip["duration"])
        except ValueError as exc:
            payload["repair_errors"] = str(exc)
            payload["previous_prompt"] = prompt
            prompt, _ = await self._ask(novel, chapter, shot, "grid_h3_phase_b", payload,
                                        json_result=False, image_refs=refs)
            prompt = normalize_grid_dialogue_markers(prompt, dialogue_events)
            if not dialogue_events:
                prompt = enforce_grid_no_voice(prompt)
            checks = validate_grid_h3_prompt(prompt, subjects, dialogue_events,
                                             [r["picture_index"] for r in refs], clip["duration"])
        clip["prompt"] = prompt
        if clip.get("video_url"):
            clip.pop("video_url", None)
            clip.pop("video_task_id", None)
            self._invalidate_shot_video(shot, chapter)
        clip["reference_images"] = refs
        clip["prompt_template_snapshot"] = template
        clip["validation"] = checks
        shot.video_director_plan = dump_grid_clip_plan(data, plan["clip_plan"])
        self._complete(task)
        self.db.commit()
        return {"clip": clip, "referenceImages": refs, "prompt": prompt, "checks": checks}

    async def generate_clip(self, novel: Novel, chapter: Chapter, shot: Shot, index: int,
                            task: Task | None = None) -> dict:
        data, plan, clip = self._clip(shot, index)
        _assert_narration_coverage(shot, data, clip["panel_indexes"], _clip_dialogue_indexes(clip))
        if not clip.get("prompt"):
            raise GridPipelineError("请先预览并保存 H3 六段式提示词")
        refs = self._clip_refs(data, clip)
        if refs != clip.get("reference_images"):
            raise GridPipelineError("参考图已变化，请重新编译 H3 提示词")
        subjects, dialogue_events = _h3_bindings(data, clip)
        validate_grid_h3_prompt(clip["prompt"], subjects, dialogue_events,
                                [r["picture_index"] for r in refs], clip["duration"])
        workflow = (self.db.get(Workflow, task.workflow_id) if task and task.comfyui_prompt_id else
                    WorkflowRepository(self.db).get_active_by_type("multi_reference_video"))
        if not workflow and not (task and task.comfyui_prompt_id):
            raise GridPipelineError("未配置激活的 H3 多参考生视频工作流")
        def check_graph(graph, _manifest):
            if not any(node.get("class_type") == "MiniMaxH3ReferenceToVideo"
                       and node.get("inputs", {}).get("ref_image_size") == "match"
                       for node in graph.values() if isinstance(node, dict)):
                raise GridPipelineError("H3 ref_image_size 必须为 match")
            self._active(task)
            task.workflow_json = json.dumps(graph, ensure_ascii=False)
            self.db.commit()
        try:
            comfy = ComfyUIService()
            if task and task.comfyui_prompt_id:
                self._active(task)
                graph = _json(task.workflow_json, {})
                if not graph:
                    raise GridPipelineError("已提交的 H3 任务缺少工作流快照，拒绝重复提交")
                mapping = _json(workflow.node_mapping, {}) if workflow else {}
                saved_output = _json(task.metadata_json, {}).get("video_save_node_id")
                result = await comfy.client.wait_for_result(task.comfyui_prompt_id, graph,
                                                            saved_output or mapping.get("video_save_node_id", "1"), timeout=7200)
                result["video_url"] = result.get("video_url") or result.get("image_url")
            else:
                mapping = _json(workflow.node_mapping, {})
                if not mapping.get("load_image_node_1"):
                    raise GridPipelineError("H3 工作流缺少多参考图节点映射")
                task = task or Task(type="grid_h3_clip", status="running", novel_id=novel.id,
                                    chapter_id=chapter.id, shot_id=shot.id, clip_index=index,
                                    execution_scope="CLIP", name=f"宫格 H3 Shot {shot.index} C{index}",
                                    started_at=datetime.utcnow())
                task.workflow_id, task.workflow_name = workflow.id, workflow.name
                task.seed = task.seed or secrets.randbelow(2**31-1)+1
                record_grid_task_inputs(task, data, panel_indexes=clip["panel_indexes"], reference_images=refs,
                                        prompt_text=clip["prompt"],
                                        template_snapshot=clip["prompt_template_snapshot"])
                self.db.add(task)
                self.db.commit()
                result = await comfy.generate_shot_video_with_workflow(
                    prompt=clip["prompt"], workflow_json=workflow.workflow_json, node_mapping=mapping,
                    duration_seconds=max(1, round(clip["duration"])), seed=task.seed,
                    reference_image_paths=[url_to_local_path(ref["url"]) for ref in refs],
                    before_submit=check_graph,
                    on_prompt_queued=lambda prompt_id, submitted: self._save_queued(task, prompt_id, submitted),
                )
            if not result.get("success") or not result.get("video_url"):
                raise GridPipelineError(result.get("message") or "H3 Clip 生成失败")
            self._active(task)
            task.progress, task.current_step = 80, "H3 完成，正在保存 Clip"
            self.db.commit()
            path = await file_storage.download_video_receipt(result["video_url"], novel.id, chapter.id,
                                                             shot.index, filename_suffix=f"grid_c{index}")
            self._active(task)
            if any(line.get("delivery") == "narration" and line.get("visual_subjects")
                   for line in clip["dialogues"]):
                for attempt in range(2):
                    evidence_urls: list[str] = []
                    try:
                        visual_review = await self._review_clip_video(
                            novel, chapter, shot, data, clip, path, evidence_urls)
                        category = "accepted"
                    except GridVisualReviewError as exc:
                        visual_review = exc.result
                        category = exc.category
                        error = str(exc)
                    except Exception as exc:
                        visual_review = {}
                        category = "execution_error"
                        error = f"成片视觉验收异常：{exc}"
                    event = {"clip_index": index, "category": category,
                             "overall": visual_review.get("overall", "ERROR"),
                             "summary": visual_review.get("summary") or (error if category != "accepted" else ""),
                             "video_url": local_path_to_url(path),
                             "unexpected_people": visual_review.get("unexpected_people"),
                             "missing_subjects": visual_review.get("missing_subjects") or [],
                             "evidence_frames": [url for url in evidence_urls if url],
                             "llm_log_id": visual_review.get("llm_log_id"),
                             "created_at": datetime.utcnow().isoformat() + "Z"}
                    metadata = _json(task.metadata_json, {})
                    metadata.setdefault("visual_review_attempts", []).append(event)
                    metadata["visual_review"] = event
                    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
                    self.db.commit()
                    if category == "accepted":
                        break
                    if category == "rejected" or attempt == 1:
                        raise GridPipelineError(error)
            video_url = local_path_to_url(path)
            if not video_url:
                raise GridPipelineError("H3 Clip 保存失败")
            clip["video_url"] = video_url
            clip["video_task_id"] = task.id
            shot.video_director_plan = dump_grid_clip_plan(data, plan["clip_plan"])
            self._invalidate_shot_video(shot, chapter)
            self._complete(task, video_url)
            self.db.commit()
            return {"taskId": task.id, "videoUrl": video_url, "clip": clip}
        except Exception as exc:
            if task:
                self._failed(task, exc)
            raise


    async def merge_shot(self, novel: Novel, chapter: Chapter, shot: Shot,
                         task: Task | None = None) -> str:
        data = self._grid(shot)
        plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=data.revision)
        if not plan or any(not clip.get("video_url") for clip in plan["clip_plan"]):
            raise GridPipelineError("所有 Clip 生成完成后才能合并 Shot")
        paths = [url_to_local_path(clip["video_url"]) for clip in plan["clip_plan"]]
        if not all(paths):
            raise GridPipelineError("Clip 视频文件不存在")
        output = file_storage._get_story_dir(novel.id) / f"chapter_{chapter.id[:8]}" / "videos" / f"grid_shot_{shot.index}_{secrets.token_hex(6)}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        result = await file_storage.merge_videos(paths, str(output))
        if not result.get("success"):
            raise GridPipelineError(result.get("message") or "Shot 合片失败")
        self._active(task)
        chapter.final_video = None
        shot.video_url, shot.video_status = local_path_to_url(str(output)), "completed"
        plan["merged_video_url"] = shot.video_url
        shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
        self._complete(task, shot.video_url)
        self.db.commit()
        return shot.video_url

    async def merge_chapter(self, novel: Novel, chapter: Chapter,
                            task: Task | None = None) -> str:
        shots = self.db.query(Shot).filter(Shot.chapter_id == chapter.id).order_by(Shot.index).all()
        if not shots or any(not shot.video_url for shot in shots):
            raise GridPipelineError("所有 Shot 合片完成后才能合并章回")
        paths = [url_to_local_path(shot.video_url) for shot in shots]
        if not all(paths):
            raise GridPipelineError("Shot 视频文件不存在")
        output = file_storage._get_story_dir(novel.id) / f"chapter_{chapter.id[:8]}" / "videos" / f"grid_chapter_{secrets.token_hex(6)}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        result = await file_storage.merge_videos(paths, str(output))
        if not result.get("success"):
            raise GridPipelineError(result.get("message") or "章回合片失败")
        self._active(task)
        raw_url = local_path_to_url(str(output))
        final_url = raw_url
        config = self.db.get(SystemConfig, "default")
        nameplate_mode = (config.nameplate_preview_mode or "protagonist_first") if config else "protagonist_first"
        auto_approve = bool(config.auto_approve_first_appearance_names) if config else True
        preview_url = None
        events, warnings = [], []
        try:
            if task:
                task.progress, task.current_step = 75, "正在定位首次出镜位置"
                self.db.commit()
            width, height, _ = await asyncio.to_thread(probe_nameplate_video, output)
            segments = [{"kind": "shot", "key": shot.index, "path": path}
                        for shot, path in zip(shots, paths)]
            events, warnings = await build_nameplate_events(
                self.db, novel.id, chapter.id, segments,
                output_size=(width, height), mode=nameplate_mode,
                use_distractor_references=True)
            if events:
                preview_path = output.with_name(f"{output.stem}-names.mp4")
                if task:
                    task.progress, task.current_step = 85, "正在生成姓名牌预览"
                    self.db.commit()
                await render_first_appearance_nameplates(output, preview_path, events)
                preview_url = local_path_to_url(str(preview_path))
                if auto_approve:
                    final_url = preview_url
        except Exception as exc:
            warnings.append(f"姓名牌预览失败：{exc}")
            events = []
            preview_url = None
        if task:
            metadata = _json(task.metadata_json, {})
            metadata.update({
                "nameplate_events": events,
                "nameplate_warnings": warnings,
                "nameplate_preview_url": preview_url,
                "nameplate_status": "approved" if preview_url and auto_approve else
                                    "pending_confirmation" if preview_url else "none",
                "nameplate_auto_approved": bool(preview_url and auto_approve),
                "nameplate_raw_url": raw_url,
                "video_url": final_url,
                "video_variant": "draft",
                "is_final_video": True,
            })
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        chapter.final_video = final_url
        self._complete(task, chapter.final_video)
        self.db.commit()
        return chapter.final_video
