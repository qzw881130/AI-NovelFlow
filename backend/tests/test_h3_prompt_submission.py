"""Service-boundary tests; run with --noconftest and plugin autoload disabled."""

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


pytestmark = pytest.mark.PURE

BACKEND = Path(__file__).resolve().parents[1]
PROMPT = "subject_definitions:\n<Subject 1>\nsummary:\nThe approved shot."


@pytest.fixture
def boundary(monkeypatch):
    # Standalone modules avoid app/services startup and the real HTTP client.
    package_name = "_isolated_h3_prompt_submission"
    for name in ("app", "app.utils", "app.services", package_name):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    load("app.utils.workflow_disconnect", BACKEND / "app/utils/workflow_disconnect.py")
    state_diagnostics = load(
        "app.services.external_failure_diagnostic",
        BACKEND / "app/services/external_failure_diagnostic.py",
    )
    monkeypatch.setattr(sys.modules["app.services"], "external_failure_diagnostic", state_diagnostics, raising=False)
    load(f"{package_name}.workflows", BACKEND / "app/services/comfyui/workflows.py")
    state = SimpleNamespace(events=[], built=[], queued=[], allowed=True, diagnostics=state_diagnostics)

    async def upload_image(path):
        state.events.append(f"image:{path}")
        return {"success": True, "filename": f"uploaded/{path}"}

    async def upload_audio(path):
        state.events.append(f"audio:{path}")
        return {"success": True, "filename": f"uploaded/{path}"}

    async def queue(workflow):
        state.events.append("queue")
        state.queued.append(deepcopy(workflow))
        return {"success": True, "prompt_id": "prompt-test"}

    async def wait(*args, **kwargs):
        state.events.append("wait")
        return {"success": True, "video_url": "/test.mp4"}

    state.client = SimpleNamespace(
        upload_image=AsyncMock(side_effect=upload_image),
        upload_audio=AsyncMock(side_effect=upload_audio),
        queue_prompt=AsyncMock(side_effect=queue),
        wait_for_result=AsyncMock(side_effect=wait),
    )
    client_module = ModuleType(f"{package_name}.client")
    client_module.ComfyUIClient = lambda: state.client
    monkeypatch.setitem(sys.modules, client_module.__name__, client_module)
    state.module = load(f"{package_name}.service", BACKEND / "app/services/comfyui/service.py")
    state.service = state.module.ComfyUIService()
    build = state.service.builder.build_video_workflow

    def capture_build(**kwargs):
        workflow = build(**kwargs)
        state.built.append(workflow)
        state.events.append("build")
        return workflow

    monkeypatch.setattr(state.service.builder, "build_video_workflow", capture_build)

    def before_submit(workflow):
        state.events.append("callback")
        if not state.allowed:
            raise ValueError("test gate blocked")

    state.callback = Mock(side_effect=before_submit)
    state.workflow = {
        "51": {"class_type": "CR Prompt Text", "inputs": {"prompt": "old prompt"}},
        "54": {"class_type": "MiniMaxH3AudioConditioningT8", "inputs": {
            "prompt": ["51", 0], "drive_audio": ["61", 0], "final_audio": ["91", 0],
            "ref_images.ref_image_0": ["45", 0],
        }},
        "49": {"class_type": "BasicGuider", "inputs": {"conditioning": ["54", 0]}},
        "45": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "61": {"class_type": "LoadAudio", "inputs": {"audio": "old-drive.wav"}},
        "91": {"class_type": "LoadAudio", "inputs": {"audio": "old-final.wav"}},
        "kf": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "out": {"class_type": "SaveVideo", "inputs": {"video": ["54", 1]}},
    }
    state.mapping = {
        "prompt_node_id": "51", "video_save_node_id": "out",
        "reference_image_node_id": "45", "drive_audio_node_id": "61",
        "final_audio_node_id": "91", "reference_audio_node_id": "61",
        "keyframe_node_1": "kf",
    }
    return state


def submit(boundary, **kwargs):
    kwargs.setdefault("prompt", PROMPT)
    kwargs.setdefault("workflow_json", json.dumps(boundary.workflow))
    kwargs.setdefault("node_mapping", boundary.mapping)
    kwargs.setdefault("on_before_submit", boundary.callback)
    kwargs.setdefault("seed", 17)
    return asyncio.run(boundary.service.generate_shot_video_with_workflow(**kwargs))


