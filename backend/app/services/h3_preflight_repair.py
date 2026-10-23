"""Bounded repair of #14 output using the existing authority check, never Canonical.

Original JSON is immutable. L0 uses explicit bindings and verified continuity;
L1 only adds short missing reference/listener/blocking prose. Timing, dialogue,
camera plans and workflow stay frozen.
"""
import copy
import difflib
import hashlib
import json
import re

from app.services.h3_native_prompt import SECTIONS, sections, speaker_bindings
from app.services.video_director_ai import resolve_prompt_template
from app.services.llm_service import LLMService
from app.services.llm.cancellation import LLMCallTerminated
from app.utils.json_parser import safe_parse_llm_json

TEMPLATE_TYPE = 'h3_preflight_repair_prompt'
L1_CHECKS = {'reference_authority_scope', 'speaker_switch_listener_settle',
             'speaker_switch_listener_scope', 'blocking_preservation_wording'}


def _one_edit(a, b):
    # Names are corrected only when an explicit Subject ID and unique canonical
    # candidate agree; another valid name is never corrected as a typo.
    if abs(len(a)-len(b)) > 1 or a == b:
        return False
    if len(a) == len(b):
        return sum(x != y for x,y in zip(a,b)) == 1
    short,long = sorted([a,b], key=len)
    return any(long[:i]+long[i+1:] == short for i in range(len(long)))


