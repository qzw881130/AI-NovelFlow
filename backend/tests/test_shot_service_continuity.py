from app.models.novel import Chapter, Novel
from app.services.shot_service import ShotService


def test_create_shots_from_parsed_data_preserves_continuity_mode(db_session):
    novel = Novel(title="continuity import")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.commit()

    shots = ShotService(db_session).create_shots_from_parsed_data(chapter.id, [
        {"duration": 75, "continuity_mode": "CONTINUOUS_TAKE"},
        {"duration": 8},
    ])

    assert shots[0]["continuity_mode"] == "CONTINUOUS_TAKE"
    assert shots[1]["continuity_mode"] == "NORMAL"
