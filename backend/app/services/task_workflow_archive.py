"""Package a submitted task workflow with its persisted local references."""

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.services.file_storage import file_storage


def _local_reference_path(url: str) -> Path:
    if not isinstance(url, str):
        raise ValueError("参考文件地址无效")
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/api/files/"):
        raise ValueError("参考文件不是本地文件")
    base = file_storage.base_dir.resolve()
    relative = unquote(parsed.path[len("/api/files/"):])
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValueError("参考文件路径无效")
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path


def _safe_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(value or fallback)).strip(" ._")
    return cleaned[:80] or fallback


def build_workflow_archive(task_id: str, data: dict) -> FileResponse:
    workflow = data.get("workflow")
    if not workflow:
        raise HTTPException(status_code=409, detail="该任务尚未保存工作流 JSON")
    if isinstance(workflow, str):
        workflow_text = workflow
    else:
        workflow_text = json.dumps(workflow, ensure_ascii=False, indent=2)

    images = data.get("referenceImages") or []
    video = data.get("referenceVideo")
    references = []
    try:
        for index, image in enumerate(images, 1):
            if not isinstance(image, dict) or not image.get("url"):
                raise ValueError(f"第 {index} 张参考图缺少文件地址")
            source = _local_reference_path(image["url"])
            label = _safe_part(image.get("label"), f"Picture_{index}")
            archive_path = f"references/images/{index:02d}_{label}_{_safe_part(source.stem, 'image')}{source.suffix}"
            references.append((source, archive_path, image["url"], image.get("label") or f"Picture {index}"))
        if video:
            source = _local_reference_path(video)
            archive_path = f"references/video/{_safe_part(source.name, 'reference_video.mp4')}"
            references.append((source, archive_path, video, "参考视频"))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=f"无法完整打包工作流参考文件：{exc}") from exc

    result_image = data.get("resultImage")
    outputs = []
    if result_image:
        try:
            source = _local_reference_path(result_image)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=409, detail=f"无法打包生成图片：{exc}") from exc
        outputs.append((source, f"outputs/generated_image{source.suffix or '.png'}", result_image))

    manifest = {
        "taskId": task_id,
        "windowIndex": data.get("windowIndex"),
        "references": [
            {"label": label, "sourceUrl": url, "archivePath": archive_path}
            for _, archive_path, url, label in references
        ],
        "outputs": [
            {"label": "生成图片", "sourceUrl": url, "archivePath": archive_path}
            for _, archive_path, url in outputs
        ],
    }
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="novelflow-workflow-", suffix=".zip", delete=False) as temporary:
            temp_path = temporary.name
        with ZipFile(temp_path, "w") as archive:
            archive.writestr("workflow.json", workflow_text, compress_type=ZIP_DEFLATED)
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2), compress_type=ZIP_DEFLATED)
            for source, archive_path, _, _ in references:
                archive.write(source, archive_path, compress_type=ZIP_STORED)
            for source, archive_path, _ in outputs:
                archive.write(source, archive_path, compress_type=ZIP_STORED)
    except Exception:
        if temp_path:
            os.unlink(temp_path)
        raise

    suffix = f"_clip_{data['windowIndex']}" if data.get("windowIndex") is not None else ""
    background = BackgroundTasks()
    background.add_task(os.unlink, temp_path)
    return FileResponse(
        temp_path, media_type="application/zip", background=background,
        filename=f"workflow_{task_id}{suffix}.zip",
    )
