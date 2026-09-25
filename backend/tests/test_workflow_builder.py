"""
WorkflowBuilder 单元测试
"""

import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from app.services.task_service import TaskService
from app.services.shot_keyframe_service import bypass_failed_prompt_rewrite_nodes, randomize_prompt_rewrite_seeds
from app.utils.workflow_seed import extract_workflow_seed


def load_workflow_builder():
    module_path = Path(__file__).parent.parent / "app" / "services" / "comfyui" / "workflows.py"
    spec = importlib.util.spec_from_file_location("workflows", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WorkflowBuilder


def test_video_workflow_uses_one_explicit_seed_for_all_seed_nodes():
    builder = load_workflow_builder()()
    workflow = {
        "1": {"inputs": {"text": "old"}, "class_type": "CLIPTextEncode"},
        "2": {"inputs": {"seed": 1}, "class_type": "KSampler"},
        "3": {"inputs": {"noise_seed": 2}, "class_type": "RandomNoise"},
    }

    result = builder.build_video_workflow(
        prompt="video prompt",
        workflow_json=json.dumps(workflow),
        node_mapping={"prompt_node_id": "1"},
        seed=4294967296,
    )

    assert result["2"]["inputs"]["seed"] == 4294967296
    assert result["3"]["inputs"]["noise_seed"] == 4294967296
    assert extract_workflow_seed(result) == 4294967296


def test_strict_reference_image_clears_default_load_image_values_and_sets_all_nodes():
    builder = load_workflow_builder()()
    workflow = {
        "137": {"class_type": "LoadImage", "inputs": {"image": "file1.png"}},
        "138": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
    }

    node_ids = builder.prepare_strict_reference_image(workflow)
    assert node_ids == ["137", "138"]
    assert workflow["137"]["inputs"]["image"] == ""
    assert workflow["138"]["inputs"]["image"] == ""

    builder.prepare_strict_reference_image(workflow, "shot-image-upload.png")
    assert workflow["137"]["inputs"]["image"] == "shot-image-upload.png"
    assert workflow["138"]["inputs"]["image"] == "shot-image-upload.png"


def test_video_continuation_keeps_source_audio_and_preserves_previous_video_input():
    builder = load_workflow_builder()()
    workflow = {
        "66": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": "old.mp4"}},
        "105": {"class_type": "PrimitiveFloat", "inputs": {"value": 10}},
        "107": {"class_type": "CR Prompt Text", "inputs": {"prompt": "old prompt"}},
        "39": {"class_type": "VHS_VideoCombine", "inputs": {"filename_prefix": "old"}},
        "97": {"class_type": "MiniMaxH3AVSourceAudioModeParam", "inputs": {"source_audio": "Keep source audio"}},
        "93": {"class_type": "MiniMaxH3SourceAudioPolicy", "inputs": {}},
    }

    result = builder.build_video_continuation_workflow(
        workflow,
        {"load_video_node_id": "66", "duration_seconds_node_id": "105", "prompt_node_id": "107", "video_save_node_id": "39"},
        "previous.mp4",
        10,
        "continue dialogue",
        "clip-2",
    )

    assert result["66"]["inputs"]["video"] == "previous.mp4"
    assert result["97"]["inputs"]["source_audio"] == "Keep source audio"
    assert result["107"]["inputs"]["prompt"] == "continue dialogue"
    assert "regenerated_latent" not in result["93"]["inputs"]


def test_video_continuation_restores_formal_keep_audio_topology():
    builder = load_workflow_builder()()
    workflow = {
        "66": {"inputs": {"video": "old.mp4"}, "class_type": "VHS_LoadVideoFFmpeg"},
        "105": {"inputs": {"value": 10}, "class_type": "PrimitiveFloat"},
        "107": {"inputs": {"prompt": "old"}, "class_type": "CR Prompt Text"},
        "39": {"inputs": {"filename_prefix": "old"}, "class_type": "VHS_VideoCombine"},
        "97": {"inputs": {"source_audio": "Keep source audio"}, "class_type": "MiniMaxH3AVSourceAudioModeParam"},
        "93": {"inputs": {"mode": ["97", 0], "video_info": ["66", 3]}, "class_type": "MiniMaxH3SourceAudioPolicy"},
        "23": {"inputs": {"source_audio": ["93", 0], "latent": ["55", 1]}, "class_type": "MiniMaxH3StartMaskedContext"},
        "3": {"inputs": {"latent_image": ["23", 0]}, "class_type": "SamplerCustomAdvanced"},
        "61": {"inputs": {"samples": ["3", 0]}, "class_type": "VAEDecodeAudio"},
        "62": {"inputs": {"samples": ["3", 0]}, "class_type": "VAEDecode"},
    }
    result = builder.build_video_continuation_workflow(
        workflow,
        {"load_video_node_id": "66", "duration_seconds_node_id": "105", "prompt_node_id": "107", "video_save_node_id": "39"},
        "c1-approved.mp4",
        14,
        "continuation prompt",
        "clip-2",
    )
    assert result["66"]["inputs"]["video"] == "c1-approved.mp4"
    assert result["97"]["inputs"]["source_audio"] == "Keep source audio"
    assert "regenerated_latent" not in result["93"]["inputs"]
    assert result["93"]["inputs"]["video_info"] == ["66", 3]
    assert result["23"]["inputs"]["source_audio"] == ["93", 0]
    assert result["23"]["inputs"]["latent"] == ["55", 1]
    assert result["3"]["inputs"]["latent_image"] == ["23", 0]
    assert result["61"]["inputs"]["samples"] == ["3", 0]
    assert result["62"]["inputs"]["samples"] == ["3", 0]


def test_temporal_extend_preserves_formal_keep_audio_mode_in_api_and_ui_workflows():
    builder = load_workflow_builder()()
    api_workflow = {
        "66": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": "old.mp4"}},
        "105": {"class_type": "PrimitiveFloat", "inputs": {"value": 10}},
        "107": {"class_type": "CR Prompt Text", "inputs": {"prompt": "old prompt"}},
        "39": {"class_type": "VHS_VideoCombine", "inputs": {"filename_prefix": "old"}},
        "97": {"class_type": "MiniMaxH3AVSourceAudioModeParam", "inputs": {"source_audio": "Keep source audio"}},
        "custom": {"class_type": "CustomKeyframes", "inputs": {"conditioning": ["55", 0]}},
        "55": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {}},
    }
    mapping = {
        "load_video_node_id": "66",
        "duration_seconds_node_id": "105",
        "prompt_node_id": "107",
        "video_save_node_id": "39",
        "custom_keyframes_node_id": "custom",
    }
    api_result = builder.build_temporal_extend_workflow(api_workflow, mapping, "previous.mp4", 10, [], "clip-next", "next speech")
    assert api_result["66"]["inputs"]["video"] == "previous.mp4"
    assert api_result["97"]["inputs"]["source_audio"] == "Keep source audio"

    ui_workflow = {
        "nodes": [
            {"id": "66", "type": "VHS_LoadVideoFFmpeg", "widgets_values_named": {"video": "old.mp4"}, "widgets_values": ["old.mp4"]},
            {"id": "105", "type": "PrimitiveFloat", "widgets_values_named": {"value": 10}, "widgets_values": [10]},
            {"id": "107", "type": "CR Prompt Text", "widgets_values_named": {"prompt": "old prompt"}, "widgets_values": ["old prompt"]},
            {"id": "39", "type": "VHS_VideoCombine", "widgets_values_named": {"filename_prefix": "old", "save_output": False}, "widgets_values": ["old"]},
            {"id": "97", "type": "MiniMaxH3AVSourceAudioModeParam", "widgets_values_named": {"source_audio": "Keep source audio"}, "widgets_values": ["Keep source audio"]},
            {"id": "custom", "type": "CustomKeyframes", "inputs": [], "widgets_values": []},
        ],
        "links": [],
    }
    ui_mapping = {**mapping, "custom_keyframes_node_id": "custom"}
    ui_result = builder.build_temporal_extend_workflow(ui_workflow, ui_mapping, "previous.mp4", 10, [], "clip-next", "next speech")
    ui_nodes = {str(node["id"]): node for node in ui_result["nodes"]}
    assert ui_nodes["66"]["widgets_values_named"]["video"] == "previous.mp4"
    assert ui_nodes["97"]["widgets_values_named"]["source_audio"] == "Keep source audio"


