import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.models.novel import Novel,Character
from app.models.prompt_template import PromptTemplate
from app.api.characters import router
from test_chapter_asset_parse import db_session


def client(db):
    app=FastAPI();app.include_router(router,prefix='/api/characters')
    app.dependency_overrides[get_db]=lambda:db
    return TestClient(app,raise_server_exceptions=False)


def actor(db,*,narrator=False,appearance=None):
    book=Novel(title='R2 F17 prompt applicability')
    template=PromptTemplate(name='R2 portrait fixture',type='character',template='portrait, {appearance}, ##STYLE##',is_system=True,is_active=True)
    db.add(template);db.flush();book.prompt_template_id=template.id
    value=Character(novel=book,name='旁白' if narrator else '阿青',is_narrator=narrator,appearance=appearance,
                    voice_prompt='清晰沉稳的叙述声音。')
    db.add(book);db.add(value);db.commit();return value


def test_f17_obs001_audio_only_narrator_has_explicit_visual_non_applicability(db_session):
    value=actor(db_session,narrator=True)
    before=value.appearance
    for _ in range(2):
        response=client(db_session).get('/api/characters/'+value.id+'/prompt')
        assert response.status_code==200,response.text
        assert response.json()['data']['applicable'] is False
        assert response.json()['data']['reason']=='AUDIO_ONLY_NARRATOR'
    db_session.refresh(value);assert value.appearance==before and not value.appearance
    assert value.voice_prompt=='清晰沉稳的叙述声音。'


def test_visible_character_still_gets_visual_prompt(db_session):
    value=actor(db_session,appearance='成年男子，蓝色长衫，全身站立。')
    response=client(db_session).get('/api/characters/'+value.id+'/prompt')
    assert response.status_code==200,response.text
    assert value.appearance in response.json()['data']['prompt']


def test_visible_character_without_appearance_is_explicitly_rejected(db_session):
    value=actor(db_session)
    response=client(db_session).get('/api/characters/'+value.id+'/prompt')
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='CHARACTER_APPEARANCE_REQUIRED'
