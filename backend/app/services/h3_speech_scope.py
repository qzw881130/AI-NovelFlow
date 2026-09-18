"""Deterministic H3 speech clauses scoped by the actual AudioDrive timeline.

Formatting does not terminate a timeline scope. Exceptions attach to the
predicate in their clause, not to any speech word elsewhere in the sentence.
This module only audits; it never edits a prompt or a speaker timeline.
"""
import re

CONTRACT_VERSION = 'structured-audio-authority-v1'
# Non-speech mouth motion is not a visible speech fact. Offscreen voice is not
# classified by language: both Chinese and English require visible attribution.
CN = r'(?:张嘴|开口)?(?:说道|说话(?!者|人|时间)|讲话(?!者)|发声(?!者)|说\s*[:：])|(?:产生|做|进行)(?:任何)?(?:说话|讲话|发声)?口型'
SPEECH = CN + r'|\bspeech\s+mouthing\b|\b(?:lip[- ]?sync(?:s|ing)?|speak(?:s|ing)?|talk(?:s|ing)?|say(?:s|ing)?)\b'
ACTION = re.compile(SPEECH,re.I)
SUBJECT = r'(?:<Subject\s*\d+>|\b(?:visible\s+)?(?:characters?|animals?|subjects?|people|persons?|everyone|anyone)\b)'
LINK = r'(?:(?:do|does|did|is|are|was|were|will|would|must|should|can|could|both|all|who|which|to|any|perform(?:s|ing)?|produce(?:s|d)?|has|have|start(?:s|ed)?|begin(?:s)?|continue(?:s)?|clearly|audibly|now)\s+|\b(?!only\b)\w+ly\s+)*'
NEGATABLE = r'(?:'+SPEECH+r'|\bspeech\b)'
GENERIC = r'(?:visible\s+)?(?:characters?|animals?|subjects?|persons?|people|one)'
NEGATION = re.compile(
    r'(?:不(?:得|要|会|能|可|再|允许)?|没有|未|禁止|无需|无)(?:任何|可|在|再)?(?:(?:可见)?(?:人物|角色|人))?\s*(?:'+CN+r')(?:(?:'+CN+r'))*|'
    r'\b(?:no\s+'+GENERIC+r'(?:\s+(?:or|nor)\s+'+GENERIC+r')*\s+|none\s+of\s+(?:the\s+)?'+GENERIC+r'\s+|(?:no|not|never|without)\s+(?!only\b|just\b|merely\b))'+LINK+NEGATABLE+
    r'(?:\s+(?:or|nor)\s+(?:any\s+)?'+NEGATABLE+r')*|\bnon[- ]lip[- ]?sync\b',re.I)
EXCEPTION = re.compile(r'\b(?:except(?:\s+for)?|unless|apart\s+from|other\s+than)\b',re.I)
OTHER_ACTION = re.compile(r'\b(?:remain|stay|wave|walk|run|look|stand|move|turn|graze|breathe|hold|smile)(?:s|d|ed|ing)?\b',re.I)
EXPLICIT_TEXT = re.compile(
    r'(?:台词|对白|(?<![A-Za-z0-9_])(?:exact_dialogue|dialogue))\s*[:：][ \t]*'
    r'(?:[\"\'“‘][ \t]*[^\"\'“”‘’\s]|(?!(?:NONE|null|无(?:台词)?|没有台词|保持沉默)(?:[ \t]*[。；;,，]|\s*$))[^\W_])|'
    r'<Subject\s+\d+>\s*[:：][ \t]*[\"\'“‘][ \t]*[^\"\'“”‘’\s]',re.I)

# Require seconds/t= notation, not arbitrary age/count ranges in identity text.
NUMBER = r'\d+(?:\.\d+)?'
MARKERS = re.compile(
    r'(?P<time>(?:from\s+)?(?:t\s*=\s*)?(?P<start>'+NUMBER+r')\s*(?:s|秒|seconds)?\s*(?:-|–|~|to|至|到)\s*(?:t\s*=\s*)?(?P<end>'+NUMBER+r')\s*(?:seconds|s|秒)\b)|'
    r'(?P<t_time>from\s+t\s*=\s*(?P<t_start>'+NUMBER+r')\s+to\s+t\s*=\s*(?P<t_end>'+NUMBER+r'))|'
    r'(?P<assignment>\bvisible_speaker\s*[:=]\s*(?P<speaker>NONE|<Subject\s*\d+>))|'
    r'(?P<none>(?<![A-Za-z0-9_])NONE(?![A-Za-z0-9_]|\s+of\b))|'
    r'(?P<section>^[ \t]*(?:subject_definitions|initial_state_anchor|frame_definitions|summary|detailed_description|overall_soundscape|text_rendering_constraint)\s*:)',re.I|re.M)