def deterministic_candidate(output, authority, failed_checks=None):
    candidate = copy.deepcopy(output)
    prompt = candidate['optimized_prompt']
    bindings = authority['subject_bindings']
    changes = []
    normalized = re.sub(r'(?m)^[ \t]+(' + '|'.join(SECTIONS) + r'):[ \t]*$', r'\1:', prompt)
    if normalized != prompt and sections(normalized):
        changes.append({'code':'H3_SECTION_HEADER_INDENTATION'})
        prompt = normalized
    references = authority.get('reference_bindings') or []
    if references and authority.get('anchor_policy'):
        from app.services.h3_anchor_policy import projected_bindings
        references = projected_bindings(authority, output.get('av_timeline', {}).get('anchors', []))
    allowed_pictures = {r['picture'] for r in references}
    retention = sections(prompt).get('retention_analysis', '')
    def expand_range(match):
        first, last = int(match[1]), int(match[2])
        if not 1 <= first < last <= 9:
            return match[0]
        pictures = [f'<Picture {i}>' for i in range(first, last + 1)]
        if not set(pictures) <= allowed_pictures:
            return match[0]
        expanded = ', '.join(pictures[:-1]) + ' and ' + pictures[-1]
        changes.append({'code':'EXPLICIT_PICTURE_RANGE','before':match[0],'after':expanded})
        return expanded
    # Enumerate a literal inclusive range only in reference guidance, never in
    # dialogue. The existing Binder's projected manifest is the authority.
    expanded = re.sub(r'<Picture (\d+)>\s+(?:through|to)\s+<Picture (\d+)>', expand_range, retention, flags=re.I)
    if expanded != retention:
        prompt = prompt.replace(retention, expanded, 1)
    # The candidate already attributes its current floor positions to verified
    # incoming AV. Add only the missing preservation wording after that sentence;
    # keep its original bytes intact for canonical evidence excerpts.
    if ('blocking_preservation_wording' in (failed_checks or ())
            and (authority.get('continuation') or {}).get('binding_verified') is True
            and bindings and all(subject in prompt for subject in bindings)):
        first_sentence = sections(prompt).get('retention_analysis', '').split('.', 1)[0]
        if (re.match(r'^Continue (?:the )?(?:exact )?current\b', first_sentence, re.I)
                and re.search(r'\bfloor positions?\b.{0,100}\bestablished by (?:the )?'
                              r'(?:incoming|previous|preceding) (?:video|footage)\b', first_sentence, re.I)
                and not re.search(r'\b(?:not|new|changed|different|relocated|swapped)\b', first_sentence, re.I)):
            marker = 'retention_analysis:\n' + first_sentence + '.'
            addition = ' Preserve these established floor positions.'
            if prompt.count(marker) == 1:
                revised = prompt.replace(marker, marker + addition, 1)
                changes.append({'code':'VERIFIED_FLOOR_POSITION_WORDING',
                                'after':first_sentence + '.', 'text':addition})
                prompt = revised
    def name(match):
        subject, actual = match[2], match[3].strip()
        expected = bindings.get(subject)
        candidates = [n for n in bindings.values() if _one_edit(actual,n)]
        if expected and actual not in bindings.values() and candidates == [expected]:
            changes.append({'code':'SUBJECT_NAME_TYPO','subject':subject,'before':actual,'after':expected})
            return match[1]+expected
        return match[0]
    prompt = re.sub(r'(?m)^((<Subject \d+>)\s+is\s+)([^,，\n.;；。:：]+)',name,prompt)
    canonical = authority.get('dialogue_events') or []
    mapping = speaker_bindings(canonical)
    # A missing marker is safe only if every utterance text AND explicit Subject
    # already match Canonical in order. Never infer a speaker from a nearby name.
    pattern = r'(<Subject \d+>)(\s+(?:\(S\d+\)\s+)?[^<>]*?<d>\[Chinese\]\s*(.*?)</d>)'
    detail = sections(prompt).get('detailed_description','')
    matches = list(re.finditer(pattern,detail,re.S))
    if [(m[1],m[3]) for m in matches] == [(e['speaker'],e['exact_dialogue']) for e in canonical]:
        for m in reversed(matches):
            if not re.match(r'\s+\(S\d+\)',m[2]):
                replacement=m[1]+' ('+mapping[m[1]]+')'+m[2]
                detail=detail[:m.start()]+replacement+detail[m.end():]
                changes.append({'code':'MISSING_STABLE_SPEAKER_ID','subject':m[1]})
        if matches:
            parts=sections(prompt);parts['detailed_description']=detail
            prompt='\n\n'.join(k+':\n'+v for k,v in parts.items())
    catalog=(authority.get('anchor_policy') or {}).get('catalog') or []
    aliases={a['source_picture']:a['anchor_id'] for a in catalog if a.get('source_picture')
             and sum(b.get('source_picture')==a['source_picture'] for b in catalog)==1}
    for collection in [candidate.get('anchor_decisions',[]),candidate.get('av_timeline',{}).get('anchors',[])]:
        for event in collection:
            if event.get('id') in aliases:
                old=event['id'];event['id']=aliases[old]
                changes.append({'code':'ANCHOR_ID_FROM_CATALOG','before':old,'after':event['id']})
    candidate['optimized_prompt']=prompt
    return candidate,changes


def patch_budget(failed, authority):
    events = (authority or {}).get('dialogue_events', [])
    switches = sum(a['speaker'] != b['speaker'] for a,b in zip(events, events[1:]))
    listeners = switches if failed & {'speaker_switch_listener_settle', 'speaker_switch_listener_scope'} else 0
    reference = int('reference_authority_scope' in failed)
    blocking = int('blocking_preservation_wording' in failed)
    return {'max_insertions': max(1, listeners + reference + blocking),
            'max_added_characters': min(2400, 600 * reference + 220 * listeners + 220 * blocking) or 600}


