import json
import zipfile
from types import SimpleNamespace

from app.services.file_storage import FileStorageService


def test_zip_chapter_materials_includes_video_director_assets(tmp_path):
    storage = FileStorageService(base_dir=str(tmp_path))
    story_dir = storage._get_story_dir("novel-12345678")
    chapter_dir = story_dir / "chapter_chapter-"
    chapter_dir.mkdir(parents=True)

    primary = chapter_dir / "primary.png"
    end_keyframe = chapter_dir / "end.png"
    clip_video = chapter_dir / "clip.mp4"
    reference = chapter_dir / "reference.png"
    for path in [primary, end_keyframe, clip_video, reference]:
        path.write_bytes(b"asset")

    plan = {
        "selected_mode": "FIRST_LAST_FRAME",
        "keyframes": [
            {"index": 1, "role": "START", "time_seconds": 0, "description": None},
            {"index": 2, "role": "END", "time_seconds": 10, "description": "end", "image_path": str(end_keyframe)},
        ],
        "clips": [
            {
                "clip_index": 1,
                "start_time": 0,
                "end_time": 10,
                "keyframe_indexes": [1, 2],
                "workflow_type": "first_last_video",
                "status": "SUCCEEDED",
                "local_path": str(clip_video),
                "reference_images": [{"label": "START", "url": str(reference)}],
            }
        ],
    }
    shot = SimpleNamespace(
        id="shot-1",
        index=1,
        duration=10,
        description="start",
        video_description="video",
        image_path=str(primary),
        video_director_plan=json.dumps(plan),
        keyframes="[]",
    )

    zip_path = storage.zip_chapter_materials("novel-12345678", "chapter-12345678", [shot])

    assert zip_path
    with zipfile.ZipFile(zip_path) as zipf:
        names = set(zipf.namelist())
        manifest = json.loads(zipf.read("manifest.json"))

    assert "shot_materials/shot_001/primary_image.png" in names
    assert "shot_materials/shot_001/keyframes/KF001_start.png" in names
    assert "shot_materials/shot_001/keyframes/KF002_end.png" in names
    assert "shot_materials/shot_001/videos/clips/C001.mp4" in names
    assert "shot_materials/shot_001/videos/clips/C001_reference_01.png" in names
    assert manifest["shots"][0]["keyframes"][0]["image_path"] == "shot_materials/shot_001/keyframes/KF001_start.png"
    assert manifest["shots"][0]["clips"][0]["video_path"] == "shot_materials/shot_001/videos/clips/C001.mp4"
