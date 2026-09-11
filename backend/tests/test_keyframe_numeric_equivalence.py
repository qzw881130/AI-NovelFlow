"""Offline numeric-identity regressions; run Python 3.11 with --noconftest.

The I116-A contract is reconstructed from its captured 2026-09-08 values, with
original v1 hashes pinned below. Repeated archived strings are stored once in
the adjacent JSON fixture. No temporary audit path, application startup, live
database, network, media download or actual generation is used by this replay.
"""

import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import socket
import sqlite3
import sys
from types import ModuleType, SimpleNamespace

import pytest

import test_keyframe_reference_worker as worker_tests
from test_keyframe_reference_worker import worker
import test_keyframe_reference_recovery as recovery_tests
from test_keyframe_reference_recovery import recovery


BACKEND = Path(__file__).resolve().parents[1]
TASK_ID = "4d44a90f-a945-4a60-8955-369f56d9a539"
CID = "d0e3ca88-d288-4b1d-baea-93e0dd69ab05"
GRAPH_HASH = "aa1135eaa9ec6a9735f246be1ba0bd9d6a2044e767c60f5617ba7c57727b1da5"
HISTORY_HASH = "7d04558f740e3a5f60fe563f396dd338a5eb0bc70320d6c3c141d692c2173492"
STABLE_HASH = "100a9f0f111995cf1a0f227a5cee76a26bbb8c8b123b6470e24f0e2930a2e7ca"
HISTORY_STABLE_HASH = "e6bfba96254706054e08fd9712925ce110642c380429e8fa82b7e410cf9d508a"
CACHE_HASH = "a32a16b219378d32abf9cbe48096b806bab33a1ba0a2240a8905e67aadcca7f3"
STORAGE_HASH = "62f2656a2500f6569120fd12b2ae0bf9badafb80753d4c1cc9af83de9dfad2f3"
NUMBER_FIELDS = (("107", "megapixels"), ("108", "cfg"))


def exact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def legacy_digest(value):
    return hashlib.sha256(exact(value).encode()).hexdigest()


