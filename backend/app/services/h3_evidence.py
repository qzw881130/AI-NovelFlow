"""Resolve citations to actual text without rewriting model output or judging AV quality.

Alignment is deliberately narrow: exact text, or the same ordered tokens with
small additions in the actual text. It is NOT fuzzy semantic equivalence. Unknown
paraphrases, ambiguous locations and polarity/participant changes need review.
"""
import hashlib
import re
import copy

TOKEN = re.compile(r'<(?:Subject|Picture)\s+\d+>|\w+(?:[’\']\w+)*', re.UNICODE)
POLARITY = {'no', 'not', 'never', 'without', 'instead', 'cannot', "can't", "doesn't", "isn't"}


def character_name(text):
    return re.split(r'[,，.;；。:：\n]', text, maxsplit=1)[0].strip()


def resolve_authority(authority, supplied_echo):
    """Canonical/manifest IDs own execution; an LLM echo is only audit metadata.

    Normalize historical Chinese name parsing in a separate view. Never repair
    an explicit conflicting Subject assignment or mutate the saved model output.
    """
    resolved = copy.deepcopy(authority)
    resolved['subject_bindings'] = {k: character_name(v) for k, v in authority['subject_bindings'].items()}
    manifest_valid = True
    for ref in resolved.get('reference_bindings', []):
        if ref.get('type') != 'CHARACTER_IDENTITY':
            continue
        expected = next((s for s, name in resolved['subject_bindings'].items()
                         if name == ref.get('source_name')), None)
        if expected and ref.get('subject') is None:
            ref['subject'] = expected
        elif expected and ref.get('subject') != expected:
            manifest_valid = False
        if not ref.get('subject'):
            manifest_valid = False
    differences = []
    def diff(original, echo, path):
        if isinstance(original, dict) and isinstance(echo, dict):
            for key in sorted(set(original) | set(echo)):
                diff(original.get(key), echo.get(key), path + '.' + key)
        elif isinstance(original, list) and isinstance(echo, list) and len(original) == len(echo):
            for i, (a, b) in enumerate(zip(original, echo)):
                diff(a, b, f'{path}[{i}]')
        elif original != echo:
            differences.append({'path': path, 'canonical_value': original, 'echo_value': echo})
    diff(authority, supplied_echo, 'authority_echo')
    return {
        'source': 'CANONICAL_INPUT_AND_REFERENCE_MANIFEST', 'authority': resolved,
        'echo_status': 'AUTHORITY_ECHO_MISMATCH' if differences else 'EXACT',
        'echo_differences': differences, 'manifest_subject_consistent': manifest_valid,
        'model_output_modified': False,
    }


