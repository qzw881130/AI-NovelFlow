from pathlib import Path

from PIL import Image

from app.utils.image_utils import merge_prop_images


class FakeFileStorage:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def _get_story_dir(self, novel_id: str) -> Path:
        story_dir = self.base_dir / novel_id
        story_dir.mkdir(parents=True, exist_ok=True)
        return story_dir

    def get_merged_props_path(self, novel_id: str, chapter_id: str, shot_number: int, prop_names: list = None) -> Path:
        save_dir = self._get_story_dir(novel_id) / f"chapter_{chapter_id[:8]}" / "merged_props"
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / f"shot_{shot_number:03d}_props.png"


def test_merge_prop_images_creates_labeled_reference_image(tmp_path):
    prop_a = tmp_path / "basket.png"
    prop_b = tmp_path / "hat.png"
    Image.new("RGB", (32, 24), (255, 0, 0)).save(prop_a)
    Image.new("RGB", (24, 32), (0, 0, 255)).save(prop_b)

    merged_path = merge_prop_images(
        "novel-1",
        "chapter-12345678",
        2,
        [("篮子", str(prop_a)), ("红帽子", str(prop_b))],
        FakeFileStorage(tmp_path / "storage"),
    )

    assert merged_path is not None
    merged_file = Path(merged_path)
    assert merged_file.exists()
    assert merged_file.parent.name == "merged_props"

    merged = Image.open(merged_file)
    assert merged.width > 32
    assert merged.height > 32