def assert_not_queued(boundary, result, message=""):
    assert result["success"] is False
    assert message in result["message"]
    assert "submitted_workflow" not in result
    assert "submittedWorkflow" not in result
    assert "prompt_id" not in result
    boundary.client.queue_prompt.assert_not_awaited()
    boundary.client.wait_for_result.assert_not_awaited()


@pytest.mark.parametrize("filename", [
    "video_minimax_h3_audiodrive.json",
    "first_last_video_minimax_h3_audiodrive.json",
    "three_frame_video_minimax_h3_audiodrive.json",
    "four_frame_video_minimax_h3_audiodrive.json",
    "video_minimax_h3_ref2va_fast.json",
    "first_last_video_minimax_h3_ref2va.json",
    "three_frame_video_minimax_h3_ref2va.json",
    "four_frame_video_minimax_h3_ref2va.json",
])
@pytest.mark.parametrize("renumber", [False, True])
def test_shipped_h3_graphs_submit_exact_prompt(boundary, filename, renumber):
    boundary.workflow = json.loads((BACKEND / "workflows" / filename).read_text(encoding="utf-8"))
    audio_drive = "audiodrive" in filename
    prompt_id, field = ("51", "prompt") if audio_drive else ("138", "value")
    boundary.mapping = {
        "prompt_node_id": prompt_id,
        "video_save_node_id": "95" if audio_drive else "150",
    }
    if renumber:
        ids = {node_id: str(index + 1000) for index, node_id in enumerate(boundary.workflow)}
        for node in boundary.workflow.values():
            for value in node.get("inputs", {}).values():
                if isinstance(value, list) and len(value) == 2 and value[0] in ids:
                    value[0] = ids[value[0]]
        boundary.workflow = {ids[node_id]: node for node_id, node in boundary.workflow.items()}
        boundary.mapping = {key: ids[value] for key, value in boundary.mapping.items()}
        prompt_id = ids[prompt_id]

    result = submit(boundary)

    assert result["success"] is True
    assert result["prompt_id"] == "prompt-test"
    assert result["video_url"] == "/test.mp4"
    assert result["submitted_workflow"] == boundary.queued[0]
    assert boundary.queued[0][prompt_id]["inputs"][field] == PROMPT
    assert boundary.module.resolve_h3_consumed_prompt(boundary.queued[0], boundary.mapping) == PROMPT
    assert boundary.events == ["build", "callback", "queue", "wait"]
    boundary.callback.assert_called_once_with(result["submitted_workflow"])
    boundary.client.wait_for_result.assert_awaited_once_with(
        "prompt-test", result["submitted_workflow"], boundary.mapping["video_save_node_id"], timeout=7200,
    )


def test_shared_prompt_through_h3_conditioners_and_literal_chain_is_pure(boundary):
    boundary.workflow["bridge"] = {
        "class_type": "PrimitiveStringMultiline", "inputs": {"value": ["51", 0]},
    }
    boundary.workflow["other"] = {
        "class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": ["bridge", 0]},
    }
    boundary.workflow["other-guider"] = {
        "class_type": "BasicGuider", "inputs": {"conditioning": ["other", 0]},
    }
    original = deepcopy(boundary.workflow)
    assert boundary.module.resolve_h3_consumed_prompt(boundary.workflow, boundary.mapping) == "old prompt"
    assert boundary.workflow == original
    assert submit(boundary)["success"] is True


@pytest.mark.parametrize("mapping", [
    None, {}, {"prompt_node_id": ""}, {"prompt_node_id": "missing"},
    {"prompt_node_id": 51}, {"prompt_node_id": []},
])
def test_invalid_prompt_mapping_fails_closed(boundary, mapping):
    if mapping == {"prompt_node_id": ""}:
        boundary.workflow[""] = boundary.workflow.pop("51")
        boundary.workflow["54"]["inputs"]["prompt"] = ["", 0]
    with pytest.raises(ValueError, match="mapping"):
        boundary.module.resolve_h3_consumed_prompt(boundary.workflow, mapping)
    assert_not_queued(boundary, submit(boundary, node_mapping=mapping))
    boundary.callback.assert_not_called()


