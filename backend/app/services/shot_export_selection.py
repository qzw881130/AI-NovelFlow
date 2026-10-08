"""Filter Shot package entries before reading media into the ZIP."""
import json
from copy import deepcopy

SHOT_EXPORT_SECTIONS = frozenset({
    "primary_image", "visual_states", "characters", "scenes", "props",
    "clip_videos", "final_video", "reference_images", "prompts", "workflows", "plan",
})


def export_section(path):
    if path.startswith(("shot/", "frames/start", "frames/主分镜图")):
        return "primary_image"
    if path.startswith(("visual_states/", "frames/keyframes/")):
        return "visual_states"
    for section, prefixes in {
        "characters": ("resources/characters/", "characters/"),
        "scenes": ("resources/scenes/", "scene/"),
        "props": ("resources/props/", "props/"),
    }.items():
        if path.startswith(prefixes):
            return section
    if path.startswith("final/"):
        return "final_video"
    if path.startswith("prompts/") or path.endswith("submitted_prompt.txt"):
        return "prompts"
    if path.startswith("workflows/") or path.endswith("submitted_workflow.json"):
        return "workflows"
    if any(part in path for part in ("ordinary_references/", "temporal_anchors/", "videos/references/")):
        return "reference_images"
    if path.startswith("execution/clips/") and "/artifact." in path:
        return "clip_videos"
    return None


class SelectedShotArchive:
    def __init__(self, archive, sections):
        self.archive = archive
        self.sections = set(sections)

    def allowed(self, path):
        return path == "manifest.json" or export_section(path) in self.sections

    def write(self, filename, arcname):
        if self.allowed(arcname):
            self.archive.write(filename, arcname)

    def writestr(self, name, content):
        if name == "manifest.json":
            content = json.dumps(self.filter_manifest(json.loads(content)), ensure_ascii=False, indent=2)
        if self.allowed(name):
            self.archive.writestr(name, content)

    def filter_manifest(self, original):
        manifest = deepcopy(original)
        manifest["selected_sections"] = sorted(self.sections)
        # Never leave an archive path pointing at a deselected file.
        def prune(value):
            if isinstance(value, list):
                return [prune(item) for item in value]
            if not isinstance(value, dict):
                return value
            result = {}
            for key, item in value.items():
                if key.endswith("path") and isinstance(item, str) and not self.allowed(item):
                    result[key] = None
                else:
                    result[key] = prune(item)
            if value.get("path") and result.get("path") is None:
                result["status"] = "NOT_SELECTED"
            if "plan" not in self.sections:
                result.pop("description", None)
                result.pop("video_description", None)
            return result
        manifest = prune(manifest)
        if "resources" in manifest:
            manifest["resources"] = {key: rows for key, rows in manifest["resources"].items() if key in self.sections}
        plan = manifest.get("canonical_plan")
        if plan is not None and "plan" not in self.sections:
            for key in ("transitions", "semantic_clips", "clip_plan_validation"):
                plan.pop(key, None)
            if "visual_states" not in self.sections:
                plan.pop("visual_states", None)
        if "final_video" not in self.sections and "final_assembly" in manifest:
            manifest["final_assembly"] = {"status": "NOT_SELECTED", "path": None}
        if not self.sections & {"clip_videos", "reference_images", "prompts", "workflows"}:
            manifest["execution"] = {"clips": []}
        # Historical packages list assets/workflows directly.
        for key in ("assets", "workflows"):
            if isinstance(manifest.get(key), list):
                manifest[key] = [item for item in manifest[key] if item.get("path")]
        return manifest