def legacy_stable(graph, mapping):
    stable = deepcopy(graph)
    for node in stable.values():
        node.pop("_meta", None)
        field = {"RandomNoise": "noise_seed", "KSampler": "seed", "SaveImage": "filename_prefix"}.get(node["class_type"])
        if field:
            node["inputs"].pop(field)
    node = stable[mapping["prompt_node_id"]]["inputs"]
    node.pop("text" if "text" in node else "prompt")
    if mapping.get("reference_image_node_id") in stable:
        stable[mapping["reference_image_node_id"]]["inputs"].pop("image")
    encoded = json.dumps({"graph": stable, "mapping": mapping}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def legacy_cache(contract):
    reference = contract["resolved"]
    return legacy_digest({"version": 1, "context": contract["context"],
                          "reference": {key: reference[key] for key in ("source_kind", "url", "sha256", "source_keyframe_index")} if reference else None,
                          "workflow": contract["workflow"]["contract_hash"], "template": contract["template"]["hash"], "llm_config": contract["llm_config"]})


@pytest.fixture
def numeric(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Numeric proof tests must not access network or databases")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", forbidden)
    for name in ("app", "app.services"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)

    def load(name):
        qualified = "app.services." + name
        spec = importlib.util.spec_from_file_location(qualified, BACKEND / "app/services" / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, qualified, module)
        spec.loader.exec_module(module)
        return module

    return SimpleNamespace(gate=load("keyframe_reference_contract"), graphs=load("keyframe_reference_graph"))


def test_shared_numeric_identity_accepts_three_references_without_weakening_keyframe_profile(numeric):
    graph = json.loads((BACKEND / "workflows/shot_flux2_klein_three_ref_edit.json").read_text())
    mapping = {"prompt_node_id": "117", "save_image_node_id": "9", "reference_image_node_id": "76"}
    before = exact(graph)
    original = numeric.graphs.numeric_graph_digest(graph)
    assert exact(graph) == before
    assert sum(node["class_type"] == "LoadImage" for node in graph.values()) == 3
    for node, field in (("107", "megapixels"), ("108", "cfg"), ("128", "megapixels"), ("133", "megapixels")):
        graph[node]["inputs"][field] = 1.0
    assert legacy_digest(graph) != original
    before = exact(graph)
    assert numeric.graphs.numeric_graph_digest(graph) == original
    with pytest.raises(numeric.graphs.KeyframeGraphError):
        numeric.graphs.validate_keyframe_graph(graph, mapping, reference_count=1)
    with pytest.raises(numeric.graphs.KeyframeGraphError):
        numeric.graphs.semantic_stable_graph_fingerprint(graph, mapping)
    assert exact(graph) == before


@pytest.mark.parametrize("location", ["unknown-class", "unknown-port", "metadata", "integer-widget", "link-slot"])
@pytest.mark.parametrize("value", [1.0, True, "1", None])
def test_shared_numeric_identity_preserves_unreviewed_and_nonnumber_values(numeric, location, value):
    graph = json.loads((BACKEND / "workflows/keyframe_flux2_klein.json").read_text())
    if location == "unknown-class":
        graph["opaque"] = {"class_type": "UnknownCFGGuider", "inputs": {"cfg": 1}}
        container, field = graph["opaque"]["inputs"], "cfg"
    elif location == "unknown-port":
        container, field = graph["108"]["inputs"], "unknown_number"
    elif location == "metadata":
        container, field = graph["9"]["_meta"], "number"
    elif location == "integer-widget":
        container, field = graph["102"]["inputs"], "noise_seed"
    else:
        container, field = graph["101"]["inputs"]["samples"], 1
    container[field] = 1
    original = numeric.graphs.numeric_graph_digest(graph)
    container[field] = value
    before = exact(graph)
    assert numeric.graphs.numeric_graph_digest(graph) != original
    assert exact(graph) == before
    if location != "metadata":
        with pytest.raises(numeric.graphs.KeyframeGraphError):
            numeric.graphs.semantic_graph_digest(graph)


@pytest.mark.parametrize("node,field", [("107", "megapixels"), ("108", "cfg"), ("128", "megapixels"), ("133", "megapixels")])
@pytest.mark.parametrize("value", [True, False, "1", None, float("nan"), float("inf"), -float("inf"), ["102", 0]])
def test_shared_numeric_identity_rejects_known_number_impostors(numeric, node, field, value):
    graph = json.loads((BACKEND / "workflows/shot_flux2_klein_three_ref_edit.json").read_text())
    graph[node]["inputs"][field] = value
    before = json.dumps(graph, sort_keys=True)
    with pytest.raises(numeric.graphs.KeyframeGraphError):
        numeric.graphs.numeric_graph_digest(graph)
    assert json.dumps(graph, sort_keys=True) == before


@pytest.mark.parametrize("graph", [None, [], {}, {1: {"class_type": "Unknown", "inputs": {}}}, {"1": None},
                                   {"1": {"class_type": True, "inputs": {}}}, {"1": {"class_type": "Unknown", "inputs": []}},
                                   {str(index): {"class_type": "Unknown", "inputs": {}} for index in range(257)}])
def test_shared_numeric_identity_is_bounded_and_requires_an_api_graph(numeric, graph):
    with pytest.raises(numeric.graphs.KeyframeGraphError):
        numeric.graphs.numeric_graph_digest(graph)


@pytest.fixture
def archived(numeric):
    strings = json.loads(Path(__file__).with_name("keyframe_numeric_i116_strings.json").read_text())
    graph = json.loads((BACKEND / "workflows/keyframe_flux2_klein.json").read_text())
    prompt = strings["prompt"]
    filename = "kf-" + TASK_ID + "-22d89dab6f4c4e38bbf89b56a8336b00-ref1.png"
    for node, field, value in (("110", "text", prompt), ("76", "image", filename),
                               ("102", "noise_seed", 2640632086), ("123", "value", 1920), ("125", "value", 1088)):
        graph[node]["inputs"][field] = value
    mapping = {"prompt_node_id": "110", "save_image_node_id": "9", "reference_image_node_id": "76"}
    intent = {"mode": "auto_select", "url": None, "selection": "dynamic_auto"}
    current = {"index": 3, "role": "INTERMEDIATE", "time_seconds": 14.117, "description": strings["target_description"]}
    previous = {"index": 2, "role": "INTERMEDIATE", "time_seconds": 7.0, "description": strings["previous_description"]}
    shot = {"description": strings["shot_description"], "video_description": strings["video_description"],
            "scene": "\u6cb3\u8fb9", "duration": 8, "continuity_mode": "NORMAL", "characters": ["\u5c0f\u9a6c"], "props": [], "dialogues": []}
    label = "\u4e0a\u4e00\u5173\u952e\u5e27 KF2"
    source_url = "/api/files/story_84e2c1f4/images/keyframe_0_20260906_061506.png"
    source_hash = "49f92524ac88712372cc74359a665e560d22ac3b0cdb93a036321dfb3615c0f2"
    provenance = {"status": "unverified_legacy", "state_validated": False,
                  "producer_task_ids": ["92292828-28c5-4fb1-9dc2-e45b16b39f29"], "evidence": [],
                  "source": "legacy_llm_log", "reason": "producer_state_missing"}
    target = {"shot_id": "db113888-359e-4a8c-be1b-f4ee64a85750", "chapter_id": "34346daf-c2b9-40d8-9cca-0dd480cbadb6",
              "frame_index": 1, "legacy_frame_index": 1, "plan_keyframe_index": 3,
              "legacy_state": {**current, "role": None}, "current_state": current, "previous_state_text": previous,
              "reference_intent": intent, "shot_state": shot,
              "images": {key: "/api/files/story_84e2c1f4/images/keyframe_1_20260906_061600.png" for key in ("legacy", "plan")},
              "owners": {key: "b5fbf8e4-0963-46de-88a7-ba659e8a21c7" for key in ("legacy", "plan")},
              "draft": {key: {"present": True, "value": strings["old_prompt"]} for key in ("legacy", "plan")}}
    contract = {
        "version": 1, "attempt_id": "22d89dab6f4c4e38bbf89b56a8336b00", "phase": "failed",
        "planned": {"intent": intent, "novel_id": "84e2c1f4-c52a-4d3b-ab83-5e3bf1d54880", "parent_task_id": None,
                    "requested_workflow_id": "8bd4aeca-4609-4d10-bd40-40717e3b2f0a", "skip_llm_when_prompt_exists": False, "batch_order": None},
        "target": target, "draft": {key: {"present": True, "value": prompt} for key in ("legacy", "plan")},
        "binding_resolved": True,
        "resolved": {"source_kind": "PREVIOUS_KEYFRAME", "label": label, "url": source_url, "source_keyframe_index": 2,
                     "producer_task_id": "92292828-28c5-4fb1-9dc2-e45b16b39f29", "sha256": source_hash, "size": 2655706, "state_proof": provenance},
        "binding": {"picture_index": 1, "node_id": "76", "field": "image", "output_slot": 0,
                    "uploaded_filename": filename, "payload_sha256": source_hash, "payload_size": 2655706},
        "prompt": {"llm_invoked": True, "cache_fingerprint": CACHE_HASH, "origin": "llm",
                   "input_hash": "44d6e8211a0819ab86f3080402033f56ecb038a51663de8f052080c8e9643311",
                   "raw_response": prompt, "text": prompt,
                   "text_hash": "bcff684e4a45b876109403bcd78503f57e13f866b7ae7bbcaea149a427954799",
                   "validation": {"passed": True, "source_kind": "PREVIOUS_KEYFRAME", "picture_indexes": []}},
        "submit": {"state": "submitted", "graph_hash": GRAPH_HASH, "prompt_id": CID},
        "storage_revision": 11, "storage_hash": STORAGE_HASH,
        "workflow": {"id": "8bd4aeca-4609-4d10-bd40-40717e3b2f0a", "name": "Flux2-Klein-9B \u5173\u952e\u5e27\u751f\u56fe",
                     "type": "keyframe_image", "selection": "explicit", "node_mapping": mapping,
                     "mapping_source_hash": "4d7526b9dbf58eb83143ebeb399431a45b90e597b947aa5152e59886e241a961",
                     "template_graph_hash": "e875bcafdb7807366d89cf513bdf9b45fffb1e14c3bea1073503eae732baed12",
                     "family": "flux2", "output_node_id": "9", "contract_hash": STABLE_HASH},
        "template": {"id": "dacf65db-8081-4a7a-ad5d-f08d81e18963", "name": "\u89c6\u9891\u5173\u952e\u5e27\u751f\u56fe\u63d0\u793a\u8bcd\u6784\u5efa",
                     "type": "keyframe_image_prompt", "text": strings["template"],
                     "hash": "7cbcb2cde285e62fc2c21c0c38bed163d96eda2e246e4d47fd2656253480068e"},
        "endpoint": "http://192.168.50.1:8288", "client_id": "8b422b25-ff4d-43d5-bc50-aa59d54ac548",
        "llm_config": {"provider": "deepseek", "model": "deepseek-v4-flash", "max_tokens": 393216, "temperature": 0.2},
        "context": {"shot": {"id": target["shot_id"], "index": 116, **shot}, "current_keyframe": {**current, "frame_index": 1},
                    "previous_keyframe_state_text": previous, "visual_style": "chibi style, cute cartoon style, kawaii, colorful", "aspect_ratio": "16:9"},
        "resolution_attempts": [{"source_kind": "PREVIOUS_KEYFRAME", "url": source_url, "state_proof": provenance, "accepted": True}],
        "manifest": [{"picture_index": 1, "type": "PREVIOUS_KEYFRAME", "role": "EDIT_BASE", "label": label, "source_keyframe_index": 2}],
        "frozen_binding_hash": "b321c82a42207df6801a643023601f6b35a651b43941b3aca1b4595d418fa3ad",
        "validation": {"passed": True, "graph": {
            "family": "flux2", "reference_count": 1, "reference_node_id": "76", "reference_filename": filename,
            "prompt_node_id": "110", "prompt_field": "text", "effective_prompt": prompt, "save_image_node_id": "9",
            "decode_node_id": "101", "sampler_node_id": "100", "positive_consumer_node_id": "110", "image_source_nodes": ["76"],
            "image_routes": [{"role": role, "kind": "reference", "source_node_id": "76", "consumer_node_id": node,
                              "consumer_field": "latent", "node_ids": ["76", "107", "115", node]}
                             for role, node in (("negative", "114"), ("positive", "116"))]}},
        "prepared_workflow": graph,
        "failure": {"stage": "submitted", "code": "HISTORY_SUBMISSION_MISMATCH", "message": "#09 HISTORY_SUBMISSION_MISMATCH"},
    }
    # Break construction-time aliases just as a real persisted JSON round trip does.
    contract = json.loads(exact(contract))
    history_graph = deepcopy(graph)
    for node, field in NUMBER_FIELDS:
        history_graph[node]["inputs"][field] = 1.0
    history = {"prompt": [0, CID, history_graph, {}, ["9"]], "status": {"completed": True, "status_str": "success"},
               "outputs": {"9": {"images": [{"filename": "Keyframe-Flux2-Klein_00224_.png", "subfolder": "", "type": "output"}]}}}
    task = SimpleNamespace(id=TASK_ID, type="keyframe_image", status="failed", result_url=None,
                           shot_id=target["shot_id"], chapter_id=target["chapter_id"], novel_id=contract["planned"]["novel_id"],
                           parent_task_id=None, comfyui_prompt_id=CID, prompt_text=prompt,
                           reference_images=exact([{"label": label, "url": source_url}]),
                           workflow_id=contract["workflow"]["id"], workflow_name=contract["workflow"]["name"],
                           workflow_json=exact(graph), metadata_json=exact({numeric.gate.CONTRACT_KEY: contract}))
    return SimpleNamespace(**vars(numeric), contract=contract, task=task, graph=graph, mapping=mapping, history=history)


def test_archived_i116_v1_hashes_and_numeric_history_without_reattachment(archived):
    case = archived
    before = exact((case.contract, vars(case.task), case.history))
    assert legacy_digest(case.graph) == case.gate.digest(case.graph) == GRAPH_HASH
    assert legacy_digest(case.history["prompt"][2]) == HISTORY_HASH
    assert case.graphs.stable_graph_fingerprint(case.graph, case.mapping) == STABLE_HASH
    assert case.graphs.stable_graph_fingerprint(case.history["prompt"][2], case.mapping) == HISTORY_STABLE_HASH
    assert case.gate.reference_cache_fingerprint(case.contract) == CACHE_HASH
    assert legacy_digest({key: value for key, value in case.contract.items() if key != "storage_hash"}) == STORAGE_HASH
    assert case.gate.validate_frozen_contract(case.contract, case.task, require_submitted=True) == case.contract["validation"]["graph"]
    url = case.gate.select_keyframe_output(case.history, case.contract, case.contract["endpoint"])
    assert url.endswith("/view?filename=Keyframe-Flux2-Klein_00224_.png&subfolder=&type=output")
    assert case.task.status == "failed" and case.task.result_url is None
    assert exact((case.contract, vars(case.task), case.history)) == before


def test_independently_sealed_legacy_float_contract_matches_int_history_and_cache(archived):
    case = archived
    converted = deepcopy(case.contract)
    converted["prepared_workflow"] = deepcopy(case.history["prompt"][2])
    converted["submit"]["graph_hash"] = legacy_digest(converted["prepared_workflow"])
    converted["workflow"]["contract_hash"] = legacy_stable(converted["prepared_workflow"], case.mapping)
    converted["prompt"]["cache_fingerprint"] = legacy_cache(converted)
    converted["storage_hash"] = legacy_digest({key: value for key, value in converted.items() if key != "storage_hash"})
    assert converted["submit"]["graph_hash"] == HISTORY_HASH
    assert converted["workflow"]["contract_hash"] == HISTORY_STABLE_HASH
    assert converted["prompt"]["cache_fingerprint"] != CACHE_HASH
    assert converted["storage_hash"] != STORAGE_HASH
    task = SimpleNamespace(**vars(case.task))
    task.workflow_json = exact(converted["prepared_workflow"])
    task.metadata_json = exact({case.gate.CONTRACT_KEY: converted})
    history = deepcopy(case.history)
    history["prompt"][2] = deepcopy(case.graph)
    before = exact((converted, vars(task), history, case.contract))
    case.gate.validate_frozen_contract(converted, task, require_submitted=True)
    assert case.gate.semantic_reference_cache_fingerprint(converted) == case.gate.semantic_reference_cache_fingerprint(case.contract) == CACHE_HASH
    case.gate.select_keyframe_output(history, converted, converted["endpoint"])
    assert exact((converted, vars(task), history, case.contract)) == before


@pytest.mark.parametrize("state", ["attempted", "unknown", "not_submitted"])
def test_preacknowledgement_proofs_still_require_original_v1_hash_and_cid(archived, state):
    case = archived
    case.contract["submit"] = {"state": state}
    if state != "not_submitted":
        case.contract["submit"]["graph_hash"] = GRAPH_HASH
    case.contract["storage_hash"] = legacy_digest({key: value for key, value in case.contract.items() if key != "storage_hash"})
    case.task.comfyui_prompt_id = case.task.workflow_json = None
    case.task.metadata_json = exact({case.gate.CONTRACT_KEY: case.contract})
    case.gate.validate_frozen_contract(case.contract, case.task)
    with pytest.raises(case.gate.KeyframeReferenceError, match="SUBMISSION_NOT_CONFIRMED"):
        case.gate.select_keyframe_output(case.history, case.contract, case.contract["endpoint"])
    if state != "not_submitted":
        case.contract["submit"]["graph_hash"] = HISTORY_HASH
        with pytest.raises(case.gate.KeyframeReferenceError, match="HISTORY_SUBMISSION_MISMATCH"):
            case.gate._assert_task_projections(case.task, case.contract)


@pytest.mark.parametrize("change", ["time-representation", "context", "llm", "template", "source-url", "source-kind", "source-index", "source-bytes"])
def test_semantic_cache_keeps_nonworkflow_components_exact(archived, change):
    case = archived
    current = deepcopy(case.contract)
    if change == "time-representation":
        current["context"]["previous_keyframe_state_text"]["time_seconds"] = 7
    elif change == "context":
        current["context"]["visual_style"] += " changed"
    elif change == "llm":
        current["llm_config"]["model"] = "different"
    elif change == "template":
        current["template"]["hash"] = legacy_digest("different template")
    else:
        field, value = {"source-url": ("url", "/different.png"), "source-kind": ("source_kind", "CUSTOM_REFERENCE"),
                        "source-index": ("source_keyframe_index", 3), "source-bytes": ("sha256", "0" * 64)}[change]
        current["resolved"][field] = value
    current["prompt"]["cache_fingerprint"] = legacy_cache(current)
    assert case.gate.semantic_reference_cache_fingerprint(current) != case.gate.semantic_reference_cache_fingerprint(case.contract)


@pytest.mark.parametrize("key", ["prepared_workflow", "cache_fingerprint", "contract_hash"])
def test_semantic_cache_cannot_substitute_for_missing_or_forged_v1_inputs(archived, key):
    case = archived
    if key == "prepared_workflow":
        case.contract.pop(key)
    elif key == "cache_fingerprint":
        case.contract["prompt"][key] = "0" * 64
    else:
        case.contract["workflow"][key] = "0" * 64
    with pytest.raises(case.gate.KeyframeReferenceError):
        case.gate.semantic_reference_cache_fingerprint(case.contract)


@pytest.mark.parametrize("fields", [(NUMBER_FIELDS[0],), (NUMBER_FIELDS[1],), NUMBER_FIELDS])
def test_each_numeric_reencoding_matches_task_history_and_full_proof(archived, fields):
    case = archived
    graph = deepcopy(case.graph)
    for node, field in fields:
        graph[node]["inputs"][field] = json.loads("1e0")
    case.history["prompt"][2] = graph
    case.task.workflow_json = exact(dict(reversed(list(graph.items()))))
    before = exact((graph, vars(case.task), case.contract))
    case.gate.assert_keyframe_graph_matches(graph, case.contract)
    case.gate.validate_frozen_contract(case.contract, case.task, require_submitted=True)
    case.gate.select_keyframe_output(case.history, case.contract, case.contract["endpoint"])
    assert case.graphs.semantic_stable_graph_fingerprint(graph, case.mapping) == STABLE_HASH
    assert exact((graph, vars(case.task), case.contract)) == before


@pytest.mark.parametrize("value", [0, 1, -1, 2**53 - 1, -(2**53 - 1)])
def test_only_safe_exact_integral_float_numbers_fold(archived, value):
    graph = deepcopy(archived.graph)
    graph["108"]["inputs"]["cfg"] = value
    before = exact(graph)
    full = archived.graphs.semantic_graph_digest(graph)
    stable = archived.graphs.semantic_stable_graph_fingerprint(graph, archived.mapping)
    assert exact(graph) == before
    graph["108"]["inputs"]["cfg"] = float(value)
    before = exact(graph)
    assert archived.graphs.semantic_graph_digest(graph) == full
    assert archived.graphs.semantic_stable_graph_fingerprint(graph, archived.mapping) == stable
    assert exact(graph) == before


@pytest.mark.parametrize("left,right", [
    (0, -0.0), (0.0, -0.0), (1, math.nextafter(1.0, math.inf)), (3, 3.0000000000000004),
    (0.1, math.nextafter(0.1, math.inf)), (0, 5e-324),
    (2**53, float(2**53)), (2**53 + 1, float(2**53 + 1)),
    (2**53, 2**53 + 1), (10**100, 10**100 + 1), (10**100, float(10**100)),
])
def test_signed_zero_distinct_floats_and_large_numbers_never_collapse(archived, left, right):
    graph = deepcopy(archived.graph)
    fingerprints = []
    for value in (left, right):
        graph["108"]["inputs"]["cfg"] = value
        fingerprints.append((archived.graphs.semantic_graph_digest(graph), archived.graphs.semantic_stable_graph_fingerprint(graph, archived.mapping)))
    assert fingerprints[0][0] != fingerprints[1][0]
    assert fingerprints[0][1] != fingerprints[1][1]


@pytest.mark.parametrize("node,field", NUMBER_FIELDS)
@pytest.mark.parametrize("value", ["1", True, False, None, float("nan"), float("inf"), -float("inf"), json.loads("1e999"), ["102", 0]])
def test_number_type_impostors_fail_before_canonicalization(archived, node, field, value):
    graph = deepcopy(archived.graph)
    graph[node]["inputs"][field] = value
    before = json.dumps(graph, sort_keys=True)
    for method, args in ((archived.graphs.semantic_graph_digest, (graph,)),
                         (archived.graphs.semantic_stable_graph_fingerprint, (graph, archived.mapping))):
        with pytest.raises(archived.graphs.KeyframeGraphError):
            method(*args)
    with pytest.raises(archived.gate.KeyframeReferenceError, match="TASK_PROJECTION_CHANGED"):
        archived.gate.assert_keyframe_graph_matches(graph, archived.contract, code="TASK_PROJECTION_CHANGED")
    archived.history["prompt"][2] = graph
    with pytest.raises(archived.gate.KeyframeReferenceError, match="HISTORY_SUBMISSION_MISMATCH"):
        archived.gate.select_keyframe_output(archived.history, archived.contract, archived.contract["endpoint"])
    assert json.dumps(graph, sort_keys=True) == before


@pytest.mark.parametrize("node,field", [("102", "noise_seed"), ("109", "steps"), ("106", "batch_size"), ("123", "value"), ("107", "resolution_steps")])
@pytest.mark.parametrize("value", [1.0, True, "1", None])
def test_integer_only_widgets_are_never_coerced(archived, node, field, value):
    graph = deepcopy(archived.graph)
    graph[node]["inputs"][field] = value
    with pytest.raises(archived.graphs.KeyframeGraphError, match="Expected"):
        archived.graphs.semantic_graph_digest(graph)
    with pytest.raises(archived.graphs.KeyframeGraphError):
        archived.graphs.semantic_stable_graph_fingerprint(graph, archived.mapping)


@pytest.mark.parametrize("link", [["100", 0.0], ["100", True], ["100", False], ["100", "0"], [100, 0], [0, "100"], ["100", 2], ["100", 0, 1]])
def test_connection_slots_and_array_order_remain_typed(archived, link):
    graph = deepcopy(archived.graph)
    graph["101"]["inputs"]["samples"] = link
    with pytest.raises(archived.graphs.KeyframeGraphError):
        archived.graphs.semantic_graph_digest(graph)
    with pytest.raises(archived.graphs.KeyframeGraphError):
        archived.graphs.semantic_stable_graph_fingerprint(graph, archived.mapping)


@pytest.mark.parametrize("change", ["prompt", "image", "seed", "prefix", "model", "cfg", "megapixels", "dimensions", "slot", "metadata", "array", "runtime-field"])
def test_full_history_identity_preserves_every_non_equivalent_change(archived, change):
    case = archived
    graph = case.history["prompt"][2]
    edits = {"prompt": ("110", "text", case.task.prompt_text + " "), "image": ("76", "image", "other.png"),
             "seed": ("102", "noise_seed", 2640632087), "prefix": ("9", "filename_prefix", "other"),
             "model": ("103", "unet_name", "other.safetensors"), "cfg": ("108", "cfg", 1.0000000000000002),
             "megapixels": ("107", "megapixels", 2), "dimensions": ("123", "value", 1088), "slot": ("101", "samples", ["100", 1])}
    if change in edits:
        node, field, value = edits[change]
        graph[node]["inputs"][field] = value
    elif change == "runtime-field":
        graph["76"]["is_changed"] = [case.contract["resolved"]["sha256"]]
    elif change == "metadata":
        graph["9"]["_meta"]["title"] += " changed"
    else:
        graph["9"]["_meta"]["order"] = [2, 1]
    before = exact((case.history, case.contract))
    with pytest.raises(case.gate.KeyframeReferenceError, match="HISTORY_SUBMISSION_MISMATCH"):
        case.gate.select_keyframe_output(case.history, case.contract, case.contract["endpoint"])
    if change in {"seed", "prefix", "prompt", "image", "metadata", "array"}:
        assert case.graphs.semantic_stable_graph_fingerprint(graph, case.mapping) == STABLE_HASH
    assert exact((case.history, case.contract)) == before


@pytest.mark.parametrize("value", [1.0, True, "1", None, [2, 1]])
def test_metadata_is_not_numeric_normalized_or_array_sorted(archived, value):
    graph = deepcopy(archived.graph)
    graph["9"]["_meta"]["value"] = [1, 2] if isinstance(value, list) else 1
    original = archived.graphs.semantic_graph_digest(graph)
    graph["9"]["_meta"]["value"] = value
    assert archived.graphs.semantic_graph_digest(graph) != original


@pytest.mark.parametrize("change", ["number", "context", "revision", "seal", "submit", "stable", "cache", "validation", "binding"])
def test_numeric_equivalence_never_repairs_corrupt_legacy_proof(archived, change):
    case = archived
    contract = case.contract
    if change == "number":
        contract["prepared_workflow"]["108"]["inputs"]["cfg"] = 1.0
    elif change == "context":
        contract["context"]["previous_keyframe_state_text"]["time_seconds"] = 7
    elif change == "revision":
        contract["storage_revision"] = True
    elif change == "seal":
        contract["storage_hash"] = "0" * 64
    else:
        section, field = {"submit": ("submit", "graph_hash"), "stable": ("workflow", "contract_hash"),
                          "cache": ("prompt", "cache_fingerprint"), "validation": ("validation", "graph"),
                          "binding": ("binding", "payload_sha256")}[change]
        contract[section][field] = {"passed": True} if change == "validation" else "0" * 64
        contract["storage_hash"] = legacy_digest({key: value for key, value in contract.items() if key != "storage_hash"})
    before = exact(contract)
    with pytest.raises(case.gate.KeyframeReferenceError):
        case.gate.select_keyframe_output(case.history, contract, contract["endpoint"])
    assert exact(contract) == before


def test_general_digest_stays_exact_for_json_and_bytes(numeric):
    assert len({numeric.gate.digest(value) for value in (1, 1.0, True, "1", None)}) == 5
    assert numeric.gate.digest(b"1") == hashlib.sha256(b"1").hexdigest()
    for value in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError):
            numeric.gate.digest(value)