def test_workflow_seed_extraction_rejects_ambiguous_values():
    workflow = {
        "1": {"inputs": {"seed": 10}},
        "2": {"inputs": {"noise_seed": 20}},
    }

    assert extract_workflow_seed(workflow) is None


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


def test_inject_prompt_updates_advanced_save_image_prefix():
    builder = load_workflow_builder()()
    workflow = {
        "494": {
            "inputs": {"filename_prefix": "Qwen_image_2.1", "images": ["481", 0]},
            "class_type": "SaveImageAdvanced",
        },
        "117": {"inputs": {"text": "old"}, "class_type": "CLIPTextEncode"},
    }

    result = builder.build_character_workflow(
        prompt="new prompt",
        workflow_json=json.dumps(workflow),
        novel_id="novel-id",
        character_name="角色A",
        node_mapping={"prompt_node_id": "117", "save_image_node_id": "494"},
    )

    assert result["494"]["inputs"]["filename_prefix"] == "story_novel-id/角色A"


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


def test_split_character_nodes_receive_appearance_and_style_without_duplication():
    builder = load_workflow_builder()()
    appearance = "一位欧洲童话王国男性骗子，深蓝粗布外套"
    style = "stylized 3D animation rendering"
    workflow = {
        "489": {
            "inputs": {"prompt": ""},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#489 CR Prompt Text（选这个，人物形象）"},
        },
        "490": {
            "inputs": {"prompt": ""},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#490 STYLE"},
        },
        "492": {
            "inputs": {"prompt": "固定四视图布局"},
            "class_type": "CR Prompt Text",
            "_meta": {"title": "#492 四视图"},
        },
    }

    result = builder.build_character_workflow(
        prompt=style,
        workflow_json=json.dumps(workflow, ensure_ascii=False),
        node_mapping={"prompt_node_id": "489"},
        style=style,
        character_appearance=appearance,
    )

    assert result["489"]["inputs"]["prompt"] == appearance
    assert result["490"]["inputs"]["prompt"] == style
    assert result["492"]["inputs"]["prompt"] == "固定四视图布局"
    assert appearance not in result["490"]["inputs"]["prompt"]


