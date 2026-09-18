"""Canonical ordered inline-image input, deterministic preflight and safe evidence.

The business input remains OpenAI-style text/image_url parts. Provider adapters
own native wire conversion. Logs retain image identity, never raw base64/keys.
"""
import base64
import binascii
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import re

from PIL import Image

CONTRACT = "inline-images-v1"
MIMES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}
# Same source-image budgets as RSA; animated references are not this contract.
MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 20_000_000
MODEL_PROFILES = {
    "deepseek": {"deepseek-v4-flash-vision-exp"},
    "openai": {"gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-4-turbo"},
    "gemini": {"gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"},
}


class MultimodalInputError(ValueError):
    pass


def image_data(url):
    if not isinstance(url, str):
        raise MultimodalInputError("MULTIMODAL_IMAGE_URL_INVALID")
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=]+)", url)
    if not match:
        raise MultimodalInputError("MULTIMODAL_INLINE_DATA_REQUIRED")
    if len(match[2]) > (MAX_BYTES + 2) // 3 * 4:
        raise MultimodalInputError("MULTIMODAL_IMAGE_TOO_LARGE")
    try:
        raw = base64.b64decode(match[2], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise MultimodalInputError("MULTIMODAL_IMAGE_ENCODING_INVALID") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise MultimodalInputError("MULTIMODAL_IMAGE_TOO_LARGE_OR_EMPTY")
    try:
        with Image.open(BytesIO(raw)) as image:
            mime, (width, height) = MIMES.get(image.format), image.size
            if mime != match[1]:
                raise MultimodalInputError("MULTIMODAL_IMAGE_MIME_MISMATCH")
            if width * height > MAX_PIXELS:
                raise MultimodalInputError("MULTIMODAL_IMAGE_PIXEL_LIMIT")
            if getattr(image, "n_frames", 1) != 1:
                raise MultimodalInputError("MULTIMODAL_ANIMATED_IMAGE_UNSUPPORTED")
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image.load()
    except MultimodalInputError:
        raise
    except Exception as exc:
        raise MultimodalInputError("MULTIMODAL_IMAGE_BYTES_INVALID") from exc
    return raw, {
        "mime_type": match[1], "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "width": width, "height": height,
    }


def inspect_content(content):
    if isinstance(content, str):
        return []
    if not isinstance(content, list) or not content:
        raise MultimodalInputError("MULTIMODAL_CONTENT_INVALID")
    images = []
    for index, part in enumerate(content):
        if not isinstance(part, dict):
            raise MultimodalInputError("MULTIMODAL_PART_INVALID")
        if part.get("type") == "text":
            if set(part) != {"type", "text"} or not isinstance(part["text"], str):
                raise MultimodalInputError("MULTIMODAL_TEXT_INVALID")
        elif part.get("type") == "image_url":
            image = part.get("image_url")
            if (set(part) != {"type", "image_url"} or not isinstance(image, dict)
                    or set(image) - {"url", "detail"}):
                raise MultimodalInputError("MULTIMODAL_IMAGE_PART_INVALID")
            detail = image.get("detail", "auto")
            if not isinstance(detail, str) or detail not in {"auto", "low", "high"}:
                raise MultimodalInputError("MULTIMODAL_IMAGE_DETAIL_INVALID")
            _, info = image_data(image.get("url"))
            images.append({"part_index": index, "picture_index": len(images) + 1, **info})
        else:
            raise MultimodalInputError("MULTIMODAL_PART_UNSUPPORTED")
    return images


def model_image_capability(config):
    """A declared capability is not evidence of a successful external call."""
    explicit = getattr(config, "image_input", None)
    if explicit is not None:
        return {"supported": explicit is True, "declaration": "EXPLICIT_PROCESS_CONFIGURATION"}
    supported = config.model in MODEL_PROFILES.get(config.provider, set())
    return {"supported": supported, "declaration": "KNOWN_MODEL_PROFILE" if supported else "MODEL_UNDECLARED_OR_TEXT_ONLY"}


def preflight(config, content, wire):
    images = inspect_content(content)
    if images:
        if wire not in {"openai-chat", "gemini-parts"}:
            raise MultimodalInputError("MULTIMODAL_PROVIDER_UNSUPPORTED: " + config.provider)
        if not model_image_capability(config)["supported"]:
            raise MultimodalInputError("MULTIMODAL_MODEL_CAPABILITY_UNDECLARED: " + config.model)
        if wire == "gemini-parts" and any(content[i["part_index"]]["image_url"].get("detail", "auto") != "auto" for i in images):
            raise MultimodalInputError("MULTIMODAL_IMAGE_DETAIL_UNSUPPORTED")
    return images


def canonical_log(content):
    if isinstance(content, str):
        return content
    logged = deepcopy(content)
    for image in inspect_content(content):
        part = logged[image["part_index"]]
        part["image_url"]["url"] = "[image omitted]"
        part["image_evidence"] = image
    return json.dumps(logged, ensure_ascii=False)


def native_content(content, wire):
    if wire == "openai-chat":
        return deepcopy(content)
    if wire != "gemini-parts":
        raise MultimodalInputError("MULTIMODAL_PROVIDER_UNSUPPORTED")
    parts = []
    for part in ([{"type": "text", "text": content}] if isinstance(content, str) else content):
        if part["type"] == "text":
            parts.append({"text": part["text"]})
        else:
            header, encoded = part["image_url"]["url"].split(",", 1)
            parts.append({"inlineData": {"mimeType": header[5:].split(";", 1)[0], "data": encoded}})
    return parts


def redacted_wire(value):
    if isinstance(value, list):
        return [redacted_wire(item) for item in value]
    if isinstance(value, dict):
        if "mimeType" in value and "data" in value and str(value["mimeType"]).startswith("image/"):
            return {**value, "data": "[image omitted]"}
        return {key: redacted_wire(item) for key, item in value.items()}
    if isinstance(value, str) and value.startswith("data:image/"):
        return "[image omitted]"
    return value


def json_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def wire_evidence(config, content, body, wire):
    images = inspect_content(content)
    if not images:
        return None
    return {
        "contract": CONTRACT, "wire_format": wire, "provider": config.provider, "model": config.model,
        "model_capability": model_image_capability(config), "images": images,
        "canonical_sha256": json_digest(json.loads(canonical_log(content))),
        "wire_payload_sha256": json_digest(body), "wire_payload_digest_encoding": "canonical-json-utf8",
    }


def verify_logged_request(log, content):
    """Rebuild native request from actual frozen image bytes, not a claimed hash.

    Only the explicitly tagged new contract uses this verifier. Historical logs are
    not upgraded or re-signed, and current configuration cannot reinterpret a receipt.
    """
    try:
        info = json.loads(log.request_info)
        evidence = info["multimodal"]
        wire = evidence["wire_format"]
        logged = json.loads(canonical_log(content))
        if (evidence["contract"] != CONTRACT or evidence["provider"] != log.provider
                or evidence["model"] != log.model or info["provider"] != log.provider or info["model"] != log.model
                or evidence["model_capability"]["supported"] is not True
                or evidence["images"] != inspect_content(content)
                or json.loads(log.user_prompt) != logged
                or evidence["canonical_sha256"] != json_digest(logged)
                or evidence["wire_payload_digest_encoding"] != "canonical-json-utf8"):
            raise ValueError("canonical image evidence differs")
        body = deepcopy(info["payload"])
        native = native_content(content, wire)
        if wire == "openai-chat":
            if body["model"] != log.model:
                raise ValueError("wire model differs")
            body["messages"] = [{"role": "system", "content": log.system_prompt}, {"role": "user", "content": native}]
        else:
            body["systemInstruction"] = {"parts": [{"text": log.system_prompt}]}
            body["contents"] = [{"role": "user", "parts": native}]
        if redacted_wire(body) != info["payload"] or json_digest(body) != evidence["wire_payload_sha256"]:
            raise ValueError("native wire differs")
        return evidence
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise MultimodalInputError("MULTIMODAL_LOG_PROOF_MISMATCH") from exc