@pytest.mark.parametrize("consumed", ["old prompt", PROMPT])
def test_unconnected_mapped_literal_is_not_evidence_of_submission_text(boundary, consumed):
    boundary.workflow["51"]["inputs"]["prompt"] = consumed
    boundary.workflow["decoy"] = {"class_type": "CR Prompt Text", "inputs": {"prompt": "decoy"}}
    boundary.mapping["prompt_node_id"] = "decoy"
    assert_not_queued(boundary, submit(boundary), "unconnected")


@pytest.mark.parametrize("consumed", ["conflicting prompt", PROMPT])
def test_independent_h3_prompt_consumers_are_rejected(boundary, consumed):
    boundary.workflow["other"] = {
        "class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": consumed},
    }
    message = "unconnected" if consumed == PROMPT else "Conflicting"
    assert_not_queued(boundary, submit(boundary), message)


@pytest.mark.parametrize("class_type,field", [
    ("CLIPTextEncode", "text"),
    ("StringConcatenate", "text"),
    ("MiniMaxH3PromptEnhancerT8", "prompt"),
    ("MiniMaxH3AudioConditioningT8", "prompt"),
])
def test_unknown_or_non_string_prompt_chains_fail(boundary, class_type, field):
    boundary.workflow["51"] = {"class_type": class_type, "inputs": {field: "old prompt"}}
    assert_not_queued(boundary, submit(boundary), "Unsupported dynamic H3 prompt chain")


def test_unknown_h3_consumer_cannot_hide_beside_a_supported_one(boundary):
    boundary.workflow["other"] = {"class_type": "MiniMaxH3UnknownConditioner", "inputs": {"text": PROMPT}}
    assert_not_queued(boundary, submit(boundary), "Unsupported H3 node semantics")


def test_h3_without_known_prompt_consumer_fails(boundary):
    boundary.workflow["54"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {}}
    assert_not_queued(boundary, submit(boundary), "no supported prompt consumer")


@pytest.mark.parametrize("slot", [1, -1, "0", 0.0, False, None])
@pytest.mark.parametrize("class_type,field", [("CR Prompt Text", "prompt"), ("PrimitiveStringMultiline", "value")])
def test_literal_string_output_slot_must_be_certain(boundary, slot, class_type, field):
    boundary.workflow["51"] = {"class_type": class_type, "inputs": {field: "old prompt"}}
    boundary.workflow["54"]["inputs"]["prompt"] = ["51", slot]
    assert_not_queued(boundary, submit(boundary), "output slot")


@pytest.mark.parametrize("link", [["51"], ["51", 0, 0], [51, 0], ["missing", 0], None, 42])
def test_malformed_prompt_links_fail(boundary, link):
    boundary.workflow["54"]["inputs"]["prompt"] = link
    assert_not_queued(boundary, submit(boundary), "H3")


def test_cyclic_string_chain_terminates_without_queue(boundary):
    for source, target in (("a", "b"), ("b", "a")):
        boundary.workflow[source] = {"class_type": "CR Prompt Text", "inputs": {"prompt": [target, 0]}}
    boundary.workflow["54"]["inputs"]["prompt"] = ["a", 0]
    assert_not_queued(boundary, submit(boundary), "Cyclic")


@pytest.mark.parametrize("consumed", ["old prompt", PROMPT + "\n", " " + PROMPT])
def test_injection_mismatch_requires_exact_text(boundary, monkeypatch, consumed):
    boundary.workflow["51"]["inputs"]["prompt"] = consumed
    monkeypatch.setattr(boundary.service.builder, "_set_prompt", lambda *args: None)
    assert_not_queued(boundary, submit(boundary), "does not match")
    boundary.callback.assert_not_called()


@pytest.mark.parametrize("callback", [None, False, 42])
def test_h3_requires_a_callable_before_submit(boundary, callback):
    assert_not_queued(boundary, submit(boundary, on_before_submit=callback), "requires on_before_submit")


@pytest.mark.parametrize("asynchronous", [False, True])
def test_callback_exception_vetoes_submission(boundary, asynchronous):
    def reject(workflow):
        raise ValueError("current audit rejected")

    async def reject_async(workflow):
        await asyncio.sleep(0)
        reject(workflow)

    callback = reject_async if asynchronous else reject
    assert_not_queued(boundary, submit(boundary, on_before_submit=callback), "current audit rejected")


