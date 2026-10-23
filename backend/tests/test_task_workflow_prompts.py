from types import SimpleNamespace
import json

from app.api.tasks import _extract_character_prompt_items
from app.api.tasks import get_task_clip_workflow, get_task_workflow
from app.models.task import Task
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.models.novel import Chapter, Novel
from app.services.task_service import TaskService
from app.repositories import TaskRepository


def test_task_workflow_response_includes_configured_node_mapping(db_session):
    workflow = Workflow(
        id="video-workflow", name="H3 continuation", type="VIDEO_CONTINUATION",
        node_mapping=json.dumps({"load_video_node_id": "66", "video_save_node_id": "39"}),
        workflow_json="{}",
    )
    task = Task(
        id="video-task-mapped", type="shot_video", name="Video", status="completed",
        workflow_id=workflow.id, workflow_json=json.dumps({"66": {"inputs": {"video": "source.mp4"}}}),
    )
    db_session.add_all([workflow, task])
    db_session.commit()

    response = __import__("asyncio").run(get_task_workflow(task.id, TaskRepository(db_session), db_session))

    assert response["data"]["nodeMapping"] == {"load_video_node_id": "66", "video_save_node_id": "39"}


def test_clip_workflow_response_includes_clip_workflow_node_mapping(db_session):
    novel = Novel(id="mapped-novel", title="Novel")
    chapter = Chapter(id="mapped-chapter", novel_id=novel.id, number=1, title="Chapter")
    workflow = Workflow(
        id="mapped-clip-workflow", name="H3 continuation", type="VIDEO_CONTINUATION",
        node_mapping=json.dumps({"load_video_node_id": "66", "video_save_node_id": "39"}),
        workflow_json="{}",
    )
    shot = Shot(id="mapped-shot", chapter_id=chapter.id, index=1)
    task = Task(
        id="mapped-clip-task", type="shot_video", name="Clip task", status="completed",
        novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id, workflow_id=workflow.id,
        video_director_clips=json.dumps([{"window_index": 2, "workflow_json": {"66": {"inputs": {"video": "source.mp4"}}}}]),
    )
    db_session.add_all([novel, chapter, workflow, shot, task])
    db_session.commit()

    response = __import__("asyncio").run(
        get_task_clip_workflow(task.id, 2, db_session, TaskRepository(db_session))
    )

    assert response["data"]["nodeMapping"] == {"load_video_node_id": "66", "video_save_node_id": "39"}


def test_extract_character_prompt_items_in_concat_order():
    task = SimpleNamespace(type="character_portrait")
    workflow = {
        "489": {
            "inputs": {"prompt": "人物外貌文本"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#489 人物形象"},
        },
        "490": {
            "inputs": {"prompt": "视觉风格文本"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#490 STYLE"},
        },
        "492": {
            "inputs": {"prompt": "四视图布局文本"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#492 四视图"},
        },
        "600": {
            "inputs": {"prompt": "不应展示的辅助文本"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "辅助参数"},
        },
    }

    items = _extract_character_prompt_items(
        task,
        workflow,
        {"appearance_node_id": "489", "style_node_id": "490"},
    )

    assert [(item["role"], item["nodeId"], item["content"]) for item in items] == [
        ("layout", "492", "四视图布局文本"),
        ("style", "490", "视觉风格文本"),
        ("appearance", "489", "人物外貌文本"),
    ]


def test_task_list_exposes_task_and_clip_seeds():
    task = Task(
        id="video-task",
        type="shot_video",
        name="生成视频",
        status="completed",
        progress=100,
        seed=12345,
        video_director_clips=json.dumps([
            {"window_index": 1, "seed": 111, "status": "SUCCEEDED"},
            {
                "window_index": 2,
                "status": "SUCCEEDED",
                "workflow_json": {"8": {"inputs": {"noise_seed": 222}}},
            },
        ]),
    )

    formatted = TaskService.format_task_list([task], {}, {}, {})[0]

    assert formatted["seed"] == 12345
    assert [clip["seed"] for clip in formatted["videoDirectorClips"]] == [111, 222]
