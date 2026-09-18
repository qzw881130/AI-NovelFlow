import json
from app.schemas.chapter_shot_split import parse_output
from app.services.chapter_scope import validate_plan
from app.services.narration_coverage import validate_coverage


def story(parts=None):
    parts = parts or [('阿青说：','VISUAL'), ('“先开门。”','DIALOGUE'), ('阿青说：','VISUAL'), ('“再关窗。”','DIALOGUE')]
    text = ''.join(p[0] for p in parts)
    basis = {'source': {'content': text, 'title': '独立审计', 'hash': 'read-only-probe'},
        'scope': {'characters': {'bindings': [{'name': '阿青', 'assetId': 'a'}]},
                  'scenes': {'bindings': [{'name': '门厅', 'assetId': 's'}]}, 'props': {'bindings': []}},
        'appearance_boundaries': [{'name': '阿青', 'segments': [{'start': 0, 'end': len(text), 'logical_status': 'BASE'}]}]}
    shot = {'id': 1, 'source_evidence': [{'text': text}],
        'description': 'Scene: 门厅\nCharacters:\n- 阿青: 中央站立\nAction: 静立',
        'video_description': '阿青在门厅中行动。', 'characters': ['阿青'], 'scene': '门厅', 'props': [],
        'duration': 8, 'continuity_mode': 'NORMAL', 'dialogues': [], 'audio_events': [], 'source_treatments': []}
    cursor = 0
    for index, part in enumerate(parts):
        value, kind = part[:2]; key = part[2] if len(part)>2 else 't'+str(index)
        evidence = {'text': value}
        if cursor:evidence['context_before']=text[:cursor]
        if cursor+len(value)<len(text):evidence['context_after']=text[cursor+len(value):]
        cursor += len(value)
        treatment = next((t for t in shot['source_treatments'] if t['key']==key), None)
        if treatment is None:
            treatment = {'key': key, 'type': 'NARRATION' if kind=='INNER_MONOLOGUE' else kind,
                         'source_evidence': [], 'visual_targets': ['description']}
            if kind in {'NARRATION','INNER_MONOLOGUE'}: treatment['audio_type']=kind
            shot['source_treatments'].append(treatment)
        treatment['source_evidence'].append(evidence)
        if kind!='VISUAL':
            spoken=value[1:-1] if kind in {'DIALOGUE','INNER_MONOLOGUE'} and value.startswith('“') else value
            shot['audio_events'].append({'order':len(shot['audio_events'])+1, 'type':kind, 'treatment_ref':key,
                'voice_owner':'旁白' if kind=='NARRATION' else '阿青', 'visible_speaker':'阿青' if kind=='DIALOGUE' else None,
                'requires_visible_lipsync':kind=='DIALOGUE', 'text':spoken, 'emotion_prompt':'自然', 'pause_after':'NONE'})
    project_dialogues(shot)
    return {'chapter':'独立审计','characters':['阿青'],'scenes':['门厅'],'props':[], 'unresolved_assets':[], 'shots':[shot]},basis


def project_dialogues(shot):
    for index,e in enumerate(shot['audio_events'],1):e['order']=index
    shot['dialogues']=[{'order':i,'character_name':e['voice_owner'],'text':e['text'],'emotion_prompt':e['emotion_prompt']}
                      for i,e in enumerate((e for e in shot['audio_events'] if e['type']=='DIALOGUE'),1)]


def full_validate(candidate,basis):
    parsed=parse_output(json.dumps(candidate,ensure_ascii=False));validate_plan(parsed,basis)
    report=validate_coverage(parsed,basis);assert report['status']=='PASS',report
    return report
