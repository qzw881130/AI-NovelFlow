"""Opt-in P0 video integration; --noconftest, temporary media and in-memory DB only."""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from PIL import Image
import pytest
from sqlalchemy.orm import Session

from test_h3_prompt_worker import PROMPT, run_worker
from test_shot_video_execution import change_task, execution, run, worker


def requirement(predicate="character_location", subject="fox", value="tree", **changes):
    return {"predicate": predicate, "subject": subject, "value": value,
            "source": "approved:shot-35", **changes}


def answer(reference, questions):
    return {"image_sha256": reference.sha256, "provider": "isolated-vision", "facts": [
        {**question.model_dump(), "state": "PRESENT", "confidence": "HIGH",
         "evidence": "The named region or relation is clearly visible."} for question in questions
    ]}


@pytest.fixture
def visual(execution, monkeypatch):
    state = execution
    backend = Path(__file__).resolve().parents[1]
    schemas = ModuleType("app.schemas")
    schemas.__path__ = []
    monkeypatch.setitem(sys.modules, "app.schemas", schemas)
    monkeypatch.setattr(sys.modules["app"], "schemas", schemas, raising=False)
    # The inherited worker deliberately has empty package paths: load only these modules.
    for name, relative in (
        ("app.schemas.visual_state", "app/schemas/visual_state.py"),
        ("app.services.visual_state_validator", "app/services/visual_state_validator.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, backend / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        package, attribute = name.rsplit(".", 1)
        monkeypatch.setattr(sys.modules[package], attribute, module, raising=False)
    state.validator = sys.modules["app.services.visual_state_validator"]
    state.observer = SimpleNamespace(observe=AsyncMock(side_effect=answer))
    monkeypatch.setattr(state.validator, "get_visual_state_observer", lambda: state.observer)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("Network forbidden"))
    state.image_uploads = []
    state.original_images = {}
    data = json.loads(state.task.metadata_json)
    state.oldsource = {"task_id": "prior-task", "image_url": "/old-source.png",
                       "visual_state_validation": {"decision": "PASS", "evidence": "not this run"}}
    data["oldsource"] = deepcopy(state.oldsource)
    state.task.metadata_json = json.dumps(data)
    state.db.commit()
    return state


def enable(state, contract=None, *, source=None):
    contract = contract if contract is not None else {"enabled": True, "invariants": [requirement()]}
    data = json.loads(state.task.metadata_json)
    data.update(state.foundation.create_execution_metadata(
        source if source is not None else state.shot, purpose=data["execution_purpose"],
        request={**state.run_request, "visual_state_validation": contract},
    ))
    state.task.metadata_json = json.dumps(data)
    state.db.commit()
    state.frozen_request = deepcopy(data["execution"]["request"])
    if contract.get("enabled") is not True:
        return contract

    # Legacy fixtures use filename bytes, not images. Only opt-in tests need real PNGs.
    for index, path in enumerate(sorted(state.directory.glob("*.png")), 1):
        Image.new("RGB", (5, 4), ((index * 31) % 256, (index * 67) % 256, (index * 97) % 256)).save(path, "PNG")
        state.original_images[str(path)] = path.read_bytes()
    assert len({sha256(payload).hexdigest() for payload in state.original_images.values()}) == len(state.original_images)

    async def upload_image(path, *, payload=None, upload_name=None):
        assert type(payload) is bytes and payload
        assert isinstance(upload_name, str) and upload_name
        state.events.append("upload")
        if state.upload_hook:
            hook, state.upload_hook = state.upload_hook, None
            hook()
        receipt = {"success": True, "filename": upload_name, "type": "input", "subfolder": "",
                   "payload_sha256": sha256(payload).hexdigest(), "payload_size": len(payload)}
        state.image_uploads.append({"path": path, "payload": payload, "upload_name": upload_name,
                                    "receipt": deepcopy(receipt)})
        return receipt

    state.client.upload_image.side_effect = upload_image
    return contract


def report(state, task, decision):
    data = json.loads(task.metadata_json)
    visual = data["visual_state_validation"]
    assert (visual["enabled"], visual["status"], visual["decision"]) == (True, "evaluated", decision)
    assert data["oldsource"] == state.oldsource
    assert data["execution"]["request"] == data["video_run"]["request"] == state.frozen_request
    source = data["execution"]["shot_snapshot"]
    assert visual["source"] == {
        "run_id": data["video_run"]["run_id"], "request_hash": state.execution.digest(state.frozen_request),
        "snapshot_hash": state.execution.digest(source), "plan_revision": source["video_director_plan_revision"],
        "declared_characters": json.loads(source["characters"]), "declared_props": json.loads(source["props"]),
    }
    directory = Path(data["video_run"]["directory"])
    evidence = visual["evidence"]
    path = Path(evidence["path"])
    assert path.is_relative_to(directory)
    assert sha256(path.read_bytes()).hexdigest() == evidence["sha256"]
    assert json.loads(path.read_text()) == {key: value for key, value in visual.items()
                                          if key not in {"status", "evidence", "uploads"}}
    events = [item for item in data["video_observations"] if item["kind"] == "visual-state-validation"]
    assert len(events) == 1 and events[0]["evidence"] == evidence
    artifacts = {item["sha256"]: item for item in visual["artifacts"]}
    assert set(artifacts) == {item["image_sha256"] for item in visual["references"]}
    for reference in visual["references"]:
        artifact = artifacts[reference["image_sha256"]]
        path = Path(artifact["path"])
        payload = state.original_images[state.module.url_to_local_path(reference["source_url"])]
        assert path.is_relative_to(directory)
        assert path.read_bytes() == payload
        assert artifact["sha256"] == sha256(payload).hexdigest()
        assert artifact["bytes"] == len(payload)
        with Image.open(BytesIO(payload)) as image:
            image.verify()
    return visual


def unchanged_shot(state):
    state.db.refresh(state.shot)
    assert {key: getattr(state.shot, key) for key in state.before_shot} == state.before_shot
    assert state.shot_updates == []


@pytest.mark.CANONICAL_DB
@pytest.mark.c03_legal("pending")
def test_strict_upload_timeout_stops_legal_video_before_binding_audio_queue_cid_or_wait(worker, monkeypatch):
    state = worker
    execution_module = __import__("app.services.shot_video_execution", fromlist=["shot_video_execution"])
    diagnostic_module = __import__(
        "app.services.external_failure_diagnostic", fromlist=["external_failure_diagnostic"],
    )
    state.client.base_url = "http://comfy.test"
    monkeypatch.setattr(execution_module, "frozen_client", lambda endpoint: state.client)

    async def timeout(path, *, upload_name, payload):
        assert isinstance(upload_name, str) and type(payload) is bytes and payload
        payload_hash = sha256(payload).hexdigest()
        return {
            "success": False,
            "message": "Image upload failed: timed out",
            "external_failure": diagnostic_module.ExternalFailureDiagnostic.build(
                operation_key={"operation": "UPLOAD_IMAGE", "reference_sha256": payload_hash,
                               "reference_index": 999, "invocation_no": 1},
                error_code="VALIDATED_REFERENCE_UPLOAD_FAILED", failure_class="TIMEOUT",
                stage="REFERENCE_UPLOAD", operation="UPLOAD_IMAGE", service="comfyui", provider="comfyui",
                scope={"book_id": "client-controlled", "task_id": "client-controlled", "reference_index": 999},
                reference={"reference_index": 999, "filename": upload_name, "bytes": len(payload),
                           "sha256": payload_hash},
                external_call={
                    "endpoint": "http://comfy.test/upload/image", "method": "POST", "timeout_ms": 30000,
                    "exception_type": "ReadTimeout", "exception_message": "timed out",
                    "receipt_status": "NOT_RECEIVED",
                },
                submission={
                    "queue_called": False, "submitted": False, "state": "NOT_SUBMITTED", "cid": None,
                    "queue_seen": False, "remote_upload_effect": "UNKNOWN",
                },
            ),
        }

    state.client.upload_image.side_effect = timeout
    run_worker(state)
    task = state.task
    data = json.loads(task.metadata_json)
    slot = data["video_run"]["clips"]["1"]
    failure = slot["external_failure"]
    assert (task.status, task.error_message, task.comfyui_prompt_id) == (
        "failed", "VALIDATED_REFERENCE_UPLOAD_FAILED", None,
    )
    assert data["video_run"]["failure"]["external_failure_id"] == failure["diagnostic_id"]
    assert slot["state"] == "FAILED" and slot["submission"] == {"state": "not_submitted"}
    assert slot["receipt"] is None and "rsa_uploads" not in slot
    assert failure["failure_class"] == "TIMEOUT"
    assert failure["scope"]["book_id"] == task.novel_id != "client-controlled"
    assert failure["scope"]["task_id"] == task.id != "client-controlled"
    assert failure["scope"]["clip_index"] == 1
    assert failure["scope"]["reference_index"] == failure["reference"]["reference_index"] == 0
    binding = data["rsa_binding"]
    assert failure["upstream"] == {
        "rsa_id": binding["rsa_id"], "rsa_hash": binding["rsa_hash"], "manifest_hash": binding["seal"],
    }
    expected_source = next(item for item in binding["images"]
                           if item["sha256"] == failure["reference"]["sha256"]
                           and item["url"] == data["execution"]["working_shot"]["image_url"])
    assert failure["reference"]["source_id"] == expected_source["id"]
    assert failure["submission"] == {
        "queue_called": False, "submitted": False, "state": "NOT_SUBMITTED", "cid": None,
        "queue_seen": False, "remote_upload_effect": "UNKNOWN",
    }
    event = next(item for item in data["video_observations"] if item["kind"] == "worker-result")
    path = Path(event["evidence"]["path"])
    assert sha256(path.read_bytes()).hexdigest() == event["evidence"]["sha256"] == failure["evidence"]["sha256"]
    assert path.stat().st_size <= 32 * 1024
    canonical_evidence = json.dumps(
        json.loads(path.read_text()), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()
    assert failure["evidence"]["evidence_id"] == "ev1_" + sha256(canonical_evidence).hexdigest()
    state.client.upload_image.assert_awaited_once()
    state.client.upload_audio.assert_not_awaited()
    state.client.queue_prompt.assert_not_awaited()
    state.client.wait_for_result.assert_not_awaited()


@pytest.mark.CANONICAL_DB
@pytest.mark.c03_legal("pending")
@pytest.mark.parametrize("case", ["authorization-token", "windows-path"])
def test_real_client_service_worker_persistence_redacts_reviewer_canaries(worker, monkeypatch, case):
    state = worker
    execution_module = __import__("app.services.shot_video_execution", fromlist=["shot_video_execution"])
    client_path = Path(__file__).resolve().parents[1] / "app/services/comfyui/client.py"
    client_spec = importlib.util.spec_from_file_location("_stage_a_real_comfy_client", client_path)
    client_module = importlib.util.module_from_spec(client_spec)
    client_spec.loader.exec_module(client_module)
    seen = {}
    auth_canary = "STAGE_A_AUTH_CANARY_9465"
    windows_canary = r"C:\ComfyUI\private project\reference.png"

    def handler(request):
        if case == "authorization-token":
            response = httpx.Response(
                503,
                content=("upstream denied request\nAuthorization: Token " + auth_canary).encode(),
                headers={"content-type": "text/plain"},
            )
        else:
            response = httpx.Response(
                200, json={"name": windows_canary, "subfolder": "", "type": "input"},
            )
        seen["status"] = response.status_code
        seen["body"] = response.content
        seen["content_type"] = response.headers.get("content-type")
        return response

    transport = httpx.MockTransport(handler)

    class ProbeClient(client_module.ComfyUIClient):
        @property
        def base_url(self):
            return "http://comfy.test"

        def _client(self):
            return httpx.AsyncClient(transport=transport, trust_env=False)

    probe = ProbeClient()
    state.client.base_url = "http://comfy.test"
    state.client.upload_image.side_effect = probe.upload_image
    monkeypatch.setattr(execution_module, "frozen_client", lambda endpoint: state.client)
    run_worker(state)

    task = state.task
    data = json.loads(task.metadata_json)
    compact = data["video_run"]["clips"]["1"]["external_failure"]
    event = next(item for item in data["video_observations"] if item["kind"] == "worker-result")
    evidence_path = Path(event["evidence"]["path"])
    evidence_text = evidence_path.read_text()
    detailed = json.loads(evidence_text)["result"]["external_failure"]
    for canary in (auth_canary, windows_canary):
        assert canary not in evidence_text
        assert canary not in json.dumps(compact, ensure_ascii=False)
    call = detailed["external_call"]
    assert call["http_status"] == seen["status"]
    assert call["response_body_bytes"] == len(seen["body"])
    assert call["response_body_sha256"] == sha256(seen["body"]).hexdigest()
    assert call["response_content_type"] == seen["content_type"]
    assert detailed["redacted"] is True
    assert compact["external_call"]["response_body_sha256"] == call["response_body_sha256"]
    assert (task.status, task.error_message, task.comfyui_prompt_id) == (
        "failed", "VALIDATED_REFERENCE_UPLOAD_FAILED", None,
    )
    assert data["video_run"]["clips"]["1"]["submission"] == {"state": "not_submitted"}
    state.client.upload_audio.assert_not_awaited()
    state.client.queue_prompt.assert_not_awaited()
    state.client.wait_for_result.assert_not_awaited()


def no_generation(state, task, *, prompt_started=False, uploads=0):
    assert task.status == "failed", task.error_message
    assert task.completed_at is not None and task.result_url is None
    data = json.loads(task.metadata_json)
    assert data["video_run"]["phase"] == "failed"
    assert "result" not in data["video_run"] and "result" not in data["execution"]
    assert all(slot["submission"] == {"state": "not_submitted"} and slot["receipt"] is None
               for slot in data["video_run"]["clips"].values())
    assert state.builder.await_count == int(prompt_started)
    if not prompt_started:
        assert "h3_prompt_gate" not in data
    state.llm.assert_not_awaited()
    assert state.client.upload_image.await_count == uploads
    state.client.upload_audio.assert_not_awaited()
    state.client.queue_prompt.assert_not_awaited()
    state.client.wait_for_result.assert_not_awaited()
    state.client.get_prompt_state.assert_not_awaited()
    state.storage.download_video.assert_not_awaited()
    state.storage.merge_videos.assert_not_awaited()
    assert data["oldsource"] == state.oldsource


@pytest.mark.parametrize("execution", [{"reuse": False}], indirect=True)
def test_shot35_tree_intent_but_rock_start_blocks_before_first_h3(visual):
    state = visual
    enable(state)

    def rock_start(reference, questions):
        observed = answer(reference, questions)
        if (reference.clip_index, reference.reference_index) == (1, 0):
            observed["facts"][0]["value"] = "rock"
        return observed

    state.observer.observe.side_effect = rock_start
    task = run(state)
    result = report(state, task, "BLOCK")
    blocked = [item for item in result["findings"] if item["decision"] == "BLOCK"]
    assert len(blocked) == 1
    assert (blocked[0]["raw_decision"], blocked[0]["capability"], blocked[0]["may_confirm"], blocked[0]["may_block"]) == (
        "BLOCK", "coarse_character_location", True, True)
    assert (blocked[0]["reason"], blocked[0]["clip_index"], blocked[0]["reference_index"]) == ("WRONG_START_STATE", 1, 0)
    assert blocked[0]["expected"]["value"] == "tree"
    assert blocked[0]["observed"][0]["value"] == "rock"
    assert blocked[0]["recommended_next_action"] == "EDIT_IMAGE"
    assert "WRONG_START_STATE" in task.error_message
    assert state.observer.observe.await_count == 6
    assert result["uploads"] == {}
    no_generation(state, task)
    unchanged_shot(state)


@pytest.mark.parametrize("execution", [{"audio": True, "reuse": False}], indirect=True)
@pytest.mark.parametrize("conflict,decision,raw_decision", [(True, "WARN", "BLOCK"), (False, "UNKNOWN", "PASS")])
def test_shot116_fine_water_states_are_advisory_after_all_anchors_checked_before_c1(
    visual, conflict, decision, raw_decision,
):
    state = visual
    relations = [requirement("contact_relation", "fox", "shallow_water", source="approved:shot-116"),
                 requirement("environment_relation", "shallow_water", "connected_to:river_main", source="approved:shot-116"),
                 requirement("surface_state", "fox", "wet", source="approved:shot-116")]
    enable(state, {"enabled": True, "invariants": [requirement()], "anchors": [
        {"clip_index": 2, "reference_index": 2, "requirements": relations},
    ]})

    def water_state(reference, questions):
        state.builder.assert_not_awaited()
        state.llm.assert_not_awaited()
        state.client.upload_image.assert_not_awaited()
        state.client.upload_audio.assert_not_awaited()
        state.client.queue_prompt.assert_not_awaited()
        assert reference.payload == state.original_images[state.module.url_to_local_path(reference.source_url)]
        observed = answer(reference, questions)
        for fact in observed["facts"]:
            if conflict and fact["predicate"] in {"contact_relation", "environment_relation"}:
                fact["state"] = "ABSENT"
            elif conflict and fact["predicate"] == "surface_state":
                fact["value"] = "dry"
        return observed

    state.observer.observe.side_effect = water_state
    task = run(state)
    assert task.status == "completed", task.error_message
    result = report(state, task, decision)
    assert result["capability_policy"] == state.validator.CAPABILITY_POLICY_VERSION == "coarse_v1"
    assert result["scope"]["unknown_is_blocking"] is False
    fine = [item for item in result["findings"] if item["expected"]["predicate"] != "character_location"]
    assert len(fine) == 3
    assert {item["reason"] for item in fine} == (
        {"CONTACT_STATE_CONFLICT", "ENVIRONMENT_STATE_CONFLICT", "STATE_CONFLICT"} if conflict else {"STATE_MATCH"})
    assert {(item["clip_index"], item["reference_index"]) for item in fine} == {(2, 2)}
    for item in fine:
        assert (item["decision"], item["raw_decision"], item["capability"], item["may_confirm"], item["may_block"]) == (
            decision, raw_decision, "advisory_only", False, False)
        assert item["expected"]["source"] == "approved:shot-116"
        assert item["expected"]["expected"] == "PRESENT"
        assert item["conflicting_fields"] == ([item["expected"]["predicate"]] if conflict else [])
        fact = item["observed"][0]
        surface = fact["predicate"] == "surface_state"
        assert fact["state"] == ("ABSENT" if conflict and not surface else "PRESENT")
        assert fact["value"] == ("dry" if conflict and surface else item["expected"]["value"])
    coarse = [item for item in result["findings"] if item["expected"]["predicate"] == "character_location"]
    assert len(coarse) == 6 and all(item["decision"] == "PASS" for item in coarse)
    addresses = [(clip, index) for clip in (1, 2) for index in range(3)]
    assert [(call.args[0].clip_index, call.args[0].reference_index) for call in state.observer.observe.await_args_list] == addresses
    assert [(item["clip_index"], item["reference_index"]) for item in result["references"]] == addresses
    last = result["references"][-1]
    assert (last["source_url"], last["keyframe_index"], last["decision"]) == ("/api/files/kf6.png", 6, decision)
    assert state.observer.observe.await_count == len(state.image_uploads) == 6
    assert set(result["uploads"]) == {"1", "2"}
    assert state.builder.await_count == state.llm.await_count == state.client.queue_prompt.await_count == 2
    assert state.client.upload_audio.await_count == 4
    unchanged_shot(state)


@pytest.mark.parametrize("execution", [{"audio": True, "reuse": False}], indirect=True)
def test_coarse_conflict_on_last_selected_frame_of_c2_blocks_before_forced_c1_or_any_upload(visual):
    state = visual
    enable(state)

    def rock_end(reference, questions):
        observed = answer(reference, questions)
        if (reference.clip_index, reference.reference_index) == (2, 2):
            observed["facts"][0]["value"] = "rock"
        return observed

    state.observer.observe.side_effect = rock_end
    task = run(state)
    result = report(state, task, "BLOCK")
    blocked = [item for item in result["findings"] if item["decision"] == "BLOCK"]
    assert len(blocked) == 1
    assert (blocked[0]["reason"], blocked[0]["clip_index"], blocked[0]["reference_index"]) == ("STATE_CONFLICT", 2, 2)
    assert (blocked[0]["raw_decision"], blocked[0]["capability"], blocked[0]["may_confirm"], blocked[0]["may_block"]) == (
        "BLOCK", "coarse_character_location", True, True)
    assert blocked[0]["expected"]["value"] == "tree"
    assert blocked[0]["observed"][0]["value"] == "rock"
    assert [item["decision"] for item in result["references"]] == ["PASS"] * 5 + ["BLOCK"]
    last = result["references"][-1]
    assert (last["source_url"], last["keyframe_index"]) == ("/api/files/kf6.png", 6)
    assert state.observer.observe.await_count == 6
    assert result["uploads"] == {}
    assert "STATE_CONFLICT" in task.error_message
    no_generation(state, task)
    unchanged_shot(state)


@pytest.mark.parametrize("actual,evidence,decision", [
    ("ABSENT", "The entire region is clearly visible; no bag is present.", "BLOCK"),
    ("OCCLUDED", "The bag is hidden behind the actor.", "UNKNOWN"),
    ("UNKNOWN", "The bag cannot be resolved in this frame.", "UNKNOWN"),
    ("ABSENT", "The bag is hidden behind the actor.", "UNKNOWN"),
])
def test_shot85_protected_bag_requires_proven_absence_to_block(visual, actual, evidence, decision):
    state = visual
    enable(state, {"enabled": True, "invariants": [
        requirement("prop_present", "bag", "", protected=True, source="approved:shot-85"),
    ]})

    def bag(reference, questions):
        observed = answer(reference, questions)
        for fact in observed["facts"]:
            fact["state"] = actual
            fact["evidence"] = evidence
        return observed

    state.observer.observe.side_effect = bag
    task = run(state)
    result = report(state, task, decision)
    assert state.observer.observe.await_count == 6
    assert len(result["findings"]) == 6
    assert all(item["raw_decision"] == decision and item["capability"] == "protected_prop_presence"
               and item["expected"]["expected"] == "PRESENT" and item["expected"]["protected"] is True
               for item in result["findings"])
    assert all(fact["state"] == actual and fact["evidence"] == evidence
               for item in result["findings"] for fact in item["observed"])
    if decision == "BLOCK":
        assert {item["reason"] for item in result["findings"]} == {"PROTECTED_PROP_MISSING"}
        assert all(item["may_block"] is True for item in result["findings"])
        no_generation(state, task)
    else:
        assert task.status == "completed", task.error_message
        assert {item["reason"] for item in result["findings"]} == {"INSUFFICIENT_EVIDENCE"}
        assert set(result["uploads"]) == {"1", "2"}
        assert state.client.queue_prompt.await_count == 2
    unchanged_shot(state)


@pytest.mark.parametrize("execution,expected", [
    ({"mode": "SINGLE_FRAME"}, [(1, ["start.png"], [None])]),
    ({"mode": "FIRST_LAST_FRAME"}, [(1, ["start.png", "kf3.png"], [None, 3])]),
    ({"windows": 1}, [(1, ["start.png", "kf2.png", "kf3.png"], [1, 2, 3])]),
    ({"windows": 2}, [(1, ["start.png", "kf2.png", "kf3.png"], [1, 2, 3]),
                      (2, ["kf4.png", "kf5.png", "kf6.png"], [4, 5, 6])]),
    ({"windows": 3, "only": 2, "auto_merge": True}, [(2, ["kf4.png", "kf5.png", "kf6.png"], [4, 5, 6])]),
], indirect=["execution"])
def test_legal_contexts_with_fine_relations_remain_unknown_with_actual_clip_addresses_and_unchanged_h3(visual, expected):
    state = visual
    enable(state, {"enabled": True, "invariants": [
        requirement(), requirement("contact_relation", "fox", "shallow_water", source="approved:shot-116"),
        requirement("environment_relation", "shallow_water", "connected_to:river_main", source="approved:shot-116"),
        requirement("prop_present", "bag", "", protected=True, source="approved:shot-85"),
    ]})
    selected_names = {name for _, names, _ in expected for name in names}
    for path in state.original_images:
        if Path(path).name not in selected_names:
            Path(path).write_bytes(b"Unselected files must not be decoded or uploaded")
    task = run(state)
    assert task.status == "completed", task.error_message
    result = report(state, task, "UNKNOWN")
    assert result["capability_policy"] == state.validator.CAPABILITY_POLICY_VERSION == "coarse_v1"
    assert len(result["findings"]) == 4 * len(result["references"])
    for item in result["findings"]:
        fine = item["expected"]["predicate"] in {"contact_relation", "environment_relation"}
        assert item["raw_decision"] == "PASS" and item["reason"] == "STATE_MATCH"
        assert item["decision"] == ("UNKNOWN" if fine else "PASS")
        assert item["may_confirm"] is (not fine) and item["may_block"] is (not fine)
        assert item["observed"][0]["state"] == "PRESENT"
    addresses = [(clip, index, f"/api/files/{name}", frames[index], "START" if index == 0 else "END" if index == len(names) - 1 else "KF")
                 for clip, names, frames in expected for index, name in enumerate(names)]
    assert [(item["clip_index"], item["reference_index"], item["source_url"], item["keyframe_index"], item["role"])
            for item in result["references"]] == addresses
    assert [(call.args[0].clip_index, call.args[0].reference_index) for call in state.observer.observe.await_args_list] == [
        (clip, index) for clip, index, *_ in addresses
    ]
    assert state.observer.observe.await_count == len(addresses) == len(state.image_uploads)
    assert set(result["uploads"]) == {str(clip) for clip, _, _ in expected}
    data = json.loads(task.metadata_json)
    for graph, (clip, names, _) in zip(state.queued, expected):
        bindings = result["uploads"][str(clip)]
        assert [Path(item["source_path"]).name for item in bindings] == names
        assert [item["node_id"] for item in bindings] == ["image", "kf1", "kf2"][:len(names)]
        gate = data["h3_prompt_gate"]["clips"][str(clip)][0]
        assert gate["raw_candidate"] == PROMPT
        assert gate["prequeue_validation"]["passed"] is True
        assert state.comfy.resolve_h3_consumed_prompt(graph, state.mapping) == gate["final_prompt"]
        assert gate["final_hash"] == state.ai.prompt_digest(gate["final_prompt"])
        assert gate["attempt_id"] == data["video_run"]["clips"][str(clip)]["attempt_id"]
        for binding in bindings:
            assert graph[binding["node_id"]]["inputs"]["image"] == binding["upload"]["filename"]
            assert binding["sha256"] == binding["upload"]["payload_sha256"]
    assert state.builder.await_count == state.client.queue_prompt.await_count == len(expected)
    state.llm.assert_not_awaited()
    if state.run_request["only_window_index"] is not None:
        assert data["video_run"]["result"]["kind"] == "clip"
        assert data["video_run"]["auto_merge_note"]
        state.storage.merge_videos.assert_not_awaited()
    unchanged_shot(state)


def test_noncritical_conflict_warns_and_continues(visual):
    state = visual
    enable(state, {"enabled": True, "invariants": [requirement(critical=False)]})

    def rock(reference, questions):
        observed = answer(reference, questions)
        observed["facts"][0]["value"] = "rock"
        return observed

    state.observer.observe.side_effect = rock
    task = run(state)
    assert task.status == "completed", task.error_message
    result = report(state, task, "WARN")
    assert {item["decision"] for item in result["findings"]} == {"WARN"}
    assert state.client.queue_prompt.await_count == 2
    unchanged_shot(state)


@pytest.mark.parametrize("execution", [{"audio": True}], indirect=True)
@pytest.mark.parametrize("constrained", [False, True])
def test_empty_cast_props_and_none_narration_do_not_invent_visual_facts(visual, constrained):
    state = visual
    source = state.foundation.load_execution_shot(state.task)
    source.characters = source.props = "[]"
    source.description = "Off-screen narration over an empty riverside. visible_speaker=NONE."
    plan = json.loads(source.video_director_plan)
    for clip in plan["window_plans"]:
        clip["prompt_text"] = (
            "subject_definitions:\nNo visible characters.\n"
            "summary:\nAn empty riverside under a clear sky.\n"
            "detailed_description:\nThe camera moves slowly over the shallow water.\n"
            "overall_soundscape:\nQuiet water ripples against the bank.\n"
            "initial_state_anchor:\nThe shallow water connects to the main river."
        )
    source.video_director_plan = json.dumps(plan)
    constraints = [requirement("environment_relation", "shallow_water", "connected_to:river_main")] if constrained else []
    enable(state, {"enabled": True, "invariants": constraints}, source=source)
    task = run(state)
    assert task.status == "completed", task.error_message
    result = report(state, task, "UNKNOWN")
    assert result["source"]["declared_characters"] == result["source"]["declared_props"] == []
    assert all(item["decision"] == "UNKNOWN" and item["may_confirm"] is False and item["may_block"] is False
               for item in result["findings"])
    assert state.observer.observe.await_count == (6 if constrained else 0)
    for call in state.observer.observe.await_args_list:
        assert [question.model_dump() for question in call.args[1]] == [
            {"predicate": "environment_relation", "subject": "shallow_water", "value": "connected_to:river_main"},
        ]
    if constrained:
        assert len(result["findings"]) == 6
        assert all(item["raw_decision"] == "PASS" and item["reason"] == "STATE_MATCH"
                   and item["capability"] == "advisory_only" and item["observed"][0]["state"] == "PRESENT"
                   for item in result["findings"])
    else:
        assert [item["reason"] for item in result["findings"]] == ["NOT_EVALUATED"]
        assert result["observations"] == []
    for call in state.builder.await_args_list:
        assert {item["visible_speaker"] for item in call.kwargs["speaker_timeline"]} == {"NONE"}
        assert call.kwargs["clip_dialogues"] == []
    assert state.client.upload_audio.await_count == 4
    assert all(not call.kwargs for call in state.client.upload_audio.await_args_list)
    assert state.client.queue_prompt.await_count == 2
    unchanged_shot(state)


def test_unconfigured_observer_is_unknown_nonblocking_with_no_vision_calls(visual, monkeypatch):
    state = visual
    enable(state)
    monkeypatch.setattr(state.validator, "get_visual_state_observer", lambda: None)
    task = run(state)
    assert task.status == "completed", task.error_message
    result = report(state, task, "UNKNOWN")
    assert {item["reason"] for item in result["findings"]} == {"OBSERVER_NOT_CONFIGURED"}
    assert result["observations"] == []
    state.observer.observe.assert_not_awaited()
    assert state.client.upload_image.await_count == 6
    assert state.client.queue_prompt.await_count == 2
    unchanged_shot(state)


@pytest.mark.parametrize("execution", [{"purpose": "production", "admitted": True}], indirect=True)
@pytest.mark.parametrize("explicit_false", [False, True])
def test_production_default_off_keeps_legacy_path_only_uploads(visual, explicit_false):
    state = visual
    original_upload = state.client.upload_image.side_effect
    if explicit_false:
        enable(state, {"enabled": False, "invariants": [requirement()]})
    task = run(state)
    assert task.status == "completed", task.error_message
    data = json.loads(task.metadata_json)
    assert "visual_state_validation" not in data
    assert not any(item["kind"] == "visual-state-validation" for item in data["video_observations"])
    assert not list(Path(data["video_run"]["directory"]).glob("visual-reference-*"))
    state.observer.observe.assert_not_awaited()
    assert state.client.upload_image.side_effect is original_upload
    assert state.client.upload_image.await_count == 6
    assert all(not call.kwargs for call in state.client.upload_image.await_args_list)
    assert (state.directory / "start.png").read_bytes() == b"start.png"
    assert data["oldsource"] == state.oldsource
    assert data["video_run"]["result"]["attachment"] == "attached"


@pytest.mark.parametrize("execution", [{"purpose": "production", "admitted": True}], indirect=True)
def test_production_block_settles_status_without_adopting_any_asset(visual):
    state = visual
    enable(state)

    def rock(reference, questions):
        observed = answer(reference, questions)
        observed["facts"][0]["value"] = "rock"
        return observed

    state.observer.observe.side_effect = rock
    task = run(state)
    report(state, task, "BLOCK")
    no_generation(state, task)
    state.db.refresh(state.shot)
    assert state.shot.video_status == "failed"
    assert len(state.shot_updates) == 1
    assert {key: getattr(state.shot, key) for key in state.before_shot if key not in {"video_status", "updated_at"}} == {
        key: value for key, value in state.before_shot.items() if key not in {"video_status", "updated_at"}
    }


@pytest.mark.parametrize("execution", [{"windows": 3, "only": 2}], indirect=True)
@pytest.mark.parametrize("clip_index,reference_index", [(1, 0), (2, 6)])
def test_unselected_or_keyframe_number_anchor_is_operational_reject_not_block(visual, clip_index, reference_index):
    state = visual
    enable(state, {"enabled": True, "anchors": [
        {"clip_index": clip_index, "reference_index": reference_index, "requirements": [requirement()]},
    ]})
    task = run(state)
    result = report(state, task, "UNKNOWN")
    assert [item["reason"] for item in result["findings"]] == ["INVALID_CONTRACT"]
    assert result["findings"][0]["decision"] == "UNKNOWN"
    assert "INVALID_VISUAL_STATE_CONTRACT" in task.error_message
    assert "BLOCK" not in task.error_message
    assert result["uploads"] == {}
    state.observer.observe.assert_not_awaited()
    no_generation(state, task)
    unchanged_shot(state)


@pytest.mark.parametrize("fault", ["not-image", "bad-checksum", "truncated-jpeg"])
def test_corrupt_last_selected_png_is_rejected_before_observer_or_c1(visual, fault):
    state = visual
    enable(state)
    path = state.directory / "kf6.png"
    payload = b"not an image"
    if fault == "bad-checksum":
        corrupt = bytearray(state.original_images[str(path)])
        corrupt[corrupt.index(b"IDAT") + 4] ^= 1
        payload = bytes(corrupt)
        with Image.open(BytesIO(payload)) as image:
            assert image.format == "PNG"  # Identification alone cannot catch the corrupted image data.
    elif fault == "truncated-jpeg":
        stream = BytesIO()
        Image.new("RGB", (8, 8), "blue").save(stream, "JPEG")
        payload = stream.getvalue()[:-2]
        with Image.open(BytesIO(payload)) as image:
            image.verify()  # JPEG structure can pass while its pixel stream is truncated.
    path.write_bytes(payload)
    task = run(state)
    no_generation(state, task)
    state.observer.observe.assert_not_awaited()
    result = json.loads(task.metadata_json)["visual_state_validation"]
    assert (result["status"], result["decision"]) == ("operational_error", "UNKNOWN")
    finding = result["findings"][0]
    assert finding["reason"] == "VISUAL_REFERENCE_PREPARATION_FAILED"
    assert (finding["clip_index"], finding["reference_index"]) == (2, 2)
    assert finding["source_url"] == "/api/files/kf6.png"
    assert finding["image_sha256"] == sha256(payload).hexdigest()
    assert finding["conflicting_fields"] == []
    evidence = result["evidence"]
    assert sha256(Path(evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]
    assert json.loads(Path(evidence["path"]).read_text()) == {key: value for key, value in result.items() if key != "evidence"}
    assert not result.get("uploads")
    unchanged_shot(state)


@pytest.mark.parametrize("stage", ["observer", "upload"])
def test_original_path_overwrite_cannot_change_observed_or_uploaded_payloads(visual, stage):
    state = visual
    enable(state)
    overwritten = []

    def overwrite():
        for path in state.original_images:
            Image.new("RGB", (7, 6), "magenta").save(path, "PNG")
        overwritten.append(True)

    if stage == "observer":
        def observe(reference, questions):
            if not overwritten:
                overwrite()
            return answer(reference, questions)
        state.observer.observe.side_effect = observe
    else:
        state.upload_hook = overwrite
    task = run(state)
    assert task.status == "completed", task.error_message
    result = report(state, task, "PASS")
    assert overwritten == [True]
    assert len(state.image_uploads) == state.observer.observe.await_count == 6
    for observed, uploaded in zip(state.observer.observe.await_args_list, state.image_uploads):
        reference = observed.args[0]
        original = state.original_images[uploaded["path"]]
        assert reference.payload == uploaded["payload"] == original
        assert Path(uploaded["path"]).read_bytes() != original
        assert uploaded["receipt"]["payload_sha256"] == reference.sha256
        binding = result["uploads"][str(reference.clip_index)][reference.reference_index]
        assert binding["sha256"] == reference.sha256
        assert binding["upload"] == uploaded["receipt"]
    unchanged_shot(state)


def test_two_clips_have_prequeue_upload_evidence_and_distinct_same_run_receipts(visual):
    state = visual
    enable(state)
    before_queue = []

    def inspect(stage):
        if stage == "queue":
            with Session(state.engine) as observer:
                saved = json.loads(observer.get(state.models.Task, "task").metadata_json)
            before_queue.append(saved)

    state.stage_hook = inspect
    task = run(state)
    assert task.status == "completed", task.error_message
    result = report(state, task, "PASS")
    assert len(before_queue) == 2
    assert set(before_queue[0]["visual_state_validation"]["uploads"]) == {"1"}
    assert set(before_queue[1]["visual_state_validation"]["uploads"]) == {"1", "2"}
    assert before_queue[0]["video_run"]["clips"]["1"]["receipt"] is None
    assert before_queue[1]["video_run"]["clips"]["1"]["receipt"]["prompt_id"] == "queued-1"
    assert before_queue[1]["video_run"]["clips"]["2"]["receipt"] is None
    assert before_queue[0]["visual_state_validation"]["uploads"]["1"] == result["uploads"]["1"]
    for index, saved in enumerate(before_queue, 1):
        bindings = saved["visual_state_validation"]["uploads"][str(index)]
        graph = saved["video_run"]["clips"][str(index)]["submission"]["graph"]
        assert graph == state.queued[index - 1]
        for binding in bindings:
            assert graph[binding["node_id"]]["inputs"][binding["field"]] == binding["upload"]["filename"]
    data = json.loads(task.metadata_json)
    clips = data["video_run"]["clips"]
    assert state.db.query(state.models.Task).count() == 1
    assert {slot["receipt"]["prompt_id"] for slot in clips.values()} == {"queued-1", "queued-2"}
    assert {slot["receipt"]["run_id"] for slot in clips.values()} == {data["video_run"]["run_id"]}
    assert len({slot["receipt"]["attempt_id"] for slot in clips.values()}) == 2
    assert len({item["upload_name"] for item in state.image_uploads}) == 6
    assert {item["sha256"] for item in result["uploads"]["1"]}.isdisjoint(
        {item["sha256"] for item in result["uploads"]["2"]})
    assert [Path(item["source_path"]).name for item in result["uploads"]["2"]] == ["kf4.png", "kf5.png", "kf6.png"]
    unchanged_shot(state)


@pytest.mark.parametrize("fault", ["missing-primary", "missing-extra", "duplicate-primary", "duplicate-extras", "not-load-image"])
def test_bad_image_mapping_rejects_whole_binding_before_uploads(visual, fault):
    state = visual
    mapping, graph = deepcopy(state.mapping), deepcopy(state.graph)
    if fault == "missing-primary":
        mapping.pop("reference_image_node_id")
    elif fault == "missing-extra":
        mapping.pop("keyframe_node_2")
    elif fault == "duplicate-primary":
        mapping["keyframe_node_2"] = "image"
    elif fault == "duplicate-extras":
        mapping["keyframe_node_2"] = "kf1"
    else:
        graph["kf2"]["class_type"] = "LoadAudio"
    state.workflow.node_mapping = json.dumps(mapping)
    state.workflow.workflow_json = json.dumps(graph)
    state.db.commit()
    enable(state)
    task = run(state)
    result = report(state, task, "PASS")
    assert result["uploads"] == {}
    assert "VALIDATED_REFERENCE_MAPPING_MISSING_OR_DUPLICATED" in task.error_message
    no_generation(state, task, prompt_started=True)
    unchanged_shot(state)


@pytest.mark.parametrize("field,value", [
    ("payload_sha256", "0" * 64), ("payload_size", 1), ("payload_size", True),
    ("type", "output"), ("filename", ""), ("success", False),
])
def test_bad_upload_receipt_does_not_record_partial_bindings_or_queue(visual, field, value):
    state = visual
    enable(state)
    upload = state.client.upload_image.side_effect

    async def corrupt(path, *, payload=None, upload_name=None):
        receipt = await upload(path, payload=payload, upload_name=upload_name)
        if len(state.image_uploads) == 3:
            receipt[field] = value
        return receipt

    state.client.upload_image.side_effect = corrupt
    task = run(state)
    result = report(state, task, "PASS")
    assert result["uploads"] == {}
    assert "VALIDATED_REFERENCE_UPLOAD_FAILED" in task.error_message
    no_generation(state, task, prompt_started=True, uploads=3)
    unchanged_shot(state)


@pytest.mark.parametrize("failure,reason", [("error", "OBSERVER_ERROR"), ("timeout", "OBSERVER_TIMEOUT"), ("hash", "OBSERVATION_HASH_MISMATCH"),
                                           ("none", "INVALID_OBSERVATION")])
def test_failed_vision_result_is_unknown_without_retry_and_video_continues(visual, failure, reason):
    state = visual
    enable(state)

    def unavailable(reference, questions):
        if failure == "error":
            raise RuntimeError("Vision unavailable")
        if failure == "timeout":
            raise TimeoutError("Vision timed out")
        if failure == "none":
            return None
        return {**answer(reference, questions), "image_sha256": "0" * 64}

    state.observer.observe.side_effect = unavailable
    task = run(state)
    assert task.status == "completed", task.error_message
    result = report(state, task, "UNKNOWN")
    assert {item["reason"] for item in result["findings"]} == {reason}
    assert result["observations"] == []
    assert state.observer.observe.await_count == 6
    assert len({call.args[0].sha256 for call in state.observer.observe.await_args_list}) == 6
    assert state.client.queue_prompt.await_count == state.builder.await_count == 2
    state.llm.assert_not_awaited()
    unchanged_shot(state)


@pytest.mark.parametrize("execution", [{"mode": "SINGLE_FRAME"}], indirect=True)
@pytest.mark.parametrize("race", ["cancel", "lost-claim", "frozen-request-changed"])
def test_late_observer_only_archives_after_cancel_claim_loss_or_request_tamper(visual, race):
    state = visual
    enable(state)
    saved = []
    stamp = datetime(2025, 1, 1)

    def late(reference, questions):
        if race == "cancel":
            change_task(state, status="cancelled", completed_at=stamp, result_url="/original.mp4", error_message="User cancelled")
        elif race == "lost-claim":
            change_task(state, claim_token="replacement", attempt=8, current_step="New worker owns task")
        else:
            with Session(state.engine) as editor:
                task = editor.get(state.models.Task, "task")
                data = json.loads(task.metadata_json)
                data["execution"]["request"]["visual_state_validation"]["enabled"] = False
                task.metadata_json = json.dumps(data)
                editor.commit()
        with Session(state.engine) as observer:
            saved.append(json.loads(observer.get(state.models.Task, "task").metadata_json))
        return answer(reference, questions)

    state.observer.observe.side_effect = late
    task = run(state)
    data = json.loads(task.metadata_json)
    assert {key: value for key, value in data.items() if key != "video_observations"} == saved[0]
    if race == "cancel":
        assert (task.status, task.completed_at, task.result_url, task.error_message) == (
            "cancelled", stamp, "/original.mp4", "User cancelled")
    else:
        assert task.status == "running" and task.result_url is None and task.completed_at is None
        if race == "lost-claim":
            assert (task.claim_token, task.attempt, task.current_step) == ("replacement", 8, "New worker owns task")
    events = data["video_observations"]
    assert {event["kind"] for event in events} == {"visual-state-validation", "late-failure"}
    for event in events:
        assert event["attachment"] == "detached"
        path = Path(event["evidence"]["path"])
        assert sha256(path.read_bytes()).hexdigest() == event["evidence"]["sha256"]
        if event["kind"] == "visual-state-validation":
            assert json.loads(path.read_text())["decision"] == "PASS"
    assert data["visual_state_validation"]["status"] == "preparing"
    assert data["oldsource"] == state.oldsource
    state.observer.observe.assert_awaited_once()
    state.builder.assert_not_awaited()
    state.llm.assert_not_awaited()
    state.client.upload_image.assert_not_awaited()
    state.client.upload_audio.assert_not_awaited()
    state.client.queue_prompt.assert_not_awaited()
    state.storage.download_video.assert_not_awaited()
    state.storage.merge_videos.assert_not_awaited()
    unchanged_shot(state)


@pytest.mark.parametrize("execution", [{"windows": 3, "only": 2}], indirect=True)
def test_caller_request_mutation_and_bogus_enqueue_arguments_cannot_change_frozen_selection(visual):
    state = visual
    contract = enable(state)
    contract["enabled"] = False
    contract["invariants"][0]["value"] = "rock"
    state.run_request.update(selected_mode="SINGLE_FRAME", only_window_index=1, workflow_id="wrong-workflow")
    task = run(state)  # The inherited runner also passes deliberately bogus queue arguments.
    assert task.status == "completed", task.error_message
    result = report(state, task, "PASS")
    assert {(item["clip_index"], item["reference_index"]) for item in result["references"]} == {(2, 0), (2, 1), (2, 2)}
    assert {item["expected"]["value"] for item in result["findings"]} == {"tree"}
    assert [Path(item["path"]).name for item in state.image_uploads] == ["kf4.png", "kf5.png", "kf6.png"]
    assert state.client.queue_prompt.await_count == state.builder.await_count == 1
    unchanged_shot(state)
