"""Materialize review media from existing receipts only; never enqueue generation."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import httpx
from app.services.continuous_clip_av import CONTINUOUS_CAPABILITIES, FPS, OVERLAP_FRAMES, probe_clip_av, cache_export_av_probes
from app.services.native_av_mux import remux_native_av
from app.services.comfyui.client import ComfyUIClient
from app.services.file_storage import file_storage
from app.services.video_director_ai import safe_json_dict
from app.utils.path_utils import url_to_local_path, local_path_to_url

_locks = {}
_REVIEWABLE_ERRORS = {'RAW_CLIP_RECEIPT_UNAVAILABLE', 'RAW_CLIP_OUTPUT_UNAVAILABLE', 'RAW_CLIP_AV_PAIR_UNAVAILABLE'}


def _review_projection(metadata, path, task_id):
    """Use physical continuation boundaries, never planned/optimized seconds."""
    physical = metadata['physical_output']
    previous = physical['previous']['physical_output']
    start, end = previous['frame_count'] - OVERLAP_FRAMES, physical['frame_count']
    span = physical.get('assembly_span') or {}
    if (start < 0 or end <= previous['frame_count'] or physical.get('overlap_frames') != OVERLAP_FRAMES
            or span.get('start_frame') != start or span.get('end_frame') != end):
        raise ValueError('CLIP_REVIEW_BOUNDARY_MISMATCH')
    return {'spans': [{'path': str(path), 'task_id': task_id, 'start_frame': start, 'end_frame': end,
                       'physical_output': physical}], 'frame_count': end - start, 'duration': (end - start) / FPS}


async def clip_playback(db, shot, clip_index, novel_id, chapter_id):
    from app.services.shot_video_service import (
        validate_semantic_clip_artifact, _resolve_semantic_clip_assembly_units, _continuous_assembly_projection,
    )
    plan=safe_json_dict(shot.video_director_plan);revision=int(plan.get('clip_plan_revision') or 0)
    clips=sorted([c for c in plan.get('clip_plan',[]) if int(c['clip_index'])<=clip_index],key=lambda c:c['clip_index'])
    current=next((c for c in clips if int(c['clip_index'])==clip_index),None)
    if not current:raise ValueError('CLIP_NOT_FOUND')
    # Reuse the export probe mode: verify the full media hash and stored MP4
    # frame count without decoding the whole cumulative video for every click.
    task,metadata,path=cache_export_av_probes(validate_semantic_clip_artifact)(db,shot,current,revision,novel_id,chapter_id)
    async with _locks.setdefault(task.id,asyncio.Lock()):
        db.refresh(task);metadata=safe_json_dict(task.metadata_json)
        native=(metadata.get('execution_contract') or {}).get('capability') in CONTINUOUS_CAPABILITIES
        if native:
            # Use the mapping captured when this task was submitted. Older tasks
            # predate that snapshot and used node 39 for independent playback.
            clip_output_node_id=(str(metadata.get('clip_video_output_node_id') or '')
                                 if 'clip_video_output_node_id' in metadata else '39')
        else:
            clip_output_node_id='formal_clip_output'
        cached=metadata.get('clip_playback') or {}
        if (cached.get('source_task_id')==task.id and cached.get('source_prompt_id')==task.comfyui_prompt_id
                and cached.get('source_output_node')==clip_output_node_id
                and all(Path(url_to_local_path(cached.get(k) or '') or '/missing').is_file() for k in ['independent_url','cumulative_url'])):
            return cached
        # A review derivative is never stored in independent_url or used as a
        # generation/assembly source. Validate its source and file before reuse.
        review_path = url_to_local_path(cached.get('review_url') or '')
        if (cached.get('source_task_id') == task.id and cached.get('source_prompt_id')==task.comfyui_prompt_id
                and cached.get('source_output_node')==clip_output_node_id
                and not cached.get('independent_url')
                and cached.get('independent_error') in _REVIEWABLE_ERRORS and not metadata.get('comfyui_history')
                and review_path and Path(review_path).is_file()
                and (cached.get('review_provenance') or {}).get('source_sha256') == (metadata.get('physical_output') or {}).get('sha256')):
            expected = _review_projection(metadata, path, task.id)
            provenance = cached['review_provenance']
            if (provenance.get('start_frame') == expected['spans'][0]['start_frame']
                    and provenance.get('end_frame') == expected['spans'][0]['end_frame']
                    and cache_export_av_probes(probe_clip_av)(review_path) == cached.get('review_media')
                    and Path(url_to_local_path(cached.get('cumulative_url') or '') or '/missing').is_file()):
                return cached
        @cache_export_av_probes
        def project_prefix():
            units=_resolve_semantic_clip_assembly_units(db,shot,clips,revision,novel_id,chapter_id)
            return units,_continuous_assembly_projection(db,shot,units,novel_id,chapter_id)
        # Reuses exactly the final-assembly overlap projection and provenance checks.
        units,projection=project_prefix()
        outdir=Path(path).parent/'clip_previews'/task.id;outdir.mkdir(parents=True,exist_ok=True)
        independent_url=task.result_url;independent_media=None
        independent_error = None
        if native:
            try:
                if not clip_output_node_id or clip_output_node_id==str(metadata.get('video_save_node_id') or '65'):
                    raise ValueError('RAW_CLIP_OUTPUT_UNAVAILABLE')
                client=ComfyUIClient.for_product_runtime(db)
                graph=json.loads(task.workflow_json)
                node=graph.get(clip_output_node_id) or {}
                if node.get('class_type') not in {'VHS_VideoCombine','MiniMaxH3StreamLiveExtensionAVToVHS'}:
                    raise ValueError('RAW_CLIP_OUTPUT_UNAVAILABLE')
                async with httpx.AsyncClient(timeout=180) as http:
                    history=metadata.get('comfyui_history') or {}
                    if not history:
                        reply=await http.get(client.base_url+'/history/'+task.comfyui_prompt_id);reply.raise_for_status()
                        history=reply.json().get(task.comfyui_prompt_id) or {}
                    if not history:
                        raise ValueError('RAW_CLIP_RECEIPT_UNAVAILABLE')
                    receipt = history.get('prompt') or []
                    if len(receipt) < 3 or receipt[1] != task.comfyui_prompt_id or receipt[2] != graph:
                        raise ValueError('CLIP_PLAYBACK_RECEIPT_MISMATCH')
                    if clip_output_node_id not in history.get('outputs',{}):raise ValueError('RAW_CLIP_OUTPUT_UNAVAILABLE')
                    raw=client._parse_outputs({clip_output_node_id:history['outputs'][clip_output_node_id]},graph,clip_output_node_id,strict_output_node=True)
                    url=raw.get('video_url') if raw else None
                    if not url:raise ValueError('RAW_CLIP_OUTPUT_UNAVAILABLE')
                    parsed=urlsplit(url);query=parse_qsl(parsed.query,keep_blank_values=True)
                    if not any(k=='filename' and v.endswith('-audio.mp4') for k,v in query):
                        raise ValueError('RAW_CLIP_AV_PAIR_UNAVAILABLE')
                    video_url=urlunsplit(parsed._replace(query=urlencode([(k,v[:-10]+'.mp4' if k=='filename' else v) for k,v in query])))
                    av=outdir/'independent.mp4';video=outdir/'source_video.mp4'
                    for remote,target in [(url,av),(video_url,video)]:
                        response=await http.get(remote);response.raise_for_status()
                        temporary=target.with_suffix('.download');temporary.write_bytes(response.content);os.replace(temporary,target)
                mux=await asyncio.to_thread(remux_native_av,str(video),str(av))
                independent_media=await asyncio.to_thread(probe_clip_av,str(av))
                physical=metadata['physical_output'];span=physical['assembly_span']
                if independent_media['frame_count']!=span['end_frame']-span['start_frame']:
                    raise ValueError('RAW_CLIP_FRAME_COUNT_MISMATCH')
                independent_url=local_path_to_url(str(av))
            except (ValueError, httpx.HTTPError) as exc:
                independent_url = None
                independent_error = str(exc)
        # A single uninterrupted native chain already has its whole cumulative AV.
        full_chain=all((m.get('execution_contract') or {}).get('previous_clip',{}).get('generated_by_task_id')==units[i-1][1].id
                       for i,(_,_,m,_) in enumerate(units) if i)
        if len(units)==1 or native and full_chain:
            cumulative_url=task.result_url
        else:
            cumulative=outdir/'cumulative.mp4'
            if not cumulative.is_file():
                merged=await file_storage.merge_continuous_clip_spans(projection,str(cumulative))
                if not merged.get('success'):raise ValueError(merged.get('message') or 'CLIP_CUMULATIVE_MERGE_FAILED')
            cumulative_url=local_path_to_url(str(cumulative))
        review_url = review_media = review_provenance = review_error = None
        if native and independent_error in _REVIEWABLE_ERRORS:
            try:
                review = _review_projection(metadata, path, task.id)
                # Preserve every existing source/preview, including interrupted exports.
                review_path = outdir / f'cumulative_excerpt_{uuid4().hex[:12]}.mp4'
                rendered = await file_storage.merge_continuous_clip_spans(review, str(review_path))
                if not rendered.get('success'):
                    raise ValueError(rendered.get('message') or 'CLIP_REVIEW_EXPORT_FAILED')
                review_media = rendered['physical_output']
                review_url = local_path_to_url(str(review_path))
                span = review['spans'][0]
                review_provenance = {
                    'kind': 'CUMULATIVE_EXCERPT', 'source_task_id': task.id, 'source_url': task.result_url,
                    'source_sha256': metadata['physical_output']['sha256'], 'source_output_node': '65',
                    'start_frame': span['start_frame'], 'end_frame': span['end_frame'], 'end_exclusive': True,
                    'fps': FPS, 'overlap_frames': OVERLAP_FRAMES, 'overlap_already_blended': True,
                    'is_original_clip': False,
                }
            except (ValueError, OSError) as exc:
                review_error = str(exc)
        result={'source_task_id':task.id,'clip_index':clip_index,'independent_url':independent_url,
                'cumulative_url':cumulative_url,'includes_shared_context':native,
                'independent_media':independent_media,'independent_error':independent_error,'cumulative_frames':projection['frame_count'],
                'source_prompt_id':task.comfyui_prompt_id,'source_output_node':clip_output_node_id,
                'review_url':review_url,'review_media':review_media,'review_provenance':review_provenance,'review_error':review_error}
        db.refresh(task);metadata=safe_json_dict(task.metadata_json);metadata['clip_playback']=result
        task.metadata_json=json.dumps(metadata,ensure_ascii=False);db.commit()
        return result
