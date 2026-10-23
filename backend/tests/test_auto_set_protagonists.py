from app.models.novel import Character, Novel


def test_auto_set_protagonists_only_updates_matching_characters_in_selected_novel(client, db_session):
    selected = Novel(title="当前小说")
    other = Novel(title="其他小说")
    db_session.add_all([selected, other])
    db_session.flush()

    named = Character(novel_id=selected.id, name="陈胜")
    chinese_numeral = Character(novel_id=selected.id, name="秦二世")
    numbered = Character(novel_id=selected.id, name="路人1")
    full_width_numbered = Character(novel_id=selected.id, name="士兵２")
    existing_numbered = Character(novel_id=selected.id, name="随从3", is_protagonist=True)
    narrator = Character(novel_id=selected.id, name="旁白", is_narrator=True)
    other_character = Character(novel_id=other.id, name="其他主角")
    db_session.add_all([
        named, chinese_numeral, numbered, full_width_numbered,
        existing_numbered, narrator, other_character,
    ])
    db_session.commit()

    response = client.post(f"/api/characters/auto-set-protagonists?novel_id={selected.id}")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert set(response.json()["data"]["assignedIds"]) == {named.id, chinese_numeral.id}
    assert response.json()["data"]["updatedCount"] == 2
    db_session.expire_all()
    assert named.is_protagonist is True
    assert chinese_numeral.is_protagonist is True
    assert numbered.is_protagonist is False
    assert full_width_numbered.is_protagonist is False
    assert existing_numbered.is_protagonist is True
    assert narrator.is_protagonist is False
    assert other_character.is_protagonist is False

    repeated = client.post(f"/api/characters/auto-set-protagonists?novel_id={selected.id}")
    assert repeated.json()["data"]["updatedCount"] == 0
    assert set(repeated.json()["data"]["assignedIds"]) == {named.id, chinese_numeral.id}


def test_auto_set_protagonists_requires_existing_novel(client):
    response = client.post("/api/characters/auto-set-protagonists?novel_id=missing")
    assert response.status_code == 404
