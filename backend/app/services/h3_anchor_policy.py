"""Execution-only anchor choices and reference projection; canonical assets stay intact.

Checks here establish provenance, numbering and declared event order. They do not
infer story requirements from every pixel of a keyframe or certify prose semantics.
"""
import copy
import json
import math
import re


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _same(a, b):
    return _number(a) and _number(b) and abs(a - b) <= 1e-6


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def reference_drop_capability(workflow):
    """Recognize the existing optional Ref2VA binder, not a new graph topology.

    Its 0–9 input mechanism is covered by builder/service tests and verified on the
    live MiniMaxH3ReferenceToVideo node. Other workflow families fail closed.
    """
    try:
        graph = json.loads(workflow.workflow_json)
        mapping = json.loads(workflow.node_mapping)
        from app.services.comfyui.workflows import WorkflowBuilder
        if getattr(workflow, 'type', None) not in {'multi_reference_video', 'VIDEO_CONTINUATION', 'TEMPORAL_EXTEND'}:
            raise ValueError('not the validated multi-reference workflow')
        image_nodes = {str(mapping.get(f'load_image_node_{i}')) for i in range(1, 10)}
        def uses_image(value):
            if isinstance(value, dict):
                return any(uses_image(v) for v in value.values())
            if isinstance(value, list):
                return (len(value) == 2 and str(value[0]) in image_nodes and isinstance(value[1], int)) or any(uses_image(v) for v in value)
            return False
        if any(uses_image(node.get('inputs', {})) for node_id, node in graph.items()
               if node_id != str(mapping.get('reference_to_video_node_id'))):
            raise ValueError('reference image also drives an unvalidated node')
        probe = copy.deepcopy(graph)
        WorkflowBuilder.bind_multi_reference_video_images(probe, mapping, ['validation_only.png'] * 8)
        return {'supported': True, 'mechanism': 'EXISTING_REF2VA_OPTIONAL_IMAGES_0_TO_9',
                'reference_node_id': str(mapping['reference_to_video_node_id'])}
    except (AttributeError, KeyError, TypeError, ValueError):
        return {'supported': False, 'mechanism': None,
                'reason': 'H3_ANCHOR_DROP_BINDING_UNVERIFIED: no validated optional-reference binding for this workflow'}


def anchor_policy(authority, initial, context):
    references = authority['reference_bindings']
    catalog = []
    for fact, timing in zip(authority['visual_anchor_order'], initial['visual_anchors']):
        ref = next((r for r in references if r['picture'] == fact.get('picture')), {})
        catalog.append({'anchor_id': fact['id'], 'original_time': timing['time'],
                        'source_picture': fact.get('picture'), 'source_kind': ref.get('type'),
                        'visual_reference_description': fact['visual_target'],
                        'role': fact['declaration_prefix'], 'linked_anchor_id': None})
    for fact, timing in zip(authority.get('temporal_anchor_order', []), initial.get('temporal_anchors', [])):
        source = fact.get('source') or {}
        state = source.get('keyframe_index') or fact.get('source_state_index')
        alias = f'KF{state}' if state is not None else source.get('id')
        linked = next((a for a in catalog if a['anchor_id'] == alias), None)
        catalog.append({'anchor_id': fact['anchor_id'], 'original_time': timing['time_seconds'],
                        'source_picture': linked['source_picture'] if linked else None,
                        'source_kind': 'TEMPORAL_ANCHOR', 'visual_reference_description': fact.get('description') or fact.get('declaration_suffix'),
                        'role': 'TEMPORAL', 'linked_anchor_id': alias if linked else None})
    return {'version': 1, 'catalog': catalog,
            'canonical_visual_sources': context.get('canonical_visual_sources', []),
            'drop_binding': context.get('reference_drop_capability', {'supported': False}),
            'reference_semantics': 'Soft Ref2VA reference conditioning; arrival is an internal target, not frame binding. Catalog facts record original resources, not mandatory full-image outcomes.'}


def projected_bindings(authority, anchors):
    """Compact original order after selection; never reassign Subject identity."""
    choices = {a.get('id'): a for a in anchors if isinstance(a, dict)}
    dropped = {a['source_picture'] for a in authority['anchor_policy']['catalog']
               if choices.get(a['anchor_id'], {}).get('decision') == 'DROP' and a.get('source_picture')}
    return [{**ref, 'source_picture': ref['picture'], 'picture': f'<Picture {i}>'}
            for i, ref in enumerate((r for r in authority['reference_bindings'] if r['picture'] not in dropped), 1)]