def apply_insertions(original, response, failed, authority=None):
    """No free-form replacement: keep every original byte and all structured fields."""
    if not isinstance(response,dict) or set(response) != {'insertions'}:
        raise ValueError('REPAIR_RESPONSE_NOT_LOCAL')
    edits=response['insertions']
    budget = patch_budget(failed, authority)
    if not isinstance(edits,list) or not 1 <= len(edits) <= budget['max_insertions']:
        raise ValueError('REPAIR_PATCH_LIMIT')
    prompt=original['optimized_prompt'];parts=sections(prompt)
    allowed=set()
    if failed & {'reference_authority_scope', 'blocking_preservation_wording'}:
        allowed.add('retention_analysis')
    if failed & {'speaker_switch_listener_settle', 'speaker_switch_listener_scope'}:
        allowed.add('detailed_description')
    total=0;offsets=[]
    for edit in edits:
        if not isinstance(edit,dict) or set(edit) != {'after','text'}:
            raise ValueError('REPAIR_PATCH_FIELDS')
        after,text=edit['after'],edit['text']
        if not isinstance(after,str) or not after or not isinstance(text,str) or not text.strip() or prompt.count(after)!=1:
            raise ValueError('REPAIR_PATCH_AMBIGUOUS')
        # The insertion point must belong to one permitted section. No dialogue,
        # durations, new speaker declarations, cuts or body translations may be added.
        if not any(after in parts.get(section,'') for section in allowed):
            raise ValueError('REPAIR_SECTION_NOT_ALLOWED')
        if failed == {'blocking_preservation_wording'} and not re.search(
                r'\b(?:preserv\w*|maintain\w*|retain\w*|remain\w*)\b.{0,100}'
                r'\b(?:floor positions?|blocking)\b', text, re.I):
            raise ValueError('REPAIR_BLOCKING_WORDING_REQUIRED')
        protected_text = re.sub(r'<Subject \d+>|<Picture \d+>', '', text)
        for canonical_name in (authority or {}).get('subject_bindings', {}).values():
            # Digits in a known character name (e.g. 骗子1) are identity, not timing.
            protected_text = protected_text.replace(canonical_name, re.sub(r'\d', '', canonical_name))
        if re.search(r'<d>|</d>|\(S\d+\)|\[Chinese\]|\d|(?m:^\w+:)|\b(?:cut|walk|rise|stand|step|duration|second)\w*\b|\bmov(?:e|es|ed|ing)\b',protected_text,re.I):
            raise ValueError('REPAIR_FORBIDDEN_CONTENT')
        if set(re.findall(r'<(?:Subject|Picture) \d+>',text))-set(re.findall(r'<(?:Subject|Picture) \d+>',prompt)):
            raise ValueError('REPAIR_NEW_BINDING')
        total+=len(text)
        offsets.append((prompt.index(after)+len(after),text))
    if total>budget['max_added_characters'] or len({p for p,_ in offsets})!=len(offsets):raise ValueError('REPAIR_PATCH_LIMIT')
    for pos,text in sorted(offsets,reverse=True):prompt=prompt[:pos]+text+prompt[pos:]
    result=copy.deepcopy(original);result['optimized_prompt']=prompt
    return result


def prompt_diff(before,after):
    return ''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='original',tofile='repaired'))


