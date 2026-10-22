"""Generate a title cover from a selected frame of a merged novel video."""
import asyncio
import io
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageOps

from app.core.database import SessionLocal
from app.models.novel import Novel
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.background_workers import persistent_job, worker_manager
from app.services.cover_text_styles import draw_styled_cover
from app.services.comfyui.service import ComfyUIService
from app.services.file_storage import file_storage
from app.services.prompt_builder import get_style
from app.utils.image_utils import load_chinese_font
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.time_utils import format_datetime


COVER_SIZES = {"16:9": (1536, 864), "9:16": (864, 1536), "4:3": (1152, 864), "3:4": (864, 1152), "1:1": (1024, 1024)}
COVER_TEXT_STYLES = {"classic", "cinematic", "editorial", "vintage"}


def format_novel_video_cover(task: Task | None) -> dict | None:
    if task is None:
        return None
    metadata = json.loads(task.metadata_json or "{}")
    return {
        "id": task.id, "status": task.status, "progress": task.progress or 0,
        "currentStep": task.current_step, "errorMessage": task.error_message,
        "imageUrl": task.result_url, "frameSeconds": metadata.get("frame_seconds"),
        "aspectRatio": metadata.get("aspect_ratio"), "title": metadata.get("title"),
        "author": metadata.get("author"), "production": metadata.get("production"),
        "textStyle": metadata.get("text_style", "classic"),
        "createdAt": format_datetime(task.created_at),
    }


def enqueue_novel_video_cover_task(task_id: str) -> None:
    payload = {"task_id": task_id}
    worker_manager.worker("novel_video").enqueue(persistent_job(
        task_id,
        "app.services.novel_video_cover_service:run_novel_video_cover_task",
        payload,
        lambda: run_novel_video_cover_task(**payload),
    ))


def resume_active_novel_video_covers() -> int:
    db = SessionLocal()
    try:
        tasks = db.query(Task).filter(Task.type == "novel_video_cover", Task.status.in_(["pending", "running"])).all()
        for task in tasks:
            task.status = "pending"
            task.current_step = "服务重启，等待恢复封面生成..."
        db.commit()
        ids = [task.id for task in tasks]
    finally:
        db.close()
    for task_id in ids:
        enqueue_novel_video_cover_task(task_id)
    return len(ids)


