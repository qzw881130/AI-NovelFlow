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
        if result['status'] == 'UNRESOLVED':
            return _resolve_canonical_fragments(text, requirement, authority, result)
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
        if result['status'] == 'AMBIGUOUS':
            collective = _resolve_collective_motion_locations(text, requirement, authority, result, headings)
            if collective is not None:
                return collective
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


def _resolve_collective_motion_locations(text, requirement, authority, result, headings):
    """Locate an identical complete motion rule explicitly asserted for all Subjects.

    Every canonical actor must own one matching row in the same motion_ownership
    section. This resolves provenance only; it does not prove the CVR's prose.
    """
    description = str(requirement.get('requirement') or '')
    aggregate = re.search(r'\ball\s+(?:(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?subjects\b', description, re.I)
    if not aggregate or re.search(r'\b(?:except|excluding|other than)\b', description, re.I):
        return None
    bindings = authority.get('subject_bindings', {})
    expected = set(bindings)
    explicit = set(re.findall(r'<Subject \d+>', description))
    if not expected or (explicit and explicit != expected):
        return None
    count = aggregate[1]
    if count:
        words = ['one','two','three','four','five','six','seven','eight','nine','ten']
        if (int(count) if count.isdigit() else words.index(count.lower()) + 1) != len(expected):
            return None
    scopes = [(h.end(), headings[i + 1].start() if i + 1 < len(headings) else len(text))
              for i,h in enumerate(headings) if h[1] == 'motion_ownership']
    if len(scopes) != 1:
        return None
    begin, end = scopes[0]
    supplied = requirement['source_excerpt']
    rows = list(re.finditer(r'(?m)^(<Subject \d+>)[ \t]+—[ \t]+([^:\n]+):[ \t]+([^\n]+)$', text[begin:end]))
    if len(rows) != len(expected) or {r[1] for r in rows} != expected:
        return None
    owned = []
    for row in rows:
        if (row[2].strip() != character_name(bindings[row[1]])
                or row[3].strip().rstrip('.') != supplied.strip().rstrip('.')):
            return None
        start = begin + row.start(3)
        owned.append({'start':start, 'end':start + len(supplied),
                      'subject':row[1], 'section':'motion_ownership', 'selected':True})
    # Preserve every exact match; an identical quote in another scope cannot
    # silently acquire the all-Subjects ownership of these rows.
    if {(x['start'],x['end']) for x in owned} != {(x['start'],x['end']) for x in result['locations']}:
        return None
    return {**result, 'excerpt':text[owned[0]['start']:owned[0]['end']],
            'start':None, 'end':None, 'locations':owned, 'status':'RESOLVED',
            'method':'CANONICAL_SUBJECT_LOCATIONS', 'mismatch':False,
            'subject_ids':[x['subject'] for x in owned], 'semantic_review_required':True}


