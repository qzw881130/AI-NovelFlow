"""Deterministic asset candidates for ordinary video references (no selection LLM)."""
import os
from pathlib import Path

from app.models.novel import Character, Scene, Prop
from app.services.prop_policy import get_visual_prop_names
from app.services.video_director_ai import _clip_visible_characters, _dialogue_speaker, safe_json_list
from app.utils.path_utils import url_to_local_path


def resolve_video_reference_resources(db, novel_id: str, shot, keyframes: list, transitions: list, clip: dict) -> dict:
    """Resolve optional assets; the compiler packs these after owned-state anchors."""
    references, skipped = [], []

    def add(model, kind, name):
        asset = db.query(model).filter(model.novel_id == novel_id, model.name == name).order_by(model.id).first()
        reason = None
        if not asset:
            reason = "ASSET_NOT_FOUND"
        elif kind == "CHARACTER_IDENTITY" and asset.is_narrator:
            reason = "NARRATOR_NOT_VISUAL"
        elif not asset.image_url:
            reason = "IMAGE_MISSING"
        else:
            path = url_to_local_path(asset.image_url) or asset.image_url
            if not Path(path).is_file() or not os.access(path, os.R_OK):
                reason = "IMAGE_UNRESOLVABLE"
        identity = {"kind": kind, "source_name": name, "source_id": asset.id if asset else None}
        if reason:
            skipped.append({**identity, "reason": reason})
            return
        references.append({
            **identity, "source_type": f"{model.__name__.upper()}_ASSET",
            "source_identity": {"asset_id": asset.id, "name": asset.name},
            "image_url": asset.image_url, "local_path": str(Path(path).resolve()),
        })

    if shot.scene:
        add(Scene, "SCENE", shot.scene)
    visible = list(dict.fromkeys(_clip_visible_characters(keyframes, safe_json_list(shot.characters))))
    speakers = {
        _dialogue_speaker(item) for item in clip.get("dialogue_assignment") or [] if isinstance(item, dict)
    }
    # Existing canonical descriptions do not expose a reliable motion-priority field.
    for name in sorted(visible, key=lambda name: name not in speakers):
        add(Character, "CHARACTER_IDENTITY", name)

    descriptions = "\n".join(str(item.get("description") or item.get("transition_description") or "") for item in keyframes + transitions)
    # Shot bindings bound the candidate set; owned states/projected transitions establish relevance.
    names = list(dict.fromkeys(name for name in safe_json_list(shot.props) if name and name in descriptions))
    names.sort(key=descriptions.index)
    eligible = set(get_visual_prop_names(db, novel_id, names))
    for name in names:
        if name in eligible:
            add(Prop, "PROP", name)
        else:
            skipped.append({"kind": "PROP", "source_name": name, "reason": "NOT_VISUAL_ELIGIBLE"})
    return {"references": references, "skipped_references": skipped}