def project_reference_manifest(manifest, authority, output):
    projection = projected_bindings(authority, output['av_timeline']['anchors'])
    active = {r['source_picture']: r for r in projection}
    refs, excluded = [], []
    choices = {a['id']: a for a in output['av_timeline']['anchors']}
    by_picture = {a['source_picture']: a for a in authority['anchor_policy']['catalog'] if a.get('source_picture')}
    for ref in (manifest or {}).get('references', []):
        old = f"<Picture {ref['slot']}>"
        item = copy.deepcopy(ref)
        # Old upload bindings are not valid after compaction; rebuild at submission.
        item.pop('binding', None)
        item.update(source_slot=ref['slot'], source_picture=old, logical_id=f"R{ref['slot']}")
        if old in active:
            item.update(slot=len(refs) + 1, picture=active[old]['picture'])
            refs.append(item)
        else:
            anchor = by_picture[old]
            item.update(anchor_id=anchor['anchor_id'], decision='DROP',
                        reason=choices[anchor['anchor_id']]['reason'], included_in_execution=False)
            excluded.append(item)
    if len(refs) != len(projection):
        raise ValueError('H3_REFERENCE_MANIFEST_MISMATCH: cannot project all selected inputs')
    return {**copy.deepcopy(manifest or {}), 'references': refs, 'excluded_references': excluded,
            'picture_projection': [{'source_picture': r['source_picture'], 'picture': r['picture']} for r in projection],
            'selection_source': 'H3_PROMPT_OPTIMIZER', 'actual_binding_verified': False}


def _relation_valid(relation, time, events, spoken, detail):
    if not events:
        return relation is None
    if not isinstance(relation, dict):
        return False
    index = next((i for i, e in enumerate(events) if e.get('id') == relation.get('dialogue_id')), None)
    if index is None or index >= len(spoken) or not _number(time):
        return False
    event, line = events[index], spoken[index]
    start, end = event.get('optimized_start'), event.get('optimized_end')
    if not _number(start) or not _number(end):
        return False
    excerpt = relation.get('prompt_excerpt')
    if not _text(excerpt) or excerpt not in detail:
        return False
    pos = detail.find(excerpt)
    kind = relation.get('position')
    if kind == 'BEFORE':
        return time <= start + 1e-6 and pos + len(excerpt) <= line['span_start']
    if kind == 'AFTER':
        return time >= end - 1e-6 and pos >= line['span_end']
    if kind == 'DURING':
        # Prose may introduce a concurrent action before or after quoting a line.
        # Its meaning still requires semantic review; don't keyword-score English.
        return start - 1e-6 <= time <= end + 1e-6
    return False