def _resolve_canonical_fragments(text, requirement, authority, result):
    """Exact whole clauses in one source, in order; never search for keywords.

    This conservative fallback handles omitted intervening prose, not paraphrase.
    Structured event/section boundaries and implicit pronoun ownership need review.
    The enclosing excerpt is real source text, including omissions; resolved_spans
    separately identify what the model actually quoted. Neither proves semantics.
    """
    supplied = requirement.get('source_excerpt')
    if not isinstance(supplied, str):
        return result
    fragments = [m[0].strip() for m in re.finditer(r'[^;；。.!！?？\n]+', supplied) if m[0].strip()]
    if len(fragments) < 2:
        return result
    boundary = ';；。.!！?？\n:：'

    def subjects(value):
        found = set(re.findall(r'<Subject \d+>', value))
        for subject, name in authority.get('subject_bindings', {}).items():
            name = character_name(name)
            if name and re.search(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', value):
                found.add(subject)
        return found

    requested = subjects(str(requirement.get('requirement') or ''))
    quoted = set().union(*(subjects(f) for f in fragments))
    groups = []
    for index, fragment in enumerate(fragments):
        matches = []
        for m in re.finditer(re.escape(fragment), text):
            left = text[:m.start()].rstrip(' \t\r')
            right = text[m.end():].lstrip(' \t\r')
            # Reject arbitrary substring hits, including omission of negation,
            # an actor prefix or the remainder of a clause.
            if (left and left[-1] not in boundary) or (right and right[0] not in boundary):
                continue
            matches.append({'fragment_index': index, 'start': m.start(), 'end': m.end(),
                            'excerpt': m[0], 'selected': False})
        groups.append(matches)
    locations = [loc for group in groups for loc in group]
    result = {**result, 'excerpt': None, 'start': None, 'end': None,
              'status': 'UNRESOLVED', 'method': None, 'mismatch': True,
              'fragments': fragments, 'locations': locations}
    if not all(groups):
        return {**result, 'reason': 'MISSING_WHOLE_FRAGMENT'}
    if not requested or not quoted or not quoted <= requested:
        return {**result, 'status': 'OWNERSHIP_CONFLICT', 'reason': 'FRAGMENT_PARTICIPANTS'}
    # A pronoun-only clause cannot acquire a new owner merely by being spliced
    # after another actor's clause. Keep unsupported implicit attribution blocked.
    if any(not subjects(f) and re.match(r'(?i)^(?:he|she|they|his|her|their)\b|^[他她它]', f) for f in fragments):
        return {**result, 'status': 'OWNERSHIP_CONFLICT', 'reason': 'IMPLICIT_FRAGMENT_OWNER'}
    # Keep all exact occurrences. Resolve only a unique ordered path; repeated
    # clauses with multiple valid positions remain ambiguous, never pick first.
    paths = [[]]
    for group in groups:
        paths = [path + [loc] for path in paths for loc in group
                 if not path or path[-1]['end'] <= loc['start']]
        if len(paths) > 128:
            return {**result, 'status': 'AMBIGUOUS', 'reason': 'MULTIPLE_FRAGMENT_PATHS'}
    if len(paths) != 1:
        return {**result, 'status': 'AMBIGUOUS' if paths else 'UNRESOLVED',
                'reason': 'MULTIPLE_FRAGMENT_PATHS' if paths else 'FRAGMENT_ORDER'}
    selected = paths[0]
    start, end = selected[0]['start'], selected[-1]['end']
    paragraph_start = text.rfind('\n\n', 0, start) + 2
    enclosing = text[start:end]
    # Do not combine dialogue events, authority sections, or separate paragraphs.
    if '\n\n' in enclosing or re.search(r'(?m)^\s*[A-Za-z_][\w]*:[ \t]*$', text[max(0, paragraph_start - 2):end]):
        return {**result, 'status': 'OWNERSHIP_CONFLICT', 'reason': 'SOURCE_SECTION_BOUNDARY'}
    for loc in selected:
        # A colon can introduce an actor-owned clause. Never strip that actor.
        prefix = re.split(r'[;；。.!！?？\n]', text[:loc['start']])[-1]
        if not subjects(loc['excerpt']) and subjects(prefix) - requested:
            return {**result, 'status': 'OWNERSHIP_CONFLICT', 'reason': 'SOURCE_CLAUSE_OWNER'}
        loc['selected'] = True
    return {**result, 'excerpt': enclosing, 'start': start, 'end': end,
            'status': 'RESOLVED', 'method': 'CANONICAL_ORDERED_SPANS', 'mismatch': True,
            'resolved_spans': [dict(loc) for loc in selected],
            'semantic_review_required': True}


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
            'semantic_review_required':[path for path,e in entries.items() if e.get('semantic_review_required')],
            'scope':'Text provenance only; resolved text is not proof of arbitrary semantic equivalence.'}


def excerpt(evidence, path):
    return evidence['entries'].get(path, {}).get('excerpt')