def test_async_callback_sees_all_uploaded_media_and_disconnected_inputs(boundary):
    boundary.workflow["unused"] = {"class_type": "LoadImage", "inputs": {"image": ""}}
    boundary.mapping["keyframe_node_2"] = "unused"
    boundary.workflow["consumer"] = {"class_type": "ImageScale", "inputs": {"image": ["unused", 0]}}

    async def audit(workflow):
        await asyncio.sleep(0)
        boundary.events.append("callback")
        assert workflow["45"]["inputs"]["image"] == "uploaded/reference.png"
        assert workflow["61"]["inputs"]["audio"] == "uploaded/drive.wav"
        assert workflow["91"]["inputs"]["audio"] == "uploaded/final.wav"
        assert workflow["kf"]["inputs"]["image"] == "uploaded/keyframe.png"
        assert "image" not in workflow["consumer"]["inputs"]
        assert boundary.module.resolve_h3_consumed_prompt(workflow, boundary.mapping) == PROMPT
        boundary.client.queue_prompt.assert_not_awaited()

    result = submit(
        boundary, character_reference_path="reference.png", drive_audio_path="drive.wav",
        final_audio_path="final.wav", keyframe_paths=["keyframe.png"], on_before_submit=audit,
    )
    assert result["success"] is True
    assert boundary.events == [
        "build", "image:reference.png", "audio:drive.wav", "audio:final.wav",
        "image:keyframe.png", "callback", "queue", "wait",
    ]


def test_sync_callback_returning_future_is_awaited(boundary):
    def audit(workflow):
        future = asyncio.get_running_loop().create_future()

        def finish():
            boundary.events.append("awaited")
            future.set_result(None)

        asyncio.get_running_loop().call_soon(finish)
        return future

    assert submit(boundary, on_before_submit=audit)["success"] is True
    assert boundary.events == ["build", "awaited", "queue", "wait"]


@pytest.mark.parametrize("argument,path,method", [
    ("character_reference_path", "reference.png", "upload_image"),
    ("drive_audio_path", "drive.wav", "upload_audio"),
    ("final_audio_path", "final.wav", "upload_audio"),
    ("reference_audio_path", "legacy.wav", "upload_audio"),
    ("keyframe_paths", ["keyframe.png"], "upload_image"),
])
def test_media_upload_prompt_tampering_cannot_reach_queue(boundary, argument, path, method):
    upload = getattr(boundary.client, method)
    original = upload.side_effect

    async def tamper(path):
        result = await original(path)
        boundary.built[-1]["51"]["inputs"]["prompt"] = "changed during upload"
        return result

    upload.side_effect = tamper
    assert_not_queued(boundary, submit(boundary, **{argument: path}), "does not match")
    upload.assert_awaited_once()
    boundary.callback.assert_not_called()


def test_callback_rechecks_gate_state_changed_during_upload(boundary):
    original = boundary.client.upload_audio.side_effect

    async def change_gate(path):
        boundary.allowed = False
        return await original(path)

    boundary.client.upload_audio.side_effect = change_gate
    assert_not_queued(boundary, submit(boundary, drive_audio_path="drive.wav"), "test gate blocked")
    boundary.callback.assert_called_once()


@pytest.mark.parametrize("phase", ["upload", "callback"])
def test_removing_h3_nodes_cannot_bypass_guard(boundary, phase):
    def remove(workflow):
        workflow["54"]["class_type"] = "LTXVConditioning"

    if phase == "upload":
        async def upload(path):
            remove(boundary.built[-1])
            return {"success": True, "filename": path}

        boundary.client.upload_image.side_effect = upload
        result = submit(boundary, character_reference_path="reference.png")
    else:
        result = submit(boundary, on_before_submit=remove)
    assert_not_queued(boundary, result, "no supported prompt consumer")


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("target", ["prompt", "media"])
def test_callback_cannot_mutate_validated_h3_graph(boundary, asynchronous, target):
    def tamper(workflow):
        node_id, field = ("51", "prompt") if target == "prompt" else ("61", "audio")
        workflow[node_id]["inputs"][field] = "changed during callback"

    async def tamper_async(workflow):
        await asyncio.sleep(0)
        tamper(workflow)

    result = submit(boundary, on_before_submit=tamper_async if asynchronous else tamper)
    message = "does not match" if target == "prompt" else "workflow changed"
    assert_not_queued(boundary, result, message)