async def repair_output(db,novel,shot,output,runtime,audit,check,*,state=None,persist=None):
    state=copy.deepcopy(state or {})
    original=copy.deepcopy(output)
    saved_input_matches = state.get('original_output') == original
    state.setdefault('original_output',original)
    state.setdefault('attempts',[])
    if audit.get('passed'):
        state.update(resolution='ALREADY_PASS',final_preflight=audit,final_output=output)
        if persist:persist(state)
        return output,audit,state
    candidate,changes=deterministic_candidate(output,runtime['immutable_authority'],audit.get('blocking_findings'))
    if changes:
        next_audit=check(candidate)
        before=set(audit['blocking_findings']);after=set(next_audit['blocking_findings'])
        accepted=after < before
        state['attempts'].append({'level':'L0','changes':changes,'accepted':accepted,'output':candidate,
                                  'preflight':next_audit,'prompt_diff':prompt_diff(output['optimized_prompt'],candidate['optimized_prompt'])})
        if accepted:output,audit=candidate,next_audit
    # Existing resolver already provides independent, program-extracted evidence;
    # preserve it without rewriting the LLM's raw evidence fields.
    state['resolved_metadata']=audit.get('resolved_evidence')
    if persist:persist(state)
    failed=set(audit.get('blocking_findings') or [])
    if not failed:
        state['resolution']='L0_PASS'
    elif not failed <= L1_CHECKS:
        state['resolution']='L2_UNSAFE_OR_NONLOCAL'
    elif state.get('l1_invocations',0):
        state['resolution']='L1_ALREADY_ATTEMPTED'
        saved = next((a for a in reversed(state['attempts']) if a.get('level') == 'L1'), None)
        if saved_input_matches and saved and (saved.get('raw_response') or {}).get('success'):
            # A validator/process fix may recheck the saved patch, but never buy
            # another model call. Changed source input cannot inherit its edits.
            prior_failed = set(saved.get('failed_checks') or (state.get('final_preflight') or {}).get('blocking_findings') or failed)
            try:
                if not prior_failed <= L1_CHECKS:
                    raise ValueError('REPAIR_SAVED_SCOPE_CHANGED')
                candidate = apply_insertions(output, safe_parse_llm_json(saved['raw_response']['content'], default=None), prior_failed, runtime['immutable_authority'])
                next_audit = check(candidate)
                state['attempts'].append({'level':'L1_REVALIDATION','llm_log_id':saved.get('llm_log_id'),
                    'llm_called':False,'output':candidate,'preflight':next_audit,'accepted':next_audit['passed']})
                if next_audit['passed']:
                    output,audit=candidate,next_audit;state['resolution']='L1_REPLAY_PASS'
            except Exception as exc:
                state['revalidation_error'] = str(exc)
    else:
        template=resolve_prompt_template(db,novel,'h3_preflight_repair_prompt_template_id',TEMPLATE_TYPE)
        if template.type!=TEMPLATE_TYPE:raise ValueError('REPAIR_TEMPLATE_TYPE_MISMATCH')
        version=hashlib.sha256(template.template.encode()).hexdigest()
        state.update(l1_invocations=1,resolution='L1_IN_FLIGHT',template_id=template.id,template_version=version,
                     system_prompt_snapshot=template.template)
        if persist:persist(state)  # Write BEFORE external call; crashes never retry.
        request={'original_optimized_output':output,'failed_checks':sorted(failed),
                 'patch_budget':patch_budget(failed, runtime['immutable_authority']),
                 'canonical_authority':runtime['immutable_authority'],
                 'allowed_fields':['optimized_prompt: local insertions in retention_analysis or detailed_description'],
                 'forbidden_fields':['av_timeline','duration','dialogue text/order/speaker/duration','anchor_decisions','reference bindings','camera strategy','canonical_visual_requirements'],
                 'response_contract':{'insertions':[{'after':'unique exact existing excerpt','text':'short missing reference/listener sentence'}]},
                 'template_version':version}
        try:
            result=await LLMService().chat_completion(system_prompt=template.template,user_content=json.dumps(request,ensure_ascii=False),
                response_format='json_object',task_type=TEMPLATE_TYPE,prompt_template_name=f'{template.name} [{version[:12]}]',novel_id=novel.id,chapter_id=shot.chapter_id,shot_id=shot.id)
            attempt={'level':'L1','failed_checks':sorted(failed),'llm_log_id':result.get('log_id'),'raw_response':result,'template_id':template.id,'template_version':version,'accepted':False}
            state['attempts'].append(attempt)
            if not result.get('success'):raise ValueError(result.get('error') or 'REPAIR_LLM_FAILED')
            candidate=apply_insertions(output,safe_parse_llm_json(result.get('content') or '',default=None),failed,runtime['immutable_authority'])
            next_audit=check(candidate)
            attempt.update(output=candidate,preflight=next_audit,prompt_diff=prompt_diff(output['optimized_prompt'],candidate['optimized_prompt']))
            if next_audit['passed']:
                attempt['accepted']=True;output,audit=candidate,next_audit;state['resolution']='L1_PASS'
            else:state['resolution']='L1_FAILED_PREFLIGHT'
        except LLMCallTerminated:
            if persist:persist(state)
            raise
        except Exception as exc:
            state.update(resolution='L1_FAILED',error=str(exc))
    state.update(final_preflight=audit,final_output=output)
    if persist:persist(state)
    return output,audit,state