def test_qwen_bool_widgets_and_nonintegral_shift_are_not_numeric_aliases(numeric):
    path = next((BACKEND / "user_workflows").glob("*Qwen-Edit-2511*keyframe_image.json"))
    graph = json.loads(path.read_text())
    mapping = {"prompt_node_id": "184", "save_image_node_id": "163", "reference_image_node_id": "170"}
    assert graph["64"]["inputs"]["shift"] == 3.0000000000000004
    original = numeric.graphs.semantic_stable_graph_fingerprint(graph, mapping)
    graph["64"]["inputs"]["shift"] = 3
    assert numeric.graphs.semantic_stable_graph_fingerprint(graph, mapping) != original
    for value in (1, 1.0, "true", None):
        graph["65"]["inputs"]["pre_cfg"] = value
        with pytest.raises(numeric.graphs.KeyframeGraphError):
            numeric.graphs.semantic_graph_digest(graph)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_full_graph_rejects_nonfinite_metadata_instead_of_ignoring_it(archived, value):
    graph = deepcopy(archived.graph)
    graph["9"]["_meta"]["invalid"] = value
    with pytest.raises(archived.graphs.KeyframeGraphError, match="finite JSON"):
        archived.graphs.semantic_graph_digest(graph)
    with pytest.raises(archived.graphs.KeyframeGraphError, match="finite JSON"):
        archived.graphs.semantic_stable_graph_fingerprint(graph, archived.mapping)