@pytest.mark.parametrize("with_callback", [False, True])
def test_non_h3_keeps_optional_callback_and_existing_prompt_behavior(boundary, with_callback):
    boundary.workflow = {
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt"}},
        "ltx": {"class_type": "LTXVConditioning", "inputs": {"positive": ["11", 0]},
                "_meta": {"title": "MiniMaxH3ReferenceToVideo"}},
    }
    boundary.mapping = {"prompt_node_id": "missing", "workflow_name": "MiniMaxH3"}
    assert boundary.module.is_h3_workflow(boundary.workflow) is False

    async def callback(workflow):
        await asyncio.sleep(0)
        workflow["11"]["inputs"]["text"] = "optional callback edit"

    result = submit(boundary, on_before_submit=callback if with_callback else None)
    assert result["success"] is True
    assert boundary.queued[0]["11"]["inputs"]["text"] == ("optional callback edit" if with_callback else "old prompt")
    boundary.client.queue_prompt.assert_awaited_once()
    boundary.client.wait_for_result.assert_awaited_once()


def test_h3_transition_submission_is_outside_this_guard(boundary):
    result = asyncio.run(boundary.service.generate_transition_video_with_workflow(
        workflow_json=json.dumps(boundary.workflow),
        node_mapping={"first_image_node_id": "45", "last_image_node_id": "kf", "video_save_node_id": "out"},
        first_image_path="first.png", last_image_path="last.png",
    ))
    assert result["success"] is True
    assert boundary.queued[0]["51"]["inputs"]["prompt"] == "old prompt"
    boundary.callback.assert_not_called()
    boundary.client.queue_prompt.assert_awaited_once()


def diagnostic(boundary, failure_class="TIMEOUT"):
    return boundary.diagnostics.ExternalFailureDiagnostic.build(
        operation_key={"operation": "UPLOAD_IMAGE", "reference_sha256": "0" * 64, "invocation_no": 1},
        error_code="VALIDATED_REFERENCE_UPLOAD_FAILED", failure_class=failure_class,
        stage="REFERENCE_UPLOAD", operation="UPLOAD_IMAGE", service="comfyui", provider="comfyui",
        reference={"filename": "visual-state-test.png", "bytes": 7, "sha256": "0" * 64},
        external_call={
            "endpoint": "http://comfy.test/upload/image", "method": "POST", "timeout_ms": 30000,
            "exception_type": "ReadTimeout", "exception_message": "timed out", "receipt_status": "NOT_RECEIVED",
        },
        submission={
            "queue_called": False, "submitted": False, "state": "NOT_SUBMITTED", "cid": None,
            "queue_seen": False, "remote_upload_effect": "UNKNOWN",
        },
    )


def test_strict_second_reference_failure_preserves_business_error_and_stops_all_later_work(boundary):
    payloads = [b"primary", b"keyframe"]
    bound = Mock()

    async def upload(path, *, upload_name, payload):
        boundary.events.append(f"strict-image:{path}")
        if path == "keyframe.png":
            return {"success": False, "message": "Image upload failed: timed out",
                    "external_failure": diagnostic(boundary)}
        return {
            "success": True, "filename": upload_name, "subfolder": "", "type": "input",
            "payload_sha256": __import__("hashlib").sha256(payload).hexdigest(), "payload_size": len(payload),
            "message": "uploaded",
        }

    boundary.client.upload_image.side_effect = upload
    result = submit(
        boundary,
        character_reference_path="reference.png",
        keyframe_paths=["keyframe.png"],
        drive_audio_path="drive.wav",
        final_audio_path="final.wav",
        frozen_image_inputs=[
            {"reference_index": index, "source_path": path, "payload": payload,
             "sha256": __import__("hashlib").sha256(payload).hexdigest()}
            for index, (path, payload) in enumerate(zip(("reference.png", "keyframe.png"), payloads))
        ],
        on_image_inputs_bound=bound,
    )

    assert {key: result[key] for key in ("success", "failure_kind", "message")} == {
        "success": False,
        "failure_kind": "VISUAL_STATE_REFERENCE_REJECTED",
        "message": "VALIDATED_REFERENCE_UPLOAD_FAILED",
    }
    failure = result["external_failure"]
    assert failure["failure_class"] == "TIMEOUT"
    assert failure["scope"]["reference_index"] == failure["reference"]["reference_index"] == 1
    assert failure["submission"] == {
        "queue_called": False, "submitted": False, "state": "NOT_SUBMITTED", "cid": None,
        "queue_seen": False, "remote_upload_effect": "UNKNOWN",
    }
    assert boundary.client.upload_image.await_count == 2
    boundary.client.upload_audio.assert_not_awaited()
    bound.assert_not_called()
    boundary.callback.assert_not_called()
    boundary.client.queue_prompt.assert_not_awaited()
    boundary.client.wait_for_result.assert_not_awaited()