def resolve_excerpt(text, supplied):
    result = {'supplied_excerpt': supplied, 'excerpt': None, 'start': None, 'end': None,
              'status': 'UNRESOLVED', 'method': None, 'mismatch': True,
              'scope_sha256': hashlib.sha256(text.encode()).hexdigest()}
    if not isinstance(supplied, str) or not supplied.strip():
        return result
    exact = list(re.finditer(re.escape(supplied), text))
    result['locations'] = [{'start': m.start(), 'end': m.end()} for m in exact]
    if len(exact) == 1:
        m = exact[0]
        return {**result, 'excerpt': m[0], 'start': m.start(), 'end': m.end(),
                'status': 'RESOLVED', 'method': 'EXACT', 'mismatch': False}
    if exact:
        return {**result, 'status': 'AMBIGUOUS'}
    tokens = list(TOKEN.finditer(text));wanted = [m[0].casefold() for m in TOKEN.finditer(supplied)]
    if not wanted:
        return result
    candidates = []
    for start, token in enumerate(tokens):
        if token[0].casefold() != wanted[0]:
            continue
        cursor = start;extra = []
        for word in wanted:
            while cursor < len(tokens) and tokens[cursor][0].casefold() != word:
                extra.append(tokens[cursor][0].casefold());cursor += 1
            if cursor == len(tokens):
                break
            cursor += 1
        else:
            begin,end=tokens[start].start(),tokens[cursor-1].end()
            # CJK clauses can be one token each; permit a short omitted clause
            # even when the quote has only a few tokens. Still require every
            # supplied token in order and one unique bounded source span.
            if '\n\n' in text[begin:end] or len(extra) > min(12, max(2, len(wanted)//4)):
                continue
            if any(t in POLARITY or t.startswith('<') or t.isdigit()
                   or re.search(r'不|没|无|禁止|而非|改为', t) for t in extra):
                continue
            # Include adjacent terminal punctuation, but never synthesize text.
            while end < len(text) and text[end] in '.,;:!?。！？':
                end += 1
            candidates.append((begin,end))
    if len(candidates) == 1:
        start,end=candidates[0]
        return {**result, 'excerpt': text[start:end], 'start': start, 'end': end,
                'status': 'RESOLVED', 'method': 'TOKEN_SUPERSEQUENCE'}
    return {**result, 'status': 'AMBIGUOUS' if candidates else 'UNRESOLVED'}


def resolve_canonical_excerpt(text, requirement, authority):
    """Resolve repeated event clauses using canonical ownership, not equality alone.

    All exact locations survive. A CVR can select explicit event IDs, or explicitly
    cover all of a named speaker's utterances. Unscoped repeated prose remains
    ambiguous; this is not a general natural-language semantic equivalence test.
    """
    result = resolve_excerpt(text, requirement.get('source_excerpt'))
    locations = result.get('locations') or []
    if not locations:
        return result
    events = {e['id']: e for e in authority.get('dialogue_events', [])}
    # Only top-level source headings delimit ownership; an excerpt must stay
    # entirely within an actual canonical dialogue block, never a later section.
    headings = list(re.finditer(r'(?m)^([A-Za-z_][\w]*):[ \t]*$', text))
    owned = []
    invalid_event = False
    for location in locations:
        owner = None
        for i, h in enumerate(headings):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            if h.end() <= location['start'] < location['end'] <= end and re.fullmatch(r'D\d+', h[1]):
                event = events.get(h[1]);block = text[h.end():end]
                speaker = re.search(r'(?m)^\s*speaker:\s*(<Subject \d+>)\s*$', block)
                dialogue = re.search(r'(?m)^\s*exact_dialogue:[ \t]*([^\n]+)', block)
                if (event and speaker and dialogue and speaker[1] == event['speaker']
                        and dialogue[1].rstrip() == event['exact_dialogue']):
                    owner = {'event_id': event['id'], 'speaker': event['speaker']}
                else:
                    invalid_event = True
                break
        owned.append({**location, **(owner or {}), 'selected': False})
    result['locations'] = owned
    if invalid_event:
        return {**result, 'excerpt': None, 'start': None, 'end': None,
                'status': 'OWNERSHIP_CONFLICT', 'mismatch': True}
    if not all('event_id' in loc for loc in owned):
        return result  # Never promote unknown repeated source scopes.
    description = str(requirement.get('requirement') or '')
    subjects = set(re.findall(r'<Subject \d+>', description))
    quoted_subjects = set(re.findall(r'<Subject \d+>', str(requirement.get('source_excerpt') or '')))
    requested = set(re.findall(r'\bD\d+\b', description))
    matched = {loc['event_id'] for loc in owned}
    owners = {loc['speaker'] for loc in owned if not requested or loc['event_id'] in requested}
    # Explicit actor and event identity must agree with the immutable canonical
    # records even when a string is an exact match.
    invalid = (len(subjects) != 1 or subjects != owners
               or (quoted_subjects and quoted_subjects != owners)
               or (requested and not requested <= matched))
    if invalid:
        return {**result, 'excerpt': None, 'start': None, 'end': None,
                'status': 'OWNERSHIP_CONFLICT', 'mismatch': True}
    if not requested and len(locations) > 1:
        aggregate = re.search(r'\ball\s+(?:(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?'
                              r'(?:utterances|lines|dialogue events)\b', description, re.I)
        expected = {e['id'] for e in events.values() if e['speaker'] in subjects}
        if not aggregate or matched != expected:
            return result
        count = aggregate[1]
        if count:
            words = ['one','two','three','four','five','six','seven','eight','nine','ten']
            count = int(count) if count.isdigit() else words.index(count.lower()) + 1
            if count != len(expected):
                return {**result, 'excerpt': None, 'start': None, 'end': None,
                        'status': 'OWNERSHIP_CONFLICT', 'mismatch': True}
        requested = expected
    elif not requested:
        requested = matched
    for loc in owned:
        loc['selected'] = loc['event_id'] in requested
    selected = [loc for loc in owned if loc['selected']]
    return {**result, 'excerpt': text[selected[0]['start']:selected[0]['end']],
            'start': selected[0]['start'] if len(selected) == 1 else None,
            'end': selected[0]['end'] if len(selected) == 1 else None,
            'status': 'RESOLVED', 'method': 'CANONICAL_EVENT_LOCATIONS', 'mismatch': False,
            'event_ids': [loc['event_id'] for loc in selected]}


def resolve_output_evidence(prompt, output, authority):
    from app.services.h3_native_prompt import sections, dialogue_events
    detail=sections(prompt).get('detailed_description', '');spoken=dialogue_events(prompt)
    sources={s['id']:s['text'] for s in authority.get('anchor_policy', {}).get('canonical_visual_sources', [])}
    entries={}
    def add(path, text, supplied, scope):
        entries[path]={**resolve_excerpt(text,supplied), 'scope':scope}
    for i,r in enumerate(output.get('canonical_visual_requirements') or []):
        if not isinstance(r,dict):continue
        entries[f'requirements.{i}.source'] = {
            **resolve_canonical_excerpt(sources.get(r.get('source_id'), ''), r, authority),
            'scope': 'canonical_source:' + str(r.get('source_id'))}
        add(f'requirements.{i}.prompt',prompt,r.get('prompt_excerpt'),'optimized_prompt')
    timeline=output.get('av_timeline') or {}
    for i,a in enumerate(timeline.get('anchors') or []):
        if not isinstance(a,dict) or a.get('decision')=='DROP':continue
        add(f'anchors.{i}.prompt',detail,a.get('prompt_excerpt'),'detailed_description')
        add(f'anchors.{i}.relation',detail,(a.get('arrival_relation') or {}).get('prompt_excerpt'),'detailed_description')
    for i,h in enumerate(timeline.get('handoffs') or []):
        if not isinstance(h,dict):continue
        index=next((j for j,e in enumerate(timeline.get('dialogue_events') or []) if e.get('id')==h.get('to')),None)
        if index is None or index>=len(spoken):continue
        for key,value in (h.get('prompt_evidence') or {}).items():
            target=index-1 if key=='existing_view_excerpt' else index
            add(f'handoffs.{i}.{key}',spoken[target]['prelude'],value,f'dialogue_prelude:{target}')
    return {'version':1,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
            'entries':entries,'mismatches':[path for path,e in entries.items() if e['mismatch']],
            'unresolved':[path for path,e in entries.items() if e['status']!='RESOLVED'],
            'scope':'Text provenance only; resolved text is not proof of arbitrary semantic equivalence.'}


def excerpt(evidence, path):
    return evidence['entries'].get(path, {}).get('excerpt')