def check_anchor_policy(prompt, output, authority, spoken, detail, resolved_evidence=None):
    from app.services.h3_evidence import resolve_output_evidence, excerpt
    evidence = resolved_evidence or resolve_output_evidence(prompt, output, authority)
    policy = authority['anchor_policy'];catalog = policy['catalog']
    timeline = output.get('av_timeline') or {};duration = timeline.get('optimized_duration')
    anchors = timeline.get('anchors')
    anchors = anchors if isinstance(anchors, list) and all(isinstance(a, dict) for a in anchors) else []
    expected = {a['anchor_id']: a for a in catalog}
    choices = {a.get('id'): a for a in anchors}
    checks = {'anchor_decisions_complete': len(anchors) == len(catalog) == len(choices) and set(choices) == set(expected)}
    requirements = output.get('canonical_visual_requirements')
    requirements = requirements if isinstance(requirements, list) and all(isinstance(r, dict) for r in requirements) else []
    sources = {s['id']: s['text'] for s in policy['canonical_visual_sources']}
    requirement_ids = {r.get('id') for r in requirements}
    checks['canonical_visual_requirement_trace'] = (bool(requirements) and len(requirement_ids) == len(requirements)
        and all(_text(r.get('id')) and _text(r.get('requirement')) and r.get('source_id') in sources
                and _text(excerpt(evidence, f'requirements.{i}.source')) for i,r in enumerate(requirements)))
    # Unresolved content is unverified, not proof of absence. Keep it blocked for
    # semantic review; a provenance mismatch with a resolved span is non-blocking.
    checks['canonical_visual_requirement_consistency'] = bool(requirements) and all(
        _text(excerpt(evidence, f'requirements.{i}.prompt')) for i in range(len(requirements)))
    checks.update(anchor_decision_semantics=True, anchor_arrival_relation=True,
                  anchor_arrival_phase_binding=True, anchor_required_outcomes_retained=True,
                  linked_anchor_decision_consistent=True)
    events = timeline.get('dialogue_events') or []
    phases = timeline.get('execution_phases') or []
    for key, old in expected.items():
        a = choices.get(key, {});decision = a.get('decision');time = a.get('optimized_time')
        index = next((i for i,item in enumerate(anchors) if item.get('id') == key), -1)
        valid = decision in {'KEEP', 'RETIME', 'DROP'} and _same(a.get('original_time'), old['original_time']) and _text(a.get('reason'))
        preserved = a.get('preserved_visual_requirements')
        checks['anchor_required_outcomes_retained'] &= (isinstance(preserved, list)
            and all(isinstance(r, str) and r in requirement_ids for r in preserved))
        if decision == 'DROP':
            valid &= (time is None and a.get('delta') is None and a.get('prompt_excerpt') is None
                      and a.get('arrival_relation') is None and _text(a.get('released_constraint')))
        else:
            valid &= (_number(time) and _number(duration) and 0 <= time <= duration
                      and _same(a.get('delta'), time - old['original_time'])
                      and (decision != 'KEEP' or _same(time, old['original_time'])))
            relation = a.get('arrival_relation')
            resolved_relation = ({**relation, 'prompt_excerpt': excerpt(evidence, f'anchors.{index}.relation')}
                                 if isinstance(relation, dict) else relation)
            checks['anchor_arrival_relation'] &= _relation_valid(resolved_relation, time, events, spoken, detail)
        checks['anchor_decision_semantics'] &= valid
        if old.get('linked_anchor_id'):
            linked = choices.get(old['linked_anchor_id'], {})
            checks['linked_anchor_decision_consistent'] &= ((decision == 'DROP') == (linked.get('decision') == 'DROP')
                and (decision == 'DROP' or _same(time, linked.get('optimized_time'))))
    for phase in phases:
        if not isinstance(phase, dict) or phase.get('type') != 'ANCHOR_ARRIVAL':
            continue
        anchor_id = phase.get('anchor_id')
        if anchor_id is None:
            # Accept an unambiguous stable ID in ordinary description, as in
            # historical point events; no camera/action wording interpretation.
            named = [key for key in choices if re.search(
                r'(?<![A-Za-z0-9_])' + re.escape(key) + r'(?![A-Za-z0-9_])', str(phase.get('description', '')))]
            anchor_id = named[0] if len(named) == 1 else None
        a = choices.get(anchor_id, {})
        checks['anchor_arrival_phase_binding'] &= (a.get('decision') in {'KEEP', 'RETIME'}
            and all(_number(v) for v in (phase.get('start'), phase.get('end'), a.get('optimized_time')))
            and phase['start'] <= a['optimized_time'] <= phase['end'])
    bindings = projected_bindings(authority, anchors)
    projection = [{'source_picture': r['source_picture'], 'picture': r['picture']} for r in bindings]
    checks['reference_projection_consistent'] = output.get('reference_projection') == projection
    checks['picture_presence'] = set(re.findall(r'<Picture \d+>', prompt)) == {r['picture'] for r in bindings}
    mapping = {r['source_picture']: r['picture'] for r in bindings}
    checks['retained_anchor_picture_binding'] = all(
        not old.get('source_picture') or choices.get(old['anchor_id'], {}).get('decision') == 'DROP'
        or mapping.get(old['source_picture'], '__missing__') in (excerpt(evidence, f'anchors.{i}.prompt') or '')
        for old in catalog for i,a in enumerate(anchors) if a.get('id') == old['anchor_id'])
    has_drop = any(choices.get(a['anchor_id'], {}).get('decision') == 'DROP'
                   and (a.get('source_picture') or a.get('source_kind') == 'TEMPORAL_ANCHOR') for a in catalog)
    checks['drop_binding_supported'] = not has_drop or policy['drop_binding'].get('supported') is True
    return checks, bindings
