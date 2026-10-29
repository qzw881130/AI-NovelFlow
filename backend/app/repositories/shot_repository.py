"""
分镜数据仓库

封装分镜相关的数据库查询逻辑
"""
import json
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.shot import Shot
from app.models.task import Task


class ShotRepository:
    """分镜数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_chapter(self, chapter_id: str) -> List[Shot]:
        """
        获取章节的所有分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            分镜列表，按 index 排序
        """
        return self.db.query(Shot).filter(
            Shot.chapter_id == chapter_id
        ).order_by(Shot.index).all()

    def get_by_id(self, shot_id: str) -> Optional[Shot]:
        """
        根据 ID 获取分镜

        Args:
            shot_id: 分镜 ID

        Returns:
            分镜对象或 None
        """
        return self.db.query(Shot).filter(Shot.id == shot_id).first()

    def get_by_chapter_and_index(self, chapter_id: str, index: int) -> Optional[Shot]:
        """
        根据章节 ID 和分镜序号获取分镜

        Args:
            chapter_id: 章节 ID
            index: 分镜序号 (1-based)

        Returns:
            分镜对象或 None
        """
        return self.db.query(Shot).filter(
            Shot.chapter_id == chapter_id,
            Shot.index == index
        ).first()

    def create(
        self,
        chapter_id: str,
        index: int,
        description: str = "",
        characters: List[str] = None,
        scene: str = "",
        props: List[str] = None,
        duration: int = 4,
        **kwargs
    ) -> Shot:
        """
        创建分镜

        Args:
            chapter_id: 章节 ID
            index: 分镜序号 (1-based)
            description: 分镜描述
            characters: 角色名称列表
            scene: 场景名称
            props: 道具名称列表
            duration: 时长（秒）
            **kwargs: 其他字段

        Returns:
            创建的分镜对象
        """
        shot = Shot(
            chapter_id=chapter_id,
            index=index,
            description=description,
            characters=json.dumps(characters or [], ensure_ascii=False),
            scene=scene,
            props=json.dumps(props or [], ensure_ascii=False),
            duration=duration,
            continuity_mode=kwargs.pop("continuity_mode", "NORMAL"),
        )

        # 设置其他字段
        for key, value in kwargs.items():
            if hasattr(shot, key):
                if key in ('characters', 'props', 'dialogues') and isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                setattr(shot, key, value)

        self.db.add(shot)
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def update(self, shot: Shot, **kwargs) -> Shot:
        """
        更新分镜

        Args:
            shot: 分镜对象
            **kwargs: 要更新的字段

        Returns:
            更新后的分镜对象
        """
        for key, value in kwargs.items():
            if hasattr(shot, key):
                if key == 'video_director_plan' and value:
                    plan = json.loads(value) if isinstance(value, str) else dict(value)
                    plan.pop('required_execution_images', None)
                    plan.pop('clip_execution_readiness', None)
                    plan.pop('execution_policy', None)
                    if plan.pop('ai_history_deferred', False) or any(
                        isinstance(call, dict) and call.get('details_deferred')
                        for call in plan.get('ai_calls', [])
                    ):
                        # A page projection is not an edit to historical LLM records.
                        stored = json.loads(shot.video_director_plan or '{}')
                        if 'ai_calls' in stored:
                            plan['ai_calls'] = stored['ai_calls']
                        else:
                            plan.pop('ai_calls', None)
                    value = plan
                # JSON 字段需要序列化
                if key in ('characters', 'props', 'dialogues', 'keyframes', 'video_director_plan') and isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                setattr(shot, key, value)
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def delete(self, shot: Shot) -> None:
        """
        删除分镜

        Args:
            shot: 分镜对象
        """
        self.db.delete(shot)
        self.db.commit()

    def delete_by_chapter(self, chapter_id: str) -> int:
        """
        删除章节的所有分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            删除的分镜数量
        """
        count = self.db.query(Shot).filter(Shot.chapter_id == chapter_id).count()
        self.db.query(Shot).filter(Shot.chapter_id == chapter_id).delete()
        self.db.commit()
        return count

    def bulk_create(self, shots_data: List[dict]) -> List[Shot]:
        """
        批量创建分镜

        Args:
            shots_data: 分镜数据列表，每个元素包含分镜字段

        Returns:
            创建的分镜对象列表
        """
        shots = []
        for data in shots_data:
            # 处理 JSON 字段
            for key in ('characters', 'props', 'dialogues'):
                if key in data and isinstance(data[key], (list, dict)):
                    data[key] = json.dumps(data[key], ensure_ascii=False)

            shot = Shot(**data)
            self.db.add(shot)
            shots.append(shot)

        self.db.commit()
        for shot in shots:
            self.db.refresh(shot)
        return shots

    def count_by_chapter(self, chapter_id: str) -> int:
        """
        统计章节的分镜数量

        Args:
            chapter_id: 章节 ID

        Returns:
            分镜数量
        """
        return self.db.query(Shot).filter(Shot.chapter_id == chapter_id).count()

    def get_pending_image_shots(self, chapter_id: str) -> List[Shot]:
        """
        获取章节中待生成图片的分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            待生成图片的分镜列表
        """
        return self.db.query(Shot).filter(
            Shot.chapter_id == chapter_id,
            Shot.image_status == "pending"
        ).order_by(Shot.index).all()

    def get_pending_video_shots(self, chapter_id: str) -> List[Shot]:
        """
        获取章节中待生成视频的分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            待生成视频的分镜列表
        """
        return self.db.query(Shot).filter(
            Shot.chapter_id == chapter_id,
            Shot.video_status == "pending"
        ).order_by(Shot.index).all()

    def update_image_status(
        self,
        shot: Shot,
        status: str,
        image_url: str = None,
        image_path: str = None,
        task_id: str = None
    ) -> Shot:
        """
        更新分镜图片状态

        Args:
            shot: 分镜对象
            status: 状态 (pending/generating/completed/failed)
            image_url: 图片 URL
            image_path: 图片本地路径
            task_id: 任务 ID

        Returns:
            更新后的分镜对象
        """
        shot.image_status = status
        if image_url is not None:
            shot.image_url = image_url
        if image_path is not None:
            shot.image_path = image_path
        if task_id is not None:
            shot.image_task_id = task_id
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def update_video_status(
        self,
        shot: Shot,
        status: str,
        video_url: str = None,
        task_id: str = None
    ) -> Shot:
        """
        更新分镜视频状态

        Args:
            shot: 分镜对象
            status: 状态 (pending/generating/completed/failed)
            video_url: 视频 URL
            task_id: 任务 ID

        Returns:
            更新后的分镜对象
        """
        shot.video_status = status
        if video_url is not None:
            shot.video_url = video_url
        if task_id is not None:
            shot.video_task_id = task_id
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def update_dialogues(self, shot: Shot, dialogues: List[dict]) -> Shot:
        """
        更新分镜台词数据

        Args:
            shot: 分镜对象
            dialogues: 台词数据列表

        Returns:
            更新后的分镜对象
        """
        shot.dialogues = json.dumps(dialogues, ensure_ascii=False)
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def to_response(self, shot: Shot, *, include_ai_history: bool = True, continuation_mode="AUTO") -> dict:
        """
        将分镜对象转换为响应字典

        Args:
            shot: 分镜对象

        Returns:
            响应字典
        """
        from app.services.required_visual_state_images import (
            project_required_execution_images, project_clip_execution_readiness,
        )
        from app.models.task import Task
        from app.services.clip_execution_compiler import get_canonical_execution_readiness
        from app.services.hd_repaint_service import get_hd_repaint_variants
        from app.services.shot_video_freshness import main_image_newer_than_video

        hd_variants = get_hd_repaint_variants(self.db, shot.id)
        latest_completed_variants = [variant for variant in hd_variants if variant.get("videoUrl")]
        latest_hd = latest_completed_variants[-1] if latest_completed_variants else None
        video_director_plan = json.loads(shot.video_director_plan) if shot.video_director_plan else {}
        if video_director_plan.get("canonical_visual_plan") is True:
            tasks = self.db.query(Task).filter(Task.shot_id == shot.id, Task.type.in_(["shot_image", "shot_image_repair_candidate", "keyframe_image"])).all()
            required = project_required_execution_images(shot, video_director_plan, tasks, continuation_mode=continuation_mode)
            video_director_plan["required_execution_images"] = required
            video_director_plan["clip_execution_readiness"] = project_clip_execution_readiness(self.db, shot, video_director_plan, required, continuation_mode=continuation_mode)
            video_director_plan["execution_readiness"] = get_canonical_execution_readiness(
                shot, video_director_plan, continuation_mode=continuation_mode,
            )
            from app.services.effective_execution import project_effective_execution, projection_record
            video_director_plan["execution_policy"] = {
                "continuation_mode": continuation_mode,
                "clips": [projection_record(project_effective_execution(video_director_plan, c, continuation_mode))
                          for c in video_director_plan.get("clip_plan") or []],
            }
        if not include_ai_history and isinstance(video_director_plan.get("ai_calls"), list):
            # Projection only: never mutate persisted history or the current execution plan.
            summary_fields = {
                "step", "title", "task_type", "prompt_template_name", "status",
                "error_message", "input_summary", "clip_index", "workflow_type",
                "workflow_name", "reference_images", "task_id", "created_at",
            }
            video_director_plan["ai_calls"] = [
                {**{k: v for k, v in call.items() if k in summary_fields},
                 "history_index": index, "details_deferred": True,
                 "has_final_prompt": bool(str(call.get("final_prompt") or "").strip())}
                for index, call in enumerate(video_director_plan["ai_calls"])
                if isinstance(call, dict)
            ]
            video_director_plan["ai_history_deferred"] = True
        return {
            "summaryOnly": False,
            "id": shot.id,
            "chapterId": shot.chapter_id,
            "index": shot.index,
            "description": shot.description,
            "video_description": shot.video_description,
            "shotImagePrompt": shot.shot_image_prompt,
            "characters": json.loads(shot.characters) if shot.characters else [],
            "scene": shot.scene,
            "props": json.loads(shot.props) if shot.props else [],
            "duration": shot.duration,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "videoDirectorPlan": video_director_plan,
            "gridData": json.loads(shot.grid_data) if shot.grid_data else None,
            "imageUrl": shot.image_url,
            "imagePath": shot.image_path,
            "imageStatus": shot.image_status,
            "imageTaskId": shot.image_task_id,
            "videoUrl": shot.video_url,
            "videoStatus": shot.video_status,
            "videoTaskId": shot.video_task_id,
            "mainImageNewerThanVideo": main_image_newer_than_video(self.db, shot),
            "hdVideoVariants": hd_variants,
            "hdVideoUrl": latest_hd.get("videoUrl") if latest_hd else shot.hd_video_url,
            "hdVideoStatus": latest_hd.get("status") if latest_hd else (shot.hd_video_status or "pending"),
            "hdVideoTaskId": latest_hd.get("latestCompletedTaskId") if latest_hd else shot.hd_video_task_id,
            "hdVideoSourceTaskId": latest_hd.get("sourceTaskId") if latest_hd else shot.hd_video_source_task_id,
            "hdVideoMegapixels": latest_hd.get("targetMegapixels") if latest_hd else (float(shot.hd_video_megapixels) if shot.hd_video_megapixels else None),
            "mergedCharacterImage": shot.merged_character_image,
            "mergedPropImage": shot.merged_prop_image,
            "dialogues": json.loads(shot.dialogues) if shot.dialogues else [],
            "keyframes": json.loads(shot.keyframes) if shot.keyframes else [],
            "referenceAudioUrl": shot.reference_audio_url,
            "referenceAudioType": shot.reference_audio_type or "none",
            "createdAt": shot.created_at.isoformat() if shot.created_at else None,
            "updatedAt": shot.updated_at.isoformat() if shot.updated_at else None,
        }

    def to_summary_response(self, shot: Shot, *, image_tasks=(), hd_variants=()) -> dict:
        """Chapter navigation projection. Never expose historical prompts or manifests."""
        from app.services.required_visual_state_images import project_required_execution_images
        from app.services.clip_execution_compiler import get_canonical_execution_readiness
        from app.services.shot_video_freshness import main_image_newer_than_video

        plan = json.loads(shot.video_director_plan or "{}") or {}
        clip_fields = {
            "clip_id", "clip_index", "start_time", "end_time", "planned_duration",
            "capability", "continuity_to_previous", "previous_clip_index",
            "visual_state_indexes", "carry_in_state_index", "requires_temporal_control",
            "temporal_anchor_ids", "selected_temporal_target_ids", "early_composition_state_id",
            "generated_by_task_id", "video_url", "local_path", "execution_status",
            "approval_status", "status",
        }
        state_fields = {"index", "role", "time_seconds", "image_url", "image_task_id"}
        plan_fields = {
            "canonical_visual_plan", "clip_plan_revision", "clip_plan_validation",
            "clip_plan_approval_mode", "assembly_status", "assembly_clip_plan_revision",
            "assembly_task_ids", "merged_video_url", "merged_at", "selected_mode",
            "recommended_mode",
        }
        summary_plan = {key: value for key, value in plan.items() if key in plan_fields}
        summary_plan["clip_plan"] = [
            {key: value for key, value in clip.items() if key in clip_fields}
            for clip in (plan.get("clip_plan") or []) if isinstance(clip, dict)
        ]
        summary_plan["keyframes"] = [
            {key: value for key, value in state.items() if key in state_fields}
            for state in (plan.get("keyframes") or []) if isinstance(state, dict)
        ]
        window_fields = {
            "window_index", "clip_index", "keyframe_indexes", "video_url", "local_path",
            "generated_at", "status", "start_time", "end_time",
        }
        summary_plan["window_plans"] = [
            {key: value for key, value in window.items() if key in window_fields}
            for window in (plan.get("window_plans") or []) if isinstance(window, dict)
        ]
        summary_plan["clips"] = [
            {key: value for key, value in clip.items() if key in window_fields}
            for clip in (plan.get("clips") or []) if isinstance(clip, dict)
        ]
        if plan.get("canonical_visual_plan") is True:
            required = project_required_execution_images(shot, plan, image_tasks)
            summary_plan["required_execution_images"] = [
                {key: item.get(key) for key in (
                    "state_index", "state_id", "ready", "image_url", "active_task",
                    "provenance", "consumer_clip_indexes", "consumers",
                )}
                for item in required
            ]
            summary_plan["execution_readiness"] = get_canonical_execution_readiness(shot, plan)
        latest_hd = next((variant for variant in reversed(hd_variants) if variant.get("videoUrl")), None)
        return {
            "summaryOnly": True,
            "id": shot.id, "chapterId": shot.chapter_id, "index": shot.index,
            "description": shot.description, "video_description": "",
            "characters": json.loads(shot.characters or "[]"), "scene": shot.scene,
            "props": json.loads(shot.props or "[]"), "duration": shot.duration,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "videoDirectorPlan": summary_plan,
            "gridData": json.loads(shot.grid_data) if shot.grid_data else None,
            "imageUrl": shot.image_url, "imagePath": shot.image_path,
            "imageStatus": shot.image_status, "imageTaskId": shot.image_task_id,
            "videoUrl": shot.video_url, "videoStatus": shot.video_status,
            "videoTaskId": shot.video_task_id,
            "mainImageNewerThanVideo": main_image_newer_than_video(self.db, shot),
            "hdVideoVariants": list(hd_variants),
            "hdVideoUrl": latest_hd.get("videoUrl") if latest_hd else shot.hd_video_url,
            "hdVideoStatus": latest_hd.get("status") if latest_hd else (shot.hd_video_status or "pending"),
            "hdVideoTaskId": latest_hd.get("latestCompletedTaskId") if latest_hd else shot.hd_video_task_id,
            "hdVideoSourceTaskId": latest_hd.get("sourceTaskId") if latest_hd else shot.hd_video_source_task_id,
            "hdVideoMegapixels": latest_hd.get("targetMegapixels") if latest_hd else shot.hd_video_megapixels,
            "mergedCharacterImage": shot.merged_character_image,
            "mergedPropImage": shot.merged_prop_image,
            "dialogues": json.loads(shot.dialogues or "[]"),
            "keyframes": [
                {key: frame.get(key) for key in ("frame_index", "plan_keyframe_index", "image_url", "image_task_id")}
                for frame in json.loads(shot.keyframes or "[]")
            ],
            "referenceAudioUrl": shot.reference_audio_url,
            "referenceAudioType": shot.reference_audio_type or "none",
            "createdAt": shot.created_at.isoformat() if shot.created_at else None,
            "updatedAt": shot.updated_at.isoformat() if shot.updated_at else None,
        }