@pytest.mark.parametrize("changes,expected_class,violation", [
    ({"success": False}, "UNKNOWN", "SERVICE_UPLOAD_FAILURE_WITHOUT_DIAGNOSTIC"),
    ({"type": "output"}, "INVALID_RECEIPT", "SERVICE_RECEIPT_TYPE_NOT_INPUT"),
    ({"filename": ""}, "INVALID_RECEIPT", "SERVICE_RECEIPT_FILENAME_MISSING"),
    ({"payload_sha256": "0" * 64}, "INVALID_RECEIPT", "SERVICE_RECEIPT_PAYLOAD_SHA256_MISMATCH"),
    ({"payload_size": True}, "INVALID_RECEIPT", "SERVICE_RECEIPT_PAYLOAD_SIZE_INVALID"),
    ({"payload_size": 1}, "INVALID_RECEIPT", "SERVICE_RECEIPT_PAYLOAD_SIZE_MISMATCH"),
])
def test_service_receipt_predicates_emit_only_fixed_violation_codes(boundary, changes, expected_class, violation):
    payload = b"primary-reference"
    bound = Mock()

    async def upload(path, *, upload_name, payload):
        receipt = {
            "success": True, "filename": upload_name, "subfolder": "", "type": "input",
            "payload_sha256": __import__("hashlib").sha256(payload).hexdigest(), "payload_size": len(payload),
            "arbitrary_receipt_dump": "must-not-persist",
        }
        receipt.update(changes)
        return receipt

    boundary.client.upload_image.side_effect = upload
    result = submit(
        boundary,
        character_reference_path="reference.png",
        drive_audio_path="drive.wav",
        frozen_image_inputs=[{
            "reference_index": 0, "source_path": "reference.png", "payload": payload,
            "sha256": __import__("hashlib").sha256(payload).hexdigest(),
        }],
        on_image_inputs_bound=bound,
    )

    assert result["success"] is False
    assert result["failure_kind"] == "VISUAL_STATE_REFERENCE_REJECTED"
    assert result["message"] == "VALIDATED_REFERENCE_UPLOAD_FAILED"
    failure = result["external_failure"]
    assert failure["failure_class"] == expected_class
    assert failure["external_call"]["receipt_violation"] == violation
    assert "must-not-persist" not in json.dumps(failure)
    assert failure["submission"]["cid"] is None
    boundary.client.upload_audio.assert_not_awaited()
    bound.assert_not_called()
    boundary.callback.assert_not_called()
    boundary.client.queue_prompt.assert_not_awaited()
    boundary.client.wait_for_result.assert_not_awaited()


@pytest.mark.parametrize("receipt", [None, [], "not-a-receipt"])
def test_non_object_upload_result_keeps_validated_business_error(boundary, receipt):
    payload = b"primary-reference"
    async def upload(path, *, upload_name, payload):
        return receipt
    boundary.client.upload_image.side_effect = upload
    result = submit(
        boundary,
        character_reference_path="reference.png",
        frozen_image_inputs=[{
            "reference_index": 0, "source_path": "reference.png", "payload": payload,
            "sha256": __import__("hashlib").sha256(payload).hexdigest(),
        }],
        on_image_inputs_bound=Mock(),
    )
    assert {key: result[key] for key in ("success", "failure_kind", "message")} == {
        "success": False,
        "failure_kind": "VISUAL_STATE_REFERENCE_REJECTED",
        "message": "VALIDATED_REFERENCE_UPLOAD_FAILED",
    }
    assert result["external_failure"]["failure_class"] == "INVALID_RECEIPT"
    assert result["external_failure"]["external_call"]["receipt_violation"] == "SERVICE_UPLOAD_RESULT_NOT_OBJECT"
    boundary.client.upload_audio.assert_not_awaited()
    boundary.callback.assert_not_called()
    boundary.client.queue_prompt.assert_not_awaited()
    boundary.client.wait_for_result.assert_not_awaited()