def _extract_frame(video_path: Path, seconds: float, output_path: Path) -> None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(seconds),
         "-i", str(video_path), "-frames:v", "1", str(output_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0 or not output_path.is_file():
        raise RuntimeError(f"无法提取所选视频帧：{result.stderr.strip() or '未找到画面'}")


def _set_dimension(workflow: dict, node_id: str | None, value: int) -> None:
    node = workflow.get(str(node_id)) if node_id else None
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise ValueError("场景分镜图工作流的宽高节点映射不完整")
    inputs = node["inputs"]
    if "Number" in inputs:
        inputs.pop("value", None)  # Int 节点不接受额外的 value 参数。
        inputs["Number"] = str(value) if isinstance(inputs["Number"], str) else value
    elif "value" in inputs:
        inputs["value"] = str(value) if isinstance(inputs["value"], str) else value
    else:
        raise ValueError("场景分镜图工作流的宽高节点没有可写数值")


def _draw_cover(image_bytes: bytes, destination: Path, size: tuple[int, int], title: str, author: str, production: str,
                text_style: str = "classic") -> None:
    if text_style not in COVER_TEXT_STYLES:
        raise ValueError("不支持的封面文字款式")
    with Image.open(io.BytesIO(image_bytes)) as source:
        canvas = ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS).convert("RGBA")
    if text_style != "classic":
        canvas = draw_styled_cover(canvas, title, author, production, text_style)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp.png")
        canvas.convert("RGB").save(temporary, format="PNG", optimize=True)
        os.replace(temporary, destination)
        return
    width, height = size
    overlay = Image.new("RGBA", size)
    overlay_draw = ImageDraw.Draw(overlay)
    for y in range(int(height * 0.30), height):
        position = max(0, (y / height - 0.30) / 0.70)
        alpha = round(205 * position ** 1.6)
        overlay_draw.line((0, y, width, y), fill=(8, 13, 21, alpha))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)
    margin = round(min(width, height) * 0.075)
    text_width = width - 2 * margin

    def wrap(text: str, font, max_width: float = text_width) -> list[str]:
        lines, current = [], ""
        for char in text:
            candidate = current + char
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    details = [("原作者", author), ("制　作", production)]
    detail_size = max(22, round(min(width, height) * 0.035))
    detail_font = load_chinese_font(detail_size)
    label_width = max(draw.textlength(label, font=detail_font) for label, _ in details)
    colon_width = draw.textlength("：", font=detail_font)
    detail_gap = round(detail_size * 0.12)
    detail_lines = [wrap(value, detail_font, text_width - label_width - colon_width - detail_gap) for _, value in details]
    while detail_size > 16 and sum(map(len, detail_lines)) > 4:
        detail_size -= 2
        detail_font = load_chinese_font(detail_size)
        label_width = max(draw.textlength(label, font=detail_font) for label, _ in details)
        colon_width = draw.textlength("：", font=detail_font)
        detail_gap = round(detail_size * 0.12)
        detail_lines = [wrap(value, detail_font, text_width - label_width - colon_width - detail_gap) for _, value in details]
    widest_value = max(draw.textlength(line, font=detail_font) for lines in detail_lines for line in lines)
    detail_x = (width - label_width - colon_width - detail_gap - widest_value) / 2
    value_x = detail_x + label_width + colon_width + detail_gap
    detail_step = round(detail_size * 1.45)
    detail_height = sum(map(len, detail_lines)) * detail_step + detail_step // 3

    title_text = title.strip()
    title_size = round(min(width, height) * 0.105)
    title_font = load_chinese_font(title_size)
    title_lines = wrap(title_text, title_font)
    while title_size > 20 and (len(title_lines) > 5 or len(title_lines) * title_size * 1.2 > height * 0.42):
        title_size -= 2
        title_font = load_chinese_font(title_size)
        title_lines = wrap(title_text, title_font)
    title_step = round(title_size * 1.2)
    base_y = height - margin - detail_height - round(height * 0.18)
    title_y = base_y - len(title_lines) * title_step - round(title_size * 0.22)
    for index, line in enumerate(title_lines):
        y = title_y + index * title_step
        x = (width - draw.textlength(line, font=title_font)) / 2
        draw.text((x + 2, y + 3), line, font=title_font, fill=(0, 0, 0, 150), stroke_width=2)
        draw.text((x, y), line, font=title_font, fill=(255, 252, 242, 255))
    for (label, _), lines in zip(details, detail_lines):
        for index, line in enumerate(lines):
            if index == 0:
                draw.text((detail_x, base_y), label, font=detail_font, fill=(246, 241, 229, 235))
                draw.text((detail_x + label_width, base_y), "：", font=detail_font, fill=(246, 241, 229, 235))
            draw.text((value_x, base_y), line, font=detail_font, fill=(246, 241, 229, 235))
            base_y += detail_step
        base_y += detail_step // 3
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.png")
    canvas.convert("RGB").save(temporary, format="PNG", optimize=True)
    os.replace(temporary, destination)