@pytest.mark.parametrize("change", ["prompt-id", "not-completed", "two-images", "preview", "traversal"])
def test_numeric_history_keeps_cid_status_and_output_guards(archived, change):
    case = archived
    if change == "prompt-id":
        case.history["prompt"][1] = "other"
    elif change == "not-completed":
        case.history["status"] = {"completed": 1}
    elif change == "two-images":
        case.history["outputs"]["9"]["images"] *= 2
    elif change == "preview":
        case.history["outputs"]["preview"] = case.history["outputs"].pop("9")
    else:
        case.history["outputs"]["9"]["images"][0]["filename"] = "../other.png"
    with pytest.raises(case.gate.KeyframeReferenceError):
        case.gate.select_keyframe_output(case.history, case.contract, case.contract["endpoint"])


@pytest.mark.parametrize("both", [False, True])
def test_real_worker_uses_numeric_history_without_requeue_or_graph_rewrite(worker, both):
    def history(value):
        for node, field in NUMBER_FIELDS if both else (NUMBER_FIELDS[1],):
            value["prompt"][2][node]["inputs"][field] = 1.0

    worker.history_hook = history
    worker_tests.create(worker)
    result = worker_tests.run(worker)
    worker_tests.assert_completed(worker, result, "PRIMARY_STORYBOARD")
    assert len(worker.queued) == len(worker.downloads) == 1
    assert exact(json.loads(result.task.workflow_json)) == exact(worker.queued[0]) == exact(result.contract["prepared_workflow"])
    for node, field in NUMBER_FIELDS:
        assert type(worker.queued[0][node]["inputs"][field]) is int


