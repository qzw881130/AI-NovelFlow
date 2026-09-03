"""
WorkflowBuilder 单元测试
"""

import json
import importlib.util
from pathlib import Path


def load_workflow_builder():
    module_path = Path(__file__).parent.parent / "app" / "services" / "comfyui" / "workflows.py"
    spec = importlib.util.spec_from_file_location("workflows", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WorkflowBuilder


def test_inject_prompt_preserves_mapped_style_placeholder_template():
    builder = load_workflow_builder()()
    workflow = {
        "9": {
            "inputs": {"filename_prefix": "character_", "images": ["101", 0]},
            "class_type": "SaveImage",
        },
        "117": {
            "inputs": {"text": "生成这张角色三视图，包括正面，侧面，背面, ##STYLE##"},
            "class_type": "CR Text",
        },
    }

    result = builder.build_character_workflow(
        prompt="anime style, high quality, detailed, professional artwork",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"prompt_node_id": "117", "save_image_node_id": "9"},
        style="anime style, high quality, detailed, professional artwork",
    )

    assert result["117"]["inputs"]["text"] == (
        "生成这张角色三视图，包括正面，侧面，背面, "
        "anime style, high quality, detailed, professional artwork"
    )


def test_inject_prompt_overwrites_mapped_prompt_without_style_placeholder():
    builder = load_workflow_builder()()
    workflow = {
        "133": {
            "inputs": {"text": "prompt here"},
            "class_type": "CLIPTextEncode",
        },
    }

    result = builder.build_character_workflow(
        prompt="完整生成提示词",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"prompt_node_id": "133"},
        style="风格词",
    )

    assert result["133"]["inputs"]["text"] == "完整生成提示词"


def test_inject_prompt_sets_cr_prompt_text_appearance_node_prompt_field():
    builder = load_workflow_builder()()
    workflow = {
        "137": {
            "inputs": {"prompt": "一位约三十岁的人类男性村民"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#137 CR Prompt Text（选这个，人物形象）"},
        },
    }

    result = builder.build_character_workflow(
        prompt="anime style, high quality, detailed, professional artwork",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"prompt_node_id": "137"},
        style="anime style, high quality, detailed, professional artwork",
        character_appearance="温柔的年轻母亲，系着围裙，神情关切",
    )

    assert result["137"]["inputs"]["prompt"] == "温柔的年轻母亲，系着围裙，神情关切"


def test_inject_prompt_keeps_explicit_horn_appearance():
    builder = load_workflow_builder()()
    workflow = {
        "137": {
            "inputs": {"prompt": "默认人物形象"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#137 CR Prompt Text（选这个，人物形象）"},
        },
    }

    result = builder.build_character_workflow(
        prompt="anime style",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"prompt_node_id": "137"},
        style="anime style",
        character_appearance="头上长着鹿角的森林守护者",
    )

    assert result["137"]["inputs"]["prompt"] == "头上长着鹿角的森林守护者"


def test_inject_prompt_sanitizes_human_turnaround_template():
    builder = load_workflow_builder()()
    workflow = {
        "135": {
            "inputs": {
                "prompt": (
                    "重点清晰展示角色最具有辨识度的头部特征，例如脸型或头部轮廓、"
                    "眼睛、眉毛、鼻子、嘴巴、口鼻部、耳朵、毛发、发型、头饰、角、"
                    "触须、鳞片、羽毛以及其他实际存在的头部特征。"
                )
            },
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#135 四视图"},
        },
        "137": {
            "inputs": {"prompt": "默认人物形象"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#137 CR Prompt Text（选这个，人物形象）"},
        },
    }

    result = builder.build_character_workflow(
        prompt="anime style",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"prompt_node_id": "137"},
        style="anime style",
        character_appearance="人类女性，约30岁，头发脑后盘成圆髻，用深蓝色布巾包裹。",
    )

    template_prompt = result["135"]["inputs"]["prompt"]
    assert "头饰、角、触须、鳞片、羽毛" not in template_prompt
    assert "本角色是普通人类" not in template_prompt


def test_inject_prompt_does_not_sanitize_explicit_horn_template():
    builder = load_workflow_builder()()
    workflow = {
        "135": {
            "inputs": {"prompt": "头饰、角、触须、鳞片、羽毛以及其他实际存在的头部特征。"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#135 四视图"},
        },
        "137": {
            "inputs": {"prompt": "默认人物形象"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#137 CR Prompt Text（选这个，人物形象）"},
        },
    }

    result = builder.build_character_workflow(
        prompt="anime style",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"prompt_node_id": "137"},
        style="anime style",
        character_appearance="头上长着鹿角的森林守护者",
    )

    assert result["135"]["inputs"]["prompt"] == "头饰、角、触须、鳞片、羽毛以及其他实际存在的头部特征。"


def test_build_video_workflow_sets_megapixels_when_configured():
    builder = load_workflow_builder()()
    workflow = {
        "11": {"inputs": {"text": ""}, "class_type": "CLIPTextEncode"},
        "36": {"inputs": {"value": 960}, "class_type": "easy int"},
        "132": {"inputs": {"value": 0.4}, "class_type": "PrimitiveFloat"},
    }

    result = builder.build_video_workflow(
        prompt="video prompt",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={
            "prompt_node_id": "11",
            "max_side_node_id": "36",
            "megapixels_node_id": "132",
            "megapixels_value": "0.98",
        },
    )

    assert result["11"]["inputs"]["text"] == "video prompt"
    assert result["132"]["inputs"]["value"] == 0.98
    assert result["36"]["inputs"]["value"] == 960


def test_build_video_workflow_uses_max_side_without_megapixels():
    builder = load_workflow_builder()()
    workflow = {
        "36": {"inputs": {"value": 960}, "class_type": "easy int"},
    }

    result = builder.build_video_workflow(
        prompt="video prompt",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"max_side_node_id": "36"},
        aspect_ratio="16:9",
    )

    assert result["36"]["inputs"]["value"] == 1280


def test_build_video_workflow_sets_string_value_prompt_node():
    builder = load_workflow_builder()()
    workflow = {
        "138": {
            "inputs": {"value": "old prompt"},
            "class_type": "PrimitiveStringMultiline",
            "_meta": {"title": "#138 Input Text (Prompt)"},
        },
    }

    result = builder.build_video_workflow(
        prompt="new video prompt",
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"prompt_node_id": "138"},
    )

    assert result["138"]["inputs"]["value"] == "new video prompt"
