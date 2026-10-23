"""The chapter list reports a split only while saved split data and shots exist."""

from app.models.novel import Chapter, Novel
from app.models.shot import Shot


def test_chapter_list_ai_split_status_tracks_saved_data(client, db_session):
    novel = Novel(id="split-status-novel", title="Novel")
    chapter = Chapter(id="split-status-chapter", novel_id=novel.id, number=1, title="Chapter")
    db_session.add_all([novel, chapter])
    db_session.commit()

    url = f"/api/novels/{novel.id}/chapters"
    def split_status():
        response = client.get(url)
        assert response.status_code == 200
        return response.json()["data"][0]["aiSplitCompleted"]

    assert split_status() is False

    db_session.add(Shot(id="split-status-shot", chapter_id=chapter.id, index=1, duration=10))
    db_session.commit()
    assert split_status() is False

    chapter.parsed_data = '{"chapter":"Chapter","characters":[],"scenes":[],"props":[]}'
    db_session.commit()
    assert split_status() is True

    db_session.delete(db_session.get(Shot, "split-status-shot"))
    db_session.commit()
    assert split_status() is False
