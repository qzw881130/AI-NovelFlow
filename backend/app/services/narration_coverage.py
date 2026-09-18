"""Pure Source Treatment validator. No LLM, ORM, profile creation, repair or writes.

Treatment.NARRATION means narrative vocal expression. AudioEvent.NARRATION is
Book Narrator; explicit INNER_MONOLOGUE remains Character internal voice.
VISUAL targets prove declared attribution only, never visual semantic quality.
"""
from copy import deepcopy
import hashlib
import json
from app.services.source_speech import direct_speech_matches

VERSION = 'shot-source-treatment-v1'
VISUAL_FIELDS = {'description', 'video_description'}
QUOTE_PAIRS = {'“':'”', '"':'"', '‘':'’', '「':'」', '『':'』'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def locate(text, evidence, domains):
    """Exact, uniquely located evidence. Context qualifies a match; it does not own extra text."""
    ranges=[]
    for item in evidence or []:
        value=item.get('text') if isinstance(item,dict) else None
        if not isinstance(value,str) or not value:
            raise ValueError('TREATMENT_SOURCE_NOT_FOUND')
        candidates=[];cursor=0
        while True:
            start=text.find(value,cursor)
            if start<0:break
            end=start+len(value);cursor=start+1
            if not any(left<=start and end<=right for left,right in domains):continue
            before,after=item.get('context_before'),item.get('context_after')
            if before is not None and (not isinstance(before,str) or text[max(0,start-len(before)):start]!=before):continue
            if after is not None and (not isinstance(after,str) or text[end:end+len(after)]!=after):continue
            candidates.append((start,end))
        if not candidates:raise ValueError('TREATMENT_SOURCE_NOT_FOUND')
        if len(candidates)!=1:raise ValueError('TREATMENT_SOURCE_AMBIGUOUS')
        start,end=candidates[0]
        if ranges and start<ranges[-1]['end']:raise ValueError('TREATMENT_CONFLICT')
        ranges.append({'start':start,'end':end,'text':value})
    return ranges


def uncovered(text, start, end, spans):
    cursor=start;gaps=[]
    for left,right in sorted(spans):
        left,right=max(start,left),min(end,right)
        if right<=start or left>=end:continue
        if left>cursor and text[cursor:left].strip():gaps.append({'start':cursor,'end':left,'text':text[cursor:left]})
        cursor=max(cursor,right)
    if cursor<end and text[cursor:end].strip():gaps.append({'start':cursor,'end':end,'text':text[cursor:end]})
    return gaps


def spoken_projection(ranges, delivery):
    pieces=[]
    for span in ranges:
        value=span['text']
        if delivery in {'DIALOGUE','INNER_MONOLOGUE'} and len(value)>=2 and QUOTE_PAIRS.get(value[0])==value[-1]:
            value=value[1:-1]
        pieces.append(value)
    return ''.join(pieces)


def event_source_ranges(ranges, delivery, events, override, bindings=None):
    """Map already validated event text by its treatment's exact projection cursor.

    No text search across treatments. Authored paraphrases retain the declared
    source extent; indistinguishable subranges cannot invent an interleaving.
    """
    if override is not None:
        if bindings and all(str(e['order']) in bindings for e in events):
            result={e['order']:deepcopy(bindings[str(e['order'])]) for e in events}
            covered=[]
            for spans in result.values():
                end=-1
                if not isinstance(spans,list) or not spans:raise ValueError('AUDIO_EVENT_SOURCE_BINDING_INVALID')
                for span in spans:
                    left,right=span.get('start'),span.get('end')
                    if (type(left) is not int or type(right) is not int or left>=right or left<end
                            or not any(r['start']<=left<right<=r['end'] for r in ranges)):
                        raise ValueError('AUDIO_EVENT_SOURCE_BINDING_INVALID')
                    covered.append((left,right));end=right
            for span in ranges:
                value=span['text'];start=span['start'];stop=span['end']
                if delivery in {'DIALOGUE','INNER_MONOLOGUE'} and len(value)>=2 and QUOTE_PAIRS.get(value[0])==value[-1]:
                    start+=1;stop-=1
                # All meaningful projected source must still have an Event owner.
                for offset in range(start,stop):
                    if not span['text'][offset-span['start']].isspace() and not any(a<=offset<b for a,b in covered):
                        raise ValueError('AUDIO_EVENT_SOURCE_BINDING_INCOMPLETE')
            return result,True
        # Historical single-Event authoring has an unambiguous declared extent.
        # A legacy multi-Event override without partitions is not guessed.
        return {e['order']:[{'start':r['start'],'end':r['end']} for r in ranges] for e in events},len(events)==1
    positions=[]
    for span in ranges:
        value=span['text'];left,right=span['start'],span['end']
        if delivery in {'DIALOGUE','INNER_MONOLOGUE'} and len(value)>=2 and QUOTE_PAIRS.get(value[0])==value[-1]:
            left+=1;right-=1
        positions.extend(range(left,right))
    expected=spoken_projection(ranges,delivery);cursor=0;result={}
    for event in events:
        value=event.get('text') or ''
        while cursor<len(expected) and not expected.startswith(value,cursor) and expected[cursor].isspace():cursor+=1
        if not value or not expected.startswith(value,cursor):return {},True
        selected=positions[cursor:cursor+len(value)]
        spans=[]
        for position in selected:
            if spans and spans[-1]['end']==position:spans[-1]['end']=position+1
            else:spans.append({'start':position,'end':position+1})
        result[event['order']]=spans;cursor+=len(value)
    return result,True


def event_source_positions(ranges, delivery, events, override):
    spans,precise=event_source_ranges(ranges,delivery,events,override)
    return {order:(value[0]['start'],value[-1]['end'],not precise) for order,value in spans.items()}


def texts_cover(expected, events):
    cursor=0
    for event in events:
        value=event.get('text')
        if not isinstance(value,str) or not value.strip():return False
        if not expected.startswith(value,cursor):
            while cursor<len(expected) and expected[cursor].isspace():cursor+=1
        if not expected.startswith(value,cursor):return False
        cursor+=len(value)
    return not expected[cursor:].strip()


def validate_coverage(data, basis, *, chapter_wide=True, authored_texts=None, event_sources=None):
    """Validate a candidate/current immutable bundle; report only, never mutate it.

    Authored overrides are supplied only by the verified Revision writer/reader,
    not by Director output or a client-provided 'verified' flag.
    """
    text=basis['source']['content'];issues=[];compiled=[];chapter_spans=[]
    counts={'dialogue':0,'narration':0,'inner_monologue':0,'visual':0}
    unavailable=False
    def issue(code,shot=None,treatment=None,**details):
        issues.append({'code':code,'shot_id':shot,'treatment_key':treatment,**details})
    for shot in data.get('shots',[]):
        sid=shot['id']
        try:
            shot_ranges=locate(text,shot.get('source_evidence'),[(0,len(text))])
            if not shot_ranges:raise ValueError('TREATMENT_SOURCE_NOT_FOUND')
        except ValueError as exc:
            issue(str(exc),sid);continue
        domains=[(r['start'],r['end']) for r in shot_ranges]
        chapter_spans.extend(domains)
        # Existing Phase5 owns the contiguity/appearance rules. Coverage checks
        # the complete owned extent; no smaller treatment scope can hide prose.
        start,end=shot_ranges[0]['start'],shot_ranges[-1]['end']
        treatments=shot.get('source_treatments')
        if treatments is None:
            unavailable=True;issue('CONTRACT_UNAVAILABLE',sid);continue
        if not isinstance(treatments,list):
            issue('SOURCE_TREATMENT_MISSING',sid);continue
        by_key={};owned=[];resolved=[];audio_positions={};compiled_sources={}
        for treatment in treatments:
            key=treatment.get('key') if isinstance(treatment,dict) else None
            if not isinstance(key,str) or not key or key in by_key:
                issue('TREATMENT_CONFLICT',sid,key,reason='missing or duplicate key');continue
            by_key[key]=treatment
            try:ranges=locate(text,treatment.get('source_evidence'),domains)
            except ValueError as exc:
                issue(str(exc),sid,key);continue
            if not ranges:
                issue('TREATMENT_SOURCE_NOT_FOUND',sid,key);continue
            kind=treatment.get('type')
            if kind not in {'DIALOGUE','NARRATION','VISUAL'}:
                issue('TREATMENT_CONFLICT',sid,key,reason='invalid treatment type');continue
            targets=treatment.get('visual_targets') or []
            if (kind=='VISUAL' and not targets) or any(t not in VISUAL_FIELDS or not isinstance(shot.get(t),str) or not shot[t].strip() for t in targets):
                issue('TREATMENT_VISUAL_TARGET_MISSING',sid,key)
            if kind!='NARRATION' and treatment.get('audio_type') is not None:
                issue('TREATMENT_CONFLICT',sid,key,reason='audio_type on non-narrative treatment')
            delivery='DIALOGUE' if kind=='DIALOGUE' else treatment.get('audio_type') or 'NARRATION'
            if kind=='NARRATION' and delivery not in {'NARRATION','INNER_MONOLOGUE'}:
                issue('TREATMENT_CONFLICT',sid,key,reason='invalid narrative delivery')
            for span in ranges:
                for left,right,owner in owned:
                    if span['start']<right and left<span['end']:
                        issue('TREATMENT_CONFLICT',sid,key,other_treatment=owner,source_ranges=[span])
                owned.append((span['start'],span['end'],key))
            events=[e for e in shot.get('audio_events',[]) if e.get('treatment_ref')==key]
            if kind=='VISUAL':
                counts['visual']+=1
                if events:issue('TREATMENT_CONFLICT',sid,key,reason='VISUAL has audio events')
            else:
                counts['dialogue' if kind=='DIALOGUE' else 'inner_monologue' if delivery=='INNER_MONOLOGUE' else 'narration']+=1
                missing='DIALOGUE_EVENT_MISSING' if kind=='DIALOGUE' else 'INNER_MONOLOGUE_EVENT_MISSING' if delivery=='INNER_MONOLOGUE' else 'NARRATION_EVENT_MISSING'
                if not events:
                    issue(missing,sid,key,source_ranges=ranges,actual_count=0)
                elif any(e.get('type')!=delivery for e in events):
                    issue('TREATMENT_CONFLICT',sid,key,expected_audio_type=delivery)
                else:
                    expected=spoken_projection(ranges,delivery)
                    override=(authored_texts or {}).get(str(sid),{}).get(key)
                    if override is not None:expected=override
                    if not isinstance(expected,str) or not texts_cover(expected,events):
                        excessive=isinstance(expected,str) and sum(len(e.get('text') or '') for e in events)>len(expected)
                        issue('TREATMENT_CONFLICT' if excessive else 'TREATMENT_TEXT_MISMATCH',sid,key,
                              reason='repeated or excess spoken text' if excessive else 'spoken text does not cover the declared source',
                              source_ranges=ranges,actual_count=len(events))
                    for event in events:
                        if delivery=='NARRATION' and (event.get('voice_owner')!='旁白' or event.get('visible_speaker') is not None or event.get('requires_visible_lipsync')):
                            issue('TREATMENT_CONFLICT',sid,key,reason='Book Narrator must remain audio-only')
                        if delivery=='INNER_MONOLOGUE' and (event.get('voice_owner')=='旁白' or event.get('visible_speaker') is not None or event.get('requires_visible_lipsync')):
                            issue('TREATMENT_CONFLICT',sid,key,reason='Character internal voice must not become Book Narrator')
                    try:
                        spans,precise=event_source_ranges(ranges,delivery,events,override,(event_sources or {}).get(str(sid)))
                        audio_positions.update({order:(value[0]['start'],value[-1]['end'],not precise) for order,value in spans.items()})
                        if precise:compiled_sources.update({str(order):value for order,value in spans.items()})
                    except ValueError as exc:issue(str(exc),sid,key)
            resolved.append({**deepcopy(treatment),'ranges':ranges,'audio_orders':[e['order'] for e in events]})
        for event in shot.get('audio_events',[]):
            if event.get('treatment_ref') not in by_key:
                issue('AUDIO_EVENT_TREATMENT_MISSING',sid,audio_order=event.get('order'))
        dialogue_events=[e for e in shot.get('audio_events',[]) if e.get('type')=='DIALOGUE']
        if [(d.get('character_name'),d.get('text')) for d in shot.get('dialogues',[])] != [(e.get('voice_owner'),e.get('text')) for e in dialogue_events]:
            issue('DIALOGUE_EVENT_MISSING',sid,reason='compatibility dialogues differ from explicit DIALOGUE events')
        # Source facts are not candidate promises: retyping the entire bundle
        # as VISUAL/NARRATION cannot remove an explicitly spoken quotation.
        dialogue_spans=[(r['start'],r['end']) for t in resolved if t['type']=='DIALOGUE' for r in t['ranges']]
        for match in direct_speech_matches(text):
            left,right=match.start()+1,match.end()-1
            if left<end and start<right and uncovered(text,max(left,start),min(right,end),dialogue_spans):
                issue('DIRECT_SPEECH_TREATMENT_REQUIRED',sid,source_ranges=[{'start':left,'end':right,'text':text[left:right]}])
        previous=None
        for event in shot.get('audio_events',[]):
            position=audio_positions.get(event.get('order'))
            if position is None:continue  # Its grounding/type failure is reported above.
            if previous:
                old,old_position=previous
                same_authored=(old['treatment_ref']==event['treatment_ref'] and position[2] and old_position[2])
                if position[0]<old_position[1] and not same_authored:
                    issue('AUDIO_SOURCE_ORDER_INVALID',sid,event['treatment_ref'],
                          previous_order=old['order'],audio_order=event['order'],source_ranges=[list(old_position[:2]),list(position[:2])])
            previous=(event,position)
        gaps=uncovered(text,start,end,[(left,right) for left,right,_ in owned])
        if gaps:issue('SOURCE_TREATMENT_MISSING',sid,source_ranges=gaps)
        compiled.append({'shot_id':sid,'ranges':shot_ranges,'treatments':resolved,'event_sources':compiled_sources})
    if chapter_wide:
        gaps=uncovered(text,0,len(text),chapter_spans)
        if gaps:issue('SOURCE_TREATMENT_MISSING',scope='CHAPTER',source_ranges=gaps)
    return {'status':'CONTRACT_UNAVAILABLE' if unavailable else 'FAIL' if issues else 'PASS',
            'contract_version':VERSION,'source_hash':basis['source']['hash'],
            'input_hash':fingerprint({'data':data,'source':basis['source'],'authored_texts':authored_texts or {},'chapter_wide':chapter_wide}),
            'visual_semantics_verified':False,'counts':counts,'issues':issues,'resolved':compiled}


def error_message(report):
    first=report['issues'][0]['code'] if report.get('issues') else 'TREATMENT_VALIDATION_FAILED'
    return first+': '+json.dumps(report.get('issues',[]),ensure_ascii=False)
