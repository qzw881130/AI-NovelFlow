"""API orchestration: Phase1 candidates automatically continue into Phase2."""
from fastapi import HTTPException
from app.services.chapter_asset_parse_service import ChapterAssetParseService
from app.services.asset_resolution_service import AssetResolutionService
from app.services.asset_resolution_service import binding_state


def attach_timeline(db, novel_id, chapter_id, result, kinds):
    if "characters" not in kinds:
        return result
    if binding_state(db, novel_id, chapter_id)["assets"]["characters"]["status"] == "SUCCEEDED":
        from app.services.appearance_timeline_service import AppearanceTimelineService
        try:
            result["timeline"] = AppearanceTimelineService(db).build(novel_id, chapter_id)
        except HTTPException as exc:
            result["timelineError"] = {"status": exc.status_code, "message": str(exc.detail)}
    return result


async def parse_and_resolve(db, novel_id, chapter_id, kinds, llm=None):
    result = await ChapterAssetParseService(db, llm).parse(novel_id, chapter_id, kinds)
    if result["success"]:
        try:
            resolution = await AssetResolutionService(db, llm).resolve(novel_id, chapter_id, kinds)
            result["resolution"] = resolution["data"]
            result["success"] = resolution["success"]
            result["message"] = "身份归并与章回关联已完成" if resolution["success"] else "候选已保存，请检查身份归并或歧义项"
            attach_timeline(db, novel_id, chapter_id, result, kinds)
        except HTTPException as exc:
            result.update(success=False, message=str(exc.detail), resolutionError={"status": exc.status_code, "detail": exc.detail})
    return result