def scoped_text(prompt,timeline):
    silent=[(float(s.get('start_time',0)),float(s.get('end_time',0))) for s in timeline if isinstance(s,dict) and (s.get('visible_speaker') or 'NONE')=='NONE']
    all_silent=bool(timeline) and all((s.get('visible_speaker') or 'NONE')=='NONE' for s in timeline if isinstance(s,dict))
    active=all_silent;interval=None;cursor=0
    for marker in MARKERS.finditer(prompt):
        yield prompt[cursor:marker.start()],active,interval
        if marker.group('time') or marker.group('t_time'):
            interval=(float(marker.group('start') or marker.group('t_start')),float(marker.group('end') or marker.group('t_end')))
            active=all_silent or any(a<interval[1] and interval[0]<b for a,b in silent)
        elif marker.group('section'):
            interval=None;active=all_silent
        elif marker.group('assignment'):
            # A prompt's speaker claim cannot override an actual silent interval.
            active=all_silent or marker.group('speaker').upper()=='NONE' or bool(interval and any(a<interval[1] and interval[0]<b for a,b in silent))
        else:active=True
        cursor=marker.end()
    yield prompt[cursor:],active,interval


def clauses(text):
    # Coordinated clauses with a new subject have their own predicates. In
    # particular, "and all remain still except X" does not modify "no speech".
    subject_start=r'(?:<Subject|all\b|no\b|the\b|any\b|none\b|everyone\b)'
    boundary=r'\n[ \t]*\n|[。！？；;]|(?<=[.!?])\s+|(?:,\s*|\s+)(?:and|but|while|whereas|yet)\s+(?='+subject_start+r')'
    return re.split(boundary,text,flags=re.I)


def speech_conflicts(prompt,timeline,manifest):
    if not timeline:return []
    names=[re.escape(s['character_name']) for s in (manifest or {}).get('subjects',[]) if isinstance(s,dict) and s.get('character_name')]
    actors=re.compile(SUBJECT+('|'+'|'.join(names) if names else ''),re.I)
    by_name={s.get('character_name'):s.get('subject_ref') for s in (manifest or {}).get('subjects',[]) if isinstance(s,dict)}
    for block,is_silent,interval in scoped_text(prompt,timeline):
        for clause in clauses(block):
            # Explicit whole-clip instructions also overlap silent portions of a mixed timeline.
            whole=bool(re.search(r'throughout\s+(?:the\s+)?entire\s+clip|全程|整段',clause,re.I))
            if not is_silent and interval is None and not whole:continue
            actual=[s for s in timeline if isinstance(s,dict) and (interval is None or float(s.get('start_time',0))<interval[1] and interval[0]<float(s.get('end_time',0)))]
            def violates(subject):
                if is_silent:return True
                tag=re.fullmatch(r'<Subject\s*(\d+)>',subject.group(),flags=re.I)
                ref=f'<Subject {tag[1]}>' if tag else by_name.get(subject.group())
                return bool(ref and any((s.get('visible_speaker') or 'NONE')!=ref for s in actual))
            def issue():
                return [{'code':'NONE_SEGMENT_LIPSYNC_CONTRADICTION' if is_silent else 'VISIBLE_SPEAKER_TIMELINE_CONTRADICTION','blocking':True}]
            negated=list(NEGATION.finditer(clause));subjects=list(actors.finditer(clause))
            if is_silent and EXPLICIT_TEXT.search(clause):return issue()
            for action in ACTION.finditer(clause):
                negative=next((m for m in negated if m.start()<=action.start()<m.end()),None)
                if negative:
                    # Only a speech predicate's own exception can unmask it.
                    # Clause splitting has already separated non-speech actions.
                    exceptions=list(EXCEPTION.finditer(clause))
                    if any(any(subject.start()>=exception.end() and violates(subject) for subject in subjects)
                           and (exception.start()<negative.start() or not OTHER_ACTION.search(clause[action.end():exception.start()]))
                           for exception in exceptions):
                        return issue()
                    continue
                before=[subject for subject in subjects if subject.end()<=action.start()]
                visible=False
                if before:
                    bridge=clause[before[-1].end():action.start()]
                    bridge=re.sub(r',\s*(?:who|which)\b[^,]*,',' ',bridge,flags=re.I).strip(' \t\r\n,，:：()')
                    visible=bool(re.fullmatch(LINK,bridge+' ' if bridge else '',flags=re.I))
                    if bridge=='不仅' or bridge.endswith('而是'):visible=True
                    # A second coordinated predicate retains the same explicit
                    # actor. Its earlier action/negation is not a speech exemption.
                    if not visible:
                        coordinated=re.split(r'\b(?:and|but|then)\b',bridge,flags=re.I)
                        if len(coordinated)>1:
                            tail=coordinated[-1].strip(' \t\r\n,，')
                            visible=bool(re.fullmatch(LINK,tail+' ' if tail else '',flags=re.I)) and not (not tail and action.group().lower().endswith('ing'))
                if visible and violates(before[-1]):
                    return issue()
    return []
