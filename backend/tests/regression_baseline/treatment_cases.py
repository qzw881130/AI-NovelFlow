"""Explicit editorial fixtures, never an independent narration classifier."""
from copy import deepcopy
from test_chapter_shot_split import output


def director_output(*, narration=False, inner=False):
    data=deepcopy(output())
    opening, speech=data['shots']
    opening['source_treatments']=[{'key':'opening','type':'NARRATION' if narration or inner else 'VISUAL',
        'source_evidence':deepcopy(opening['source_evidence']),'visual_targets':['description']}]
    if narration or inner:
        kind='INNER_MONOLOGUE' if inner else 'NARRATION'
        opening['source_treatments'][0]['audio_type']=kind
        opening['audio_events']=[{'order':1,'treatment_ref':'opening','type':kind,'voice_owner':'刘备' if inner else '旁白',
            'visible_speaker':None,'requires_visible_lipsync':False,'text':opening['source_evidence'][0]['text'],
            'emotion_prompt':'平静','pause_after':'NONE'}]
    speech['source_treatments']=[
        {'key':'action','type':'VISUAL','source_evidence':[{'text':'刘备披甲，说：'}],'visual_targets':['video_description']},
        {'key':'speech','type':'DIALOGUE','source_evidence':[{'text':'“出发！”'}]},
    ]
    speech['audio_events'][0]['treatment_ref']='speech'
    return data
