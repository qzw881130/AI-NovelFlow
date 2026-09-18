"""Read-only dependencies for the sole RSA producer; consumers validate frozen choices, never replace them."""
from copy import deepcopy
from fastapi import HTTPException
from app.models.shot import Shot
from app.models.novel import Character, Scene, Prop
from app.models.chapter_shot_split import ChapterShotSplitRun
from app.models.appearance_timeline import CharacterAppearance, AppearanceTimelineRun
from app.services.chapter_shot_split_service import checked_source
from app.services.appearance_timeline_service import AppearanceTimelineService, selection_signature
from app.services.chapter_asset_parse_service import digest


def entity_definition(db, kind, asset_id, novel_id):
    model = {"characters":Character,"scenes":Scene,"props":Prop}[kind]
    asset = db.get(model,asset_id)
    if not asset or asset.novel_id != novel_id:
        raise HTTPException(409,"RSA_ASSET_SCOPE_MISMATCH")
    result = {"id":asset.id,"novel_id":asset.novel_id,"name":asset.name,"description":asset.description}
    field = "setting" if kind == "scenes" else "appearance"
    result[field] = getattr(asset,field)
    if kind == "characters":
        if not asset.identity or asset.is_narrator:
            raise HTTPException(409,"RSA_CHARACTER_IDENTITY_INVALID")
        result.update(entity_type=asset.identity.entity_type,group_size_hint=asset.identity.group_size_hint)
    return result


def appearance_definition(db, appearance_id, actor_id, novel_id):
    asset = db.get(CharacterAppearance,appearance_id)
    if (not asset or asset.novel_id != novel_id or asset.character_id != actor_id or digest(asset.definition) != asset.definition_hash):
        raise HTTPException(409,"RSA_APPEARANCE_DEFINITION_INVALID")
    return {"id":asset.id,"character_id":actor_id,"novel_id":novel_id,"definition_hash":asset.definition_hash,
        "definition":deepcopy(asset.definition),"description":asset.description}


def collect_logical_assets(db, shot_id):
    shot = db.get(Shot,shot_id)
    if not shot:
        raise HTTPException(404,"分镜不存在")
    source = checked_source(db,shot)
    split = db.get(ChapterShotSplitRun,source.run_id)
    novel_id = split.novel_id
    source_proof = {"shot_id":shot.id,"split_run_id":source.run_id,"seal":source.visual_seal,"source_hash":source.source_hash,
        "source_start":source.source_start,"source_end":source.source_end,"ranges":deepcopy(source.ranges)}
    logic = {"shot_id":shot.id,"novel_id":novel_id,"chapter_id":shot.chapter_id,"source":source_proof,
        "timeline":deepcopy(split.inputs["basis"]["timeline"]),"characters":[],"scene":None,"props":[]}
    timeline = AppearanceTimelineService(db)
    for binding in source.bindings["characters"]:
        actor_id = binding["assetId"]
        selected = timeline.at(novel_id,shot.chapter_id,actor_id,source.source_start)
        ending = timeline.at(novel_id,shot.chapter_id,actor_id,source.source_end-1)
        if (not selected["logicalReady"] or selected["start"] > source.source_start or selected["end"] < source.source_end
                or selection_signature(selected["selection"]) != selection_signature(ending["selection"])):
            raise HTTPException(409,"RSA_APPEARANCE_UNRESOLVED_OR_CROSSED")
        choice = selected["selection"]
        if choice["kind"] not in {"BASE","APPEARANCE"}:
            raise HTTPException(409,"RSA_EXPLICIT_APPEARANCE_CHOICE_REQUIRED")
        actor = {"character_id":actor_id,"binding":deepcopy(binding),"definition":entity_definition(db,"characters",actor_id,novel_id),
            "selection":{**selection_signature(choice),"reason":choice["reason"]},"timeline_run_id":selected["timelineRunId"],
            "appearance_id":choice["appearanceId"] if choice["kind"] == "APPEARANCE" else None}
        if choice["kind"] == "APPEARANCE":
            actor["appearance_definition"] = appearance_definition(db,choice["appearanceId"],actor_id,novel_id)
        elif choice["appearanceId"] is not None:
            raise HTTPException(409,"RSA_BASE_CHOICE_INVALID")
        logic["characters"].append(actor)
    scenes = source.bindings["scenes"]
    if len(scenes) != 1:
        raise HTTPException(409,"RSA_SCENE_BINDING_REQUIRED")
    logic["scene"] = {"scene_id":scenes[0]["assetId"],"binding":deepcopy(scenes[0]),"definition":entity_definition(db,"scenes",scenes[0]["assetId"],novel_id)}
    logic["props"] = [{"prop_id":b["assetId"],"binding":deepcopy(b),"definition":entity_definition(db,"props",b["assetId"],novel_id)} for b in source.bindings["props"]]
    return logic