@pytest.mark.parametrize("node,field,value", [("108", "cfg", True), ("108", "cfg", 1.0000000000000002),
                                             ("101", "samples", ["100", 0.0]), ("102", "noise_seed", 101.0)])
def test_worker_rejects_numeric_impostors_before_download(worker, node, field, value):
    def history(history):
        history["prompt"][2][node]["inputs"][field] = value

    worker.history_hook = history
    worker_tests.create(worker)
    result = worker_tests.run(worker)
    worker_tests.assert_failed(worker, result, "HISTORY_SUBMISSION_MISMATCH", queued=1, llm=1)
    assert not worker.downloads
    assert exact(result.contract["prepared_workflow"]) == exact(worker.queued[0])


@pytest.mark.parametrize("failed_prior", [False, True])
@pytest.mark.parametrize("damage", [None, "cache", "proof", "current-graph"])
def test_worker_reuse_verifies_old_proof_before_semantic_cache_matching(worker, failed_prior, damage):
    if failed_prior:
        worker.history_hook = lambda history: history["prompt"][2]["108"]["inputs"].update(cfg=2)
    prior_id = worker_tests.create(worker)
    prior = worker_tests.run(worker)
    assert prior.task.status == ("failed" if failed_prior else "completed")
    worker.llm.reset_mock()
    current = deepcopy(prior.contract)
    graph = current.pop("prepared_workflow")
    for node, field in NUMBER_FIELDS:
        graph[node]["inputs"][field] = 1.0
    current["workflow"]["contract_hash"] = legacy_stable(graph, worker.mapping)
    current["prompt"]["cache_fingerprint"] = legacy_cache(current)
    current["prompt"].update(llm_invoked=False)
    assert current["prompt"]["cache_fingerprint"] != prior.contract["prompt"]["cache_fingerprint"]
    if damage == "current-graph":
        graph["108"]["inputs"]["cfg"] = 2.0
    elif damage:
        with worker.sessions() as db:
            record = db.get(worker.Task, prior_id)
            contract = worker.contracts.read_contract(record)
            if damage == "cache":
                contract["prompt"]["cache_fingerprint"] = current["prompt"]["cache_fingerprint"]
            else:
                contract["validation"]["graph"] = {"passed": True}
            contract["storage_hash"] = legacy_digest({key: value for key, value in contract.items() if key != "storage_hash"})
            record.metadata_json = exact({worker.contracts.CONTRACT_KEY: contract})
            db.commit()
    before = worker_tests.saved(worker, prior_id)
    before_graph = exact(graph)
    with worker.sessions() as db:
        new_task = SimpleNamespace(id="new-attempt", shot_id="shot")
        if damage:
            with pytest.raises(worker.contracts.KeyframeReferenceError, match="CACHE_BINDING_UNVERIFIED"):
                worker.service._get_reusable_keyframe_prompt(db, new_task, current, graph=graph)
        else:
            assert worker.service._get_reusable_keyframe_prompt(db, new_task, current, graph=graph) == prior.task.prompt_text
            assert current["prompt"]["origin"] == "reuse" and current["prompt"]["reused_from_task_id"] == prior_id
    after = worker_tests.saved(worker, prior_id)
    assert after.task.metadata_json == before.task.metadata_json
    assert after.task.status == before.task.status and after.task.result_url == before.task.result_url
    assert exact(graph) == before_graph
    worker.llm.assert_not_awaited()
    assert len(worker.queued) == 1


