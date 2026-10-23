"""Provider image inputs and compact logs of the final wire payload."""
import base64
import copy
import hashlib
import io
from pathlib import Path

from PIL import Image


def attach_image_inputs(body, provider, images):
    if not images:
        return body
    urls = [item["url"] for item in images]
    if provider == "gemini":
        parts = body["contents"][0]["parts"]
        for url in urls:
            mime, data = _data_image(url)
            parts.append({"inline_data": {"mime_type": mime, "data": data}})
    elif provider == "anthropic":
        system = body["messages"][0]["content"]
        text = body["messages"][1]["content"]
        body["system"] = system
        content = [{"type": "text", "text": text}]
        for url in urls:
            if url.startswith("data:"):
                mime, data = _data_image(url)
                content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
            else:
                content.append({"type": "image", "source": {"type": "url", "url": url}})
        body["messages"] = [{"role": "user", "content": content}]
    else:
        user = next(m for m in body["messages"] if m["role"] == "user")
        user["content"] = [{"type": "text", "text": user["content"]}] + [
            {"type": "image_url", "image_url": {"url": url}} for url in urls
        ]
    return body


def _data_image(url):
    header, data = url.split(",", 1)
    if not header.startswith("data:image/") or not header.endswith(";base64"):
        raise ValueError("图片接口需要 base64 data URI")
    return header[5:-7], data


def capture_image_inputs(payload, metadata=None):
    """Inspect the actual final provider body, persist its submitted bytes, redact base64.

    Business metadata only annotates images that are really present in this payload.
    Original request objects are never mutated by logging.
    """
    from app.services.file_storage import file_storage

    logged = copy.deepcopy(payload)
    items = []

    def capture(url):
        index = len(items)
        extra = (metadata or [])[index] if index < len(metadata or []) else {}
        item = {**extra, "request_order": index + 1, "logical_id": extra.get("logical_id") or f"Image{index + 1}",
                "status": "available", "submitted_url": None}
        if url.startswith("data:"):
            try:
                mime, encoded = _data_image(url)
                data = base64.b64decode(encoded, validate=True)
                digest = hashlib.sha256(data).hexdigest()
                with Image.open(io.BytesIO(data)) as image:
                    dimensions = list(image.size)
                extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime, "img")
                directory = Path(file_storage.base_dir) / "_llm_inputs"
                directory.mkdir(parents=True, exist_ok=True)
                destination = directory / f"{digest}.{extension}"
                if not destination.exists():
                    destination.write_bytes(data)
                preview = f"/api/files/_llm_inputs/{destination.name}"
                item.update(submitted_url=preview, mime_type=mime, size_bytes=len(data), sha256=digest,
                            submitted_dimensions=dimensions)
            except Exception as error:
                item.update(status="unavailable", unavailable_reason=str(error))
        else:
            item.update(submitted_url=url, submitted_as="remote_url")
        items.append(item)
        return {"image_input_order": index + 1, "submitted_url": item["submitted_url"], "base64_omitted": True}

    def walk(value):
        if isinstance(value, list):
            for element in value:
                walk(element)
        elif isinstance(value, dict):
            if value.get("type") == "image_url":
                image_url = value.get("image_url", {})
                url = image_url.get("url") if isinstance(image_url, dict) else image_url
                if url:
                    value["image_url"] = capture(url)
            elif value.get("type") == "image" and isinstance(value.get("source"), dict):
                source = value["source"]
                url = (f"data:{source.get('media_type')};base64,{source.get('data')}"
                       if source.get("type") == "base64" else source.get("url"))
                if url:
                    value["source"] = capture(url)
            elif "inline_data" in value or "inlineData" in value:
                key = "inline_data" if "inline_data" in value else "inlineData"
                source = value[key]
                mime = source.get("mime_type") or source.get("mimeType")
                if str(mime).startswith("image/"):
                    value[key] = capture(f"data:{mime};base64,{source['data']}")
            else:
                for element in value.values():
                    walk(element)

    walk(logged)
    return logged, items


def log_image_inputs(request_info):
    if not request_info:
        return []
    import json
    try:
        parsed = json.loads(request_info) if isinstance(request_info, str) else request_info
        return parsed.get("imageInputs") or []
    except (TypeError, ValueError, AttributeError):
        return []