async def run_novel_video_cover_task(task_id: str) -> None:
    db = SessionLocal()
    task = None
    try:
        task = db.query(Task).filter(Task.id == task_id, Task.type == "novel_video_cover").first()
        if not task or task.status not in {"pending", "running"}:
            return
        metadata = json.loads(task.metadata_json or "{}")
        merge = db.query(Task).filter(Task.id == task.parent_task_id, Task.novel_id == task.novel_id,
                                      Task.type == "novel_video", Task.status == "completed").first()
        novel = db.query(Novel).filter(Novel.id == task.novel_id).first()
        workflow = db.query(Workflow).filter(Workflow.id == task.workflow_id).first()
        video_local = url_to_local_path(merge.result_url) if merge and merge.result_url else None
        video_path = Path(video_local) if video_local else None
        if not novel or not workflow or not video_path or not video_path.is_file():
            raise ValueError("合并视频或场景分镜图工作流不可用")
        mapping = json.loads(workflow.node_mapping or "{}")
        output_dir = file_storage._get_story_dir(task.novel_id) / "novel-video-covers" / merge.id
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_path = output_dir / f"frame-{task.id}.png"
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "提取选中的视频帧..."
        task.progress = 10
        db.commit()
        await asyncio.to_thread(_extract_frame, video_path, float(metadata["frame_seconds"]), frame_path)

        service = ComfyUIService(db=db)
        style, _ = get_style(db, novel, "character")
        text_style = metadata.get("text_style", "classic")
        ratio = metadata["aspect_ratio"]
        is_wide = COVER_SIZES[ratio][0] / COVER_SIZES[ratio][1] >= 1.2
        space_for_type = {
            "classic": "toward the lower center",
            "cinematic": "on a dark wall between the central and right figures" if is_wide else "in the lower third",
            "editorial": "in the lower left" if is_wide else "in the lower quarter",
            "vintage": "in the upper middle and lower right" if is_wide else "in the upper center and lower quarter",
        }[text_style]
        prompt = (
            "Create an elegant cinematic literary cover illustration using the supplied video frame "
            "as the primary reference. Preserve its characters, setting, era and visual style. "
            "Refine composition, lighting and depth with subtle painterly detail; keep a calm, uncluttered "
            f"area {space_for_type} for editorial typography. Sophisticated book-cover design, "
            "restrained colors and clear focal point. No text, letters, symbols, logos, watermark or border."
        )
        graph = service.builder.build_shot_workflow(
            prompt=prompt, workflow_json=workflow.workflow_json, node_mapping=mapping,
            aspect_ratio=metadata["aspect_ratio"], style=style,
        )
        size = COVER_SIZES[metadata["aspect_ratio"]]
        _set_dimension(graph, mapping.get("width_node_id"), size[0])
        _set_dimension(graph, mapping.get("height_node_id"), size[1])
        reference_id = str(mapping.get("scene_reference_image_node_id") or "")
        if reference_id not in graph or not isinstance(graph[reference_id].get("inputs"), dict):
            raise ValueError("场景分镜图工作流缺少场景参考图节点映射")
        uploaded = await service.client.upload_image(str(frame_path))
        if not uploaded.get("success") or not uploaded.get("filename"):
            raise RuntimeError(uploaded.get("message") or "上传封面参考帧失败")
        graph[reference_id]["inputs"]["image"] = uploaded["filename"]
        task.current_step = "场景分镜图工作流正在生成封面画面..."
        task.progress = 35
        task.prompt_text = prompt
        db.commit()

        def queued(prompt_id: str, submitted: dict) -> None:
            task.comfyui_prompt_id = prompt_id
            task.workflow_json = json.dumps(submitted, ensure_ascii=False)
            db.commit()

        result = await service.generate_shot_image_with_workflow(
            prompt=prompt, workflow_json=workflow.workflow_json, node_mapping=mapping,
            aspect_ratio=metadata["aspect_ratio"], workflow=graph, style=style,
            on_prompt_queued=queued,
        )
        if not result.get("success") or not result.get("image_url"):
            raise RuntimeError(result.get("message") or "封面画面生成失败")
        task.current_step = "排版封面标题与署名..."
        task.progress = 85
        db.commit()
        image_url = result["image_url"]
        if image_url.startswith("/api/files/"):
            image_bytes = Path(url_to_local_path(image_url)).read_bytes()
        else:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.get(image_url)
                response.raise_for_status()
                image_bytes = response.content
        output_path = output_dir / f"cover-{task.id}.png"
        await asyncio.to_thread(_draw_cover, image_bytes, output_path, size,
                                metadata["title"], metadata["author"], metadata["production"], text_style)
        task.result_url = local_path_to_url(str(output_path))
        if not task.result_url:
            raise RuntimeError("无法生成封面访问地址")
        task.status = "completed"
        task.progress = 100
        task.current_step = "封面生成完成"
        task.completed_at = datetime.utcnow()
        task.error_message = None
        db.commit()
    except Exception as exc:
        if task:
            task.status = "failed"
            task.current_step = "封面生成失败"
            task.error_message = str(exc)
            task.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
