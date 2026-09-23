"""Prop existence and visual-reference eligibility policy."""
import re

from app.models.novel import Prop
from app.constants.prop import PROP_EXISTENCE_REAL, PROP_EXISTENCE_NONEXISTENT, PROP_EXISTENCE_VALUES


def normalize_prop_existence(value, description: str = "", appearance: str = "") -> str:
    normalized = str(value or "").strip().upper()
    if normalized in PROP_EXISTENCE_VALUES:
        return normalized
    text = f"{description or ''} {appearance or ''}"
    if re.search(r"(?:实际|事实上|本身)?(?:并)?不存在|虚构(?:的)?(?:物品|道具|布料|衣服)|仅(?:存在于|是)谎言|骗局中虚构", text):
        return PROP_EXISTENCE_NONEXISTENT
    return PROP_EXISTENCE_REAL


def is_prop_visual_eligible(prop: Prop | None) -> bool:
    return bool(prop and (prop.existence or PROP_EXISTENCE_REAL) == PROP_EXISTENCE_REAL)


def get_visual_prop_names(db, novel_id: str, names: list[str]) -> list[str]:
    if not names:
        return []
    props = db.query(Prop).filter(
        Prop.novel_id == novel_id,
        Prop.name.in_(names),
        Prop.existence == PROP_EXISTENCE_REAL,
    ).all()
    eligible = {prop.name for prop in props}
    return [name for name in names if name in eligible]


def invalidate_nonexistent_prop_references(db, novel_id: str) -> None:
    from app.models.novel import Chapter
    from app.models.shot import Shot

    db.query(Shot).filter(
        Shot.chapter_id.in_(db.query(Chapter.id).filter(Chapter.novel_id == novel_id))
    ).update({Shot.merged_prop_image: None}, synchronize_session=False)