@pytest.mark.parametrize("fields", [(NUMBER_FIELDS[0],), (NUMBER_FIELDS[1],), NUMBER_FIELDS])
def test_worker_call_passes_prepared_graph_for_cross_representation_reuse(worker, fields):
    prior_id = worker_tests.create(worker)
    prior = worker_tests.run(worker)
    worker_tests.assert_completed(worker, prior, "PRIMARY_STORYBOARD")
    with worker.sessions() as db:
        workflow = db.get(worker.Workflow, "workflow")
        graph = json.loads(workflow.workflow_json)
        for node, field in fields:
            graph[node]["inputs"][field] = 1.0
        workflow.workflow_json = exact(graph)
        db.commit()
    worker.llm.reset_mock()
    worker_tests.create(worker, skip_llm_when_prompt_exists=True)
    result = worker_tests.run(worker)
    worker_tests.assert_completed(worker, result, "PRIMARY_STORYBOARD")
    assert result.contract["prompt"]["reused_from_task_id"] == prior_id
    assert result.contract["workflow"]["contract_hash"] != prior.contract["workflow"]["contract_hash"]
    assert result.contract["prompt"]["cache_fingerprint"] != prior.contract["prompt"]["cache_fingerprint"]
    assert worker_tests.saved(worker, prior_id).task.metadata_json == prior.task.metadata_json
    for node, field in fields:
        assert type(result.contract["prepared_workflow"][node]["inputs"][field]) is float
    worker.llm.assert_not_awaited()
    assert len(worker.queued) == len(worker.downloads) == 2


