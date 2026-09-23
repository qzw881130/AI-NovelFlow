from types import SimpleNamespace

from app.api.tasks import _extract_character_prompt_items


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