def validate_logical_dependencies(db, logic):
    """Validate the stored relation and definitions. Do not run the appearance selector again."""
    shot = db.get(Shot,logic["shot_id"])
    if not shot or shot.chapter_id != logic["chapter_id"]:
        raise HTTPException(409,"RSA_SHOT_REMOVED")
    source = checked_source(db,shot)
    expected = logic["source"]
    if (source.run_id != expected["split_run_id"] or source.visual_seal != expected["seal"] or source.source_hash != expected["source_hash"]
            or source.source_start != expected["source_start"] or source.source_end != expected["source_end"] or source.ranges != expected["ranges"]):
        raise HTTPException(409,"RSA_SOURCE_CHANGED")
    split = db.get(ChapterShotSplitRun,source.run_id)
    if split.novel_id != logic["novel_id"] or split.inputs["basis"]["timeline"] != logic["timeline"]:
        raise HTTPException(409,"RSA_TIMELINE_CHANGED")
    timeline = db.get(AppearanceTimelineRun,logic["timeline"]["run_id"]) if logic["timeline"] else None
    chapter = next((c for c in timeline.result["chapters"] if c["chapterId"] == shot.chapter_id),None) if timeline else None
    by_kind = {"characters":logic["characters"],"scenes":[logic["scene"]],"props":logic["props"]}
    for kind, entries in by_kind.items():
        if [e["binding"] for e in entries] != source.bindings[kind]:
            raise HTTPException(409,"RSA_BINDING_SET_CHANGED")
        for entry in entries:
            field = {"characters":"character_id","scenes":"scene_id","props":"prop_id"}[kind]
            if entry[field] != entry["binding"]["assetId"]:
                raise HTTPException(409,"RSA_ASSET_ID_DIFFERS_FROM_BINDING")
            if entity_definition(db,kind,entry["binding"]["assetId"],logic["novel_id"]) != entry["definition"]:
                raise HTTPException(409,"RSA_ASSET_DEFINITION_CHANGED")
            if kind == "characters":
                member = next((c for c in chapter["characters"] if c["characterId"]==entry["character_id"]),None) if chapter else None
                segment = next((s for s in member["segments"] if s["start"]<=source.source_start and source.source_end<=s["end"]),None) if member else None
                if (not segment or entry["timeline_run_id"] != timeline.id or segment["selection"]["kind"] not in {"BASE","APPEARANCE"}
                        or entry["selection"] != {**selection_signature(segment["selection"]),"reason":segment["selection"]["reason"]}
                        or entry["appearance_id"] != segment["selection"]["appearanceId"]):
                    raise HTTPException(409,"RSA_SELECTION_DIFFERS_FROM_FROZEN_TIMELINE")
            if kind == "characters" and entry["appearance_id"] is not None:
                if appearance_definition(db,entry["appearance_id"],entry["character_id"],logic["novel_id"]) != entry["appearance_definition"]:
                    raise HTTPException(409,"RSA_APPEARANCE_DEFINITION_CHANGED")
    return source


def image_slots(logic):
    slots = [(f"character:{c['character_id']}","CHARACTER_APPEARANCE" if c["appearance_id"] else "CHARACTER_BASE",c["appearance_id"] or c["character_id"])
             for c in logic["characters"]]
    slots.append(("scene","SCENE",logic["scene"]["scene_id"]))
    slots.extend(("prop:"+p["prop_id"],"PROP",p["prop_id"]) for p in logic["props"])
    return slots