def test_character_mapping_accepts_new_split_contract_and_legacy_prompt_mapping():
    split_workflow = SimpleNamespace(
        name="split",
        node_mapping=json.dumps({
            "appearance_node_id": "489",
            "style_node_id": "490",
            "save_image_node_id": "487",
        }),
    )
    legacy_workflow = SimpleNamespace(
        name="legacy",
        node_mapping=json.dumps({"prompt_node_id": "489", "save_image_node_id": "487"}),
    )
    incomplete_workflow = SimpleNamespace(
        name="incomplete",
        node_mapping=json.dumps({"appearance_node_id": "489", "save_image_node_id": "487"}),
    )

    assert TaskService.validate_workflow_node_mapping(split_workflow, "character") == (True, "")
    assert TaskService.validate_workflow_node_mapping(legacy_workflow, "character") == (True, "")
    valid, message = TaskService.validate_workflow_node_mapping(incomplete_workflow, "character")
    assert valid is False
    assert "人物外貌节点和风格节点" in message


def test_keyframe_rewrite_retry_changes_only_rewrite_seed():
    workflow = {
        "520": {"class_type": "QwenPERewriteT8", "inputs": {"seed": 42, "user_prompt": ["516", 0]}},
        "482": {"class_type": "KSampler", "inputs": {"seed": 123}},
    }

    assert randomize_prompt_rewrite_seeds(workflow) is True
    assert workflow["520"]["inputs"]["seed"] != 42
    assert workflow["520"]["inputs"]["user_prompt"] == ["516", 0]
    assert workflow["482"]["inputs"]["seed"] == 123


def test_keyframe_rewrite_fallback_routes_consumers_to_original_prompt():
    workflow = {
        "516": {"class_type": "CR Prompt Text", "inputs": {"prompt": "final prompt"}},
        "520": {"class_type": "QwenPERewriteT8", "inputs": {"seed": 42, "user_prompt": ["516", 0]}},
        "501": {"class_type": "easy showAnything", "inputs": {"anything": ["520", 0]}},
        "485": {"class_type": "TextEncodeQwenImage21", "inputs": {"prompt": ["501", 0]}},
    }

    assert bypass_failed_prompt_rewrite_nodes(workflow) is True
    assert "520" not in workflow
    assert workflow["501"]["inputs"]["anything"] == ["516", 0]
    assert workflow["485"]["inputs"]["prompt"] == ["501", 0]


def test_keyframe_rewrite_fallback_does_not_remove_unreferenced_rewriter():
    workflow = {
        "516": {"class_type": "CR Prompt Text", "inputs": {"prompt": "final prompt"}},
        "520": {"class_type": "QwenPERewriteT8", "inputs": {"seed": 42, "user_prompt": ["516", 0]}},
    }

    assert bypass_failed_prompt_rewrite_nodes(workflow) is False
    assert "520" in workflow


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