@pytest.mark.parametrize("production_available", [False, True])
def test_production_reuse_skips_newest_benchmark_before_selecting_prompt(worker, monkeypatch, production_available):
    prior_id = worker_tests.create(worker)
    prior = worker_tests.run(worker)
    worker_tests.assert_completed(worker, prior, "PRIMARY_STORYBOARD")
    execution = sys.modules["app.services.task_execution"]
    with worker.sessions() as db:
        original = db.get(worker.Task, prior_id)
        if production_available:
            benchmark = worker.Task(**{column.key: getattr(original, column.key) for column in worker.Task.__table__.columns})
            benchmark.id = "newest-benchmark"
            benchmark.created_at = original.created_at + timedelta(days=1)
            db.add(benchmark)
        else:
            benchmark = original
        metadata = execution.create_execution_metadata(db.get(worker.Shot, "shot"), purpose="benchmark")
        contract = deepcopy(prior.contract)
        contract.update(execution_purpose="benchmark", execution_attempt_id=metadata["execution"]["attempt_id"])
        worker.contracts.seal_contract(contract)
        metadata[worker.contracts.CONTRACT_KEY] = contract
        benchmark.metadata_json = exact(metadata)
        db.commit()
        worker.contracts.validate_frozen_contract(contract, benchmark, require_submitted=True)
        benchmark_id, benchmark_metadata = benchmark.id, benchmark.metadata_json
    checked_ids = []
    validate = worker.module.validate_frozen_contract

    def checked(contract, task=None, **options):
        checked_ids.append(task.id if task else None)
        return validate(contract, task, **options)

    monkeypatch.setattr(worker.module, "validate_frozen_contract", checked)
    worker.llm.reset_mock()
    worker_tests.create(worker, skip_llm_when_prompt_exists=True)
    result = worker_tests.run(worker)
    if production_available:
        worker_tests.assert_completed(worker, result, "PRIMARY_STORYBOARD")
        assert result.contract["prompt"]["reused_from_task_id"] == prior_id
        assert prior_id in checked_ids
    else:
        worker_tests.assert_failed(worker, result, "CACHE_BINDING_UNVERIFIED", queued=1)
        assert "reused_from_task_id" not in result.contract["prompt"]
    assert benchmark_id not in checked_ids
    assert worker_tests.saved(worker, benchmark_id).task.metadata_json == benchmark_metadata
    worker.llm.assert_not_awaited()
    with worker.sessions() as db:
        current = deepcopy(contract)
        assert worker.service._get_reusable_keyframe_prompt(
            db, SimpleNamespace(id="benchmark-continuation", shot_id="shot"), current, graph=current["prepared_workflow"],
        ) == prior.task.prompt_text
        assert current["prompt"]["reused_from_task_id"] == benchmark_id
    assert worker_tests.saved(worker, benchmark_id).task.metadata_json == benchmark_metadata


