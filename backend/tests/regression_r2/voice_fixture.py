"""Formal two-Chapter authoring fixture; upstream responses explicitly use test provider.

This seeds lawful source/Binding/Revision data only. Voice Design/TTS are later
invoked through the actual application API/worker and real configured ComfyUI.
"""
import asyncio
from copy import deepcopy
from pathlib import Path
from app.models.novel import Novel,Chapter,Character,Scene
from app.models.shot import Shot
from app.models.prompt_template import PromptTemplate
from app.models.asset_resolution import ChapterCharacterBinding
from app.services.appearance_timeline_service import AppearanceTimelineService
from app.services.chapter_shot_split_service import ChapterShotSplitService
from app.services.chapter_governance import require_source
from test_appearance_timeline import prepare
from test_asset_resolution import extract,resolve
from test_chapter_shot_split import LLM


def seed(db):
    book=Novel(title='R2-V live voice acceptance · labeled source fixture')
    db.add(book);db.commit()
    template=db.query(PromptTemplate).filter_by(type='chapter_split',is_system=True,is_active=True).first()
    assert template
    book.chapter_split_prompt_template_id=template.id;db.commit()
    result={'novelId':book.id,'chapters':[],'upstreamProvider':'test','upstreamPurpose':'SOURCE_FIXTURE_ONLY'}
    for number,text in [(1,'夜色渐深，阿青站在门厅。'),(2,'天色微明，阿青仍站在门厅。')]:
        chapter=Chapter(novel_id=book.id,number=number,title=f'R2 Voice验收第{number}章',content=text)
        db.add(chapter);db.commit();prepare(db,chapter,text,name='阿青')
        scene=db.query(Scene).filter_by(novel_id=book.id,name='门厅').first()
        if not scene:db.add(Scene(novel_id=book.id,name='门厅',setting='安静门厅'));db.commit()
        extract(db,chapter,[{'name':'门厅','description':'门厅','setting':'安静门厅','source_evidence':[{'text':'门厅'}]}],'scenes')
        assert resolve(db,chapter,kinds=['scenes'])['success']
        extract(db,chapter,[],'props');assert resolve(db,chapter,kinds=['props'])['success']
        assert AppearanceTimelineService(db).build(book.id,chapter.id)['success']
        plan={'chapter':chapter.title,'characters':['阿青'],'scenes':['门厅'],'props':[],'unresolved_assets':[],
            'shots':[{'id':1,'source_evidence':[{'text':text}],
                'description':'Scene: 门厅\nCharacters:\n- 阿青: 中央站立\nAction: 静立',
                'video_description':'阿青静静站立，只有画外旁白。','characters':['阿青'],'scene':'门厅','props':[],
                'duration':8,'continuity_mode':'NORMAL','dialogues':[],
                'source_treatments':[{'key':'n','type':'NARRATION','audio_type':'NARRATION','source_evidence':[{'text':text}],'visual_targets':['description']}],
                'audio_events':[{'order':1,'type':'NARRATION','treatment_ref':'n','voice_owner':'旁白','visible_speaker':None,
                    'requires_visible_lipsync':False,'text':text,'emotion_prompt':'自然','pause_after':'NONE'}]}]}
        split=asyncio.run(ChapterShotSplitService(db,LLM(db,plan)).split(book.id,chapter.id));assert split['success'],split
        shot=db.query(Shot).filter_by(chapter_id=chapter.id).one();require_source(db,shot.id)
        result['chapters'].append({'id':chapter.id,'shotId':shot.id,'text':text,'split':split['data']})
    narrators=db.query(Character).filter_by(novel_id=book.id,is_narrator=True).all();assert len(narrators)==1
    narrator=narrators[0];assert not narrator.voice_prompt and not narrator.reference_audio_url and not narrator.appearance
    assert not db.query(ChapterCharacterBinding).filter_by(character_id=narrator.id).count()
    result['narratorId']=narrator.id
    return result
