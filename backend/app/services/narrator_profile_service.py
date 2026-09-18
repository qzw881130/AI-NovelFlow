"""The existing Book narrator is an audio role, independent of visual asset bindings."""
from fastapi import HTTPException
from app.models.novel import Character, Novel


def ensure_narrator(db, novel_id):
    # Callers own the surrounding transaction and publication fence.
    profiles = db.query(Character).filter_by(novel_id=novel_id, is_narrator=True).all()
    if len(profiles) > 1:
        raise HTTPException(409, {'code': 'NARRATOR_PROFILE_AMBIGUOUS', 'novelId': novel_id})
    if profiles:
        return profiles[0]
    if not db.get(Novel, novel_id):
        raise HTTPException(404, '小说不存在')
    profile = Character(novel_id=novel_id, name='旁白', is_narrator=True,
                        description='小说旁白角色，用于生成旁白音频')
    db.add(profile)
    db.flush()
    return profile