def test_worker_retains_postselection_benchmark_adoption_guard(worker, monkeypatch):
    prior_id = worker_tests.create(worker)
    worker_tests.assert_completed(worker, worker_tests.run(worker), "PRIMARY_STORYBOARD")
    reuse = worker.service._get_reusable_keyframe_prompt

    def changed_purpose(*args, **kwargs):
        prompt = reuse(*args, **kwargs)
        with worker.sessions() as db:
            prior = db.get(worker.Task, prior_id)
            metadata = json.loads(prior.metadata_json)
            metadata["execution_purpose"] = "benchmark"
            prior.metadata_json = exact(metadata)
            db.commit()
        return prompt

    monkeypatch.setattr(worker.service, "_get_reusable_keyframe_prompt", changed_purpose)
    worker.llm.reset_mock()
    worker_tests.create(worker, skip_llm_when_prompt_exists=True)
    result = worker_tests.run(worker)
    worker_tests.assert_failed(worker, result, "BENCHMARK_PROMPT_REQUIRES_ADOPTION", queued=1)
    assert len(worker.downloads) == 1
    worker.llm.assert_not_awaited()


@pytest.mark.parametrize("reconcile", [False, True])
def test_recovery_and_real_client_poll_use_numeric_history(recovery, reconcile):
    state = recovery
    for node, field in NUMBER_FIELDS:
        state.history["prompt"][2][node]["inputs"][field] = 1.0
    original = exact(state.graph)
    if reconcile:
        assert asyncio.run(state.service.reconcile_active_tasks([state.task])) == 1
    else:
        assert recovery_tests.recover(state) is True
    assert state.task.status == "completed" and len(state.downloads) == 1
    assert exact(json.loads(state.task.workflow_json)) == original


def test_workflow_api_accepts_numeric_projection_without_changing_saved_evidence(recovery):
    graph = deepcopy(recovery.graph)
    for node, field in NUMBER_FIELDS:
        graph[node]["inputs"][field] = 1.0
    recovery_tests.change_task(recovery, workflow_json=exact(graph))
    before = recovery_tests.task_evidence(recovery)
    result = asyncio.run(recovery.api.get_task_workflow(recovery.task.id, recovery.repo))["data"]
    assert result["workflowSource"] == "submitted" and result["sourceProof"]["verified"] is True
    assert exact(result["workflow"]) == exact(graph) and result["diagnostic"] is None
    assert recovery_tests.task_evidence(recovery) == before
    assert not recovery.requests and not recovery.downloads


@pytest.mark.parametrize("node,field,value", [("108", "cfg", True), ("108", "cfg", 1.0000000000000002),
                                             ("101", "samples", ["100", 0.0]), ("123", "value", 1920.0)])
def test_recovery_rejects_numeric_impostors_before_download(recovery, node, field, value):
    recovery.history["prompt"][2][node]["inputs"][field] = value
    before = recovery_tests.media(recovery)
    assert recovery_tests.recover(recovery) is False
    assert not recovery.downloads and recovery_tests.media(recovery) == before
    assert "HISTORY_SUBMISSION_MISMATCH" in recovery.task.error_message


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_numeric_history_never_revives_terminal_recovery(recovery, status):
    recovery_tests.change_task(recovery, status=status)
    for node, field in NUMBER_FIELDS:
        recovery.history["prompt"][2][node]["inputs"][field] = 1.0
    before = recovery_tests.task_evidence(recovery)
    assert recovery_tests.recover(recovery) is False
    assert recovery_tests.task_evidence(recovery) == before and not recovery.downloads
