"""Isolated #09 graph proofs. Run with pytest --noconftest; fixtures are read-only."""

import builtins
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import ModuleType

import pytest


BACKEND = Path(__file__).resolve().parents[1]
MODULE = BACKEND / "app/services/keyframe_reference_graph.py"
# Resolve the actual shipped files without creating workflow copies or importing app.
GRAPH_FILES = (
    BACKEND / "workflows/keyframe_flux2_klein.json",
    next((BACKEND / "user_workflows").glob("*Flux2Klein*keyframe_image.json")),
    next((BACKEND / "user_workflows").glob("*Qwen-Edit-2511*keyframe_image.json")),
)
MAPPINGS = (
    {"prompt_node_id": "110", "save_image_node_id": "9", "reference_image_node_id": "76"},
    {"prompt_node_id": "117", "save_image_node_id": "9", "reference_image_node_id": "76"},
    {"prompt_node_id": "184", "save_image_node_id": "163", "reference_image_node_id": "170"},
)
PROMPT = "Keep the subject and composition; change the light.\nExact spacing matters. "
RECEIPT = "uploads/keyframe-reference-receipt.png"


def _load_module():
    spec = importlib.util.spec_from_file_location("_isolated_keyframe_reference_graph", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_module()


def _forbidden(*args, **kwargs):
    raise AssertionError("App/settings/database/network/write access is forbidden")


@pytest.fixture(autouse=True)
def isolated_io(monkeypatch):
    for name in ("app", "app.core", "app.core.config", "app.core.database", "app.services"):
        module = ModuleType(name)
        module.__path__ = []
        module.get_settings = _forbidden
        module.SessionLocal = _forbidden
        monkeypatch.setitem(sys.modules, name, module)
    original_import = builtins.__import__

    def no_app_import(name, *args, **kwargs):
        if name == "app" or name.startswith("app.") or name == "sqlalchemy" or name.startswith("sqlalchemy."):
            _forbidden()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_app_import)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(sqlite3, "connect", _forbidden)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", _forbidden)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    for owner in (builtins, io):
        original = owner.open

        def read_only(file, mode="r", *args, _open=original, **kwargs):
            if any(flag in mode for flag in "wax+"):
                _forbidden()
            return _open(file, mode, *args, **kwargs)

        monkeypatch.setattr(owner, "open", read_only)


def _fixture(index=0):
    return json.loads(GRAPH_FILES[index].read_text(encoding="utf-8")), dict(MAPPINGS[index])


def _bind(graph, mapping, prompt=PROMPT, filename=RECEIPT):
    node = graph[str(mapping["prompt_node_id"])]["inputs"]
    node["text" if "text" in node else "prompt"] = prompt
    reference_id = mapping.get("reference_image_node_id")
    if reference_id is not None and str(reference_id) in graph:
        graph[str(reference_id)]["inputs"]["image"] = filename


def _reject(graph, mapping, code=None, **kwargs):
    with pytest.raises(gate.KeyframeGraphError) as error:
        gate.validate_keyframe_graph(graph, mapping, reference_count=kwargs.pop("reference_count", 1), **kwargs)
    assert isinstance(error.value, RuntimeError)
    assert error.value.code
    if code:
        assert error.value.code == code


def test_module_has_no_application_import_or_external_io():
    module = _load_module()
    graph, mapping = _fixture()
    assert module.validate_keyframe_graph(graph, mapping, reference_count=1)["family"] == "flux2"


@pytest.mark.parametrize("index", range(3), ids=["builtin-flux", "custom-flux", "custom-qwen"])
def test_real_graph_build_once_empty_preflight_then_exact_binding(index):
    graph, mapping = _fixture(index)
    before = deepcopy(graph)
    _bind(graph, mapping, prompt="", filename="")
    prepared = gate.prepare_keyframe_graph(graph, mapping, has_reference=True)
    preflight = gate.validate_keyframe_graph(prepared, mapping, reference_count=1)
    assert preflight["effective_prompt"] == preflight["reference_filename"] == ""
    _bind(prepared, mapping)
    result = gate.validate_keyframe_graph(
        prepared, mapping, reference_count=1, expected_filename=RECEIPT, expected_prompt=PROMPT,
    )
    assert result["family"] == ("qwen" if index == 2 else "flux2")
    assert result["reference_count"] == 1
    assert result["reference_node_id"] == mapping["reference_image_node_id"]
    assert result["image_source_nodes"] == [mapping["reference_image_node_id"]]
    assert result["positive_consumer_node_id"] == ("165" if index == 2 else "110")
    assert result["prompt_node_id"] == mapping["prompt_node_id"]
    assert result["prompt_field"] == ("prompt" if index == 2 else "text")
    assert result["save_image_node_id"] == mapping["save_image_node_id"]
    assert result["effective_prompt"] == PROMPT
    assert result["reference_filename"] == RECEIPT
    assert json.loads(json.dumps(result)) == result
    assert graph[mapping["reference_image_node_id"]]["inputs"]["image"] == ""
    assert prepared[mapping["save_image_node_id"]] is not graph[mapping["save_image_node_id"]]
    assert before == json.loads(GRAPH_FILES[index].read_text(encoding="utf-8"))


@pytest.mark.parametrize("index", range(3))
def test_placeholder_preflight_is_nonmutating_and_canonical(index):
    graph, mapping = _fixture(index)
    original = deepcopy(graph), deepcopy(mapping)
    result = gate.validate_keyframe_graph(graph, mapping, reference_count=1)
    reversed_graph = dict(reversed(list(graph.items())))
    assert gate.validate_keyframe_graph(reversed_graph, mapping, reference_count=1) == result
    assert (graph, mapping) == original


@pytest.mark.parametrize("index", range(3))
def test_renumbered_graph_and_integer_mapping_ids(index):
    graph, mapping = _fixture(index)
    ids = {old: str(7000 + offset * 13) for offset, old in enumerate(reversed(graph))}
    renumbered = {}
    for old, node in graph.items():
        for field, value in node["inputs"].items():
            if isinstance(value, list):
                node["inputs"][field] = [ids[value[0]], value[1]]
        renumbered[ids[old]] = node
    mapping = {key: int(ids[value]) for key, value in mapping.items()}
    _bind(renumbered, mapping)
    prepared = gate.prepare_keyframe_graph(renumbered, mapping, has_reference=True)
    result = gate.validate_keyframe_graph(prepared, mapping, reference_count=1, expected_filename=RECEIPT, expected_prompt=PROMPT)
    assert result["reference_node_id"] == str(mapping["reference_image_node_id"])
    assert result["prompt_node_id"] == str(mapping["prompt_node_id"])
    if index == 0:
        none = gate.prepare_keyframe_graph(renumbered, mapping, has_reference=False)
        assert gate.validate_keyframe_graph(none, mapping, reference_count=0)["reference_node_id"] is None


def test_normalize_mapping_only_canonical_ids_and_no_mutation():
    mapping = {"prompt_node_id": 110, "save_image_node_id": 9, "reference_image_node_id": 76,
               "width_node_id": None, "height_node_id": ""}
    original = deepcopy(mapping)
    assert gate.normalize_keyframe_mapping(mapping) == MAPPINGS[0]
    assert mapping == original


@pytest.mark.parametrize("axis,node_id", [("width", "123"), ("height", "125")])
def test_dimension_mapping_must_match_the_effective_axis(axis, node_id):
    graph, mapping = _fixture()
    mapping[f"{axis}_node_id"] = int(node_id)
    assert gate.validate_keyframe_graph(graph, mapping, reference_count=1)["family"] == "flux2"
    mapping[f"{axis}_node_id"] = "125" if axis == "width" else "123"
    _reject(graph, mapping, "invalid_mapping")


@pytest.mark.parametrize("value", [True, False, -1, 1.5, [], {}, " auto", "auto", "None", "null", " 76", "76 "])
def test_bad_mapping_ids(value):
    mapping = {**MAPPINGS[0], "reference_image_node_id": value}
    with pytest.raises(gate.KeyframeGraphError, match="explicit node ID"):
        gate.normalize_keyframe_mapping(mapping)


@pytest.mark.parametrize("mapping", [None, [], {}, {"prompt_node_id": 110}, {"prompt_node_id": "", "save_image_node_id": "9"},
                                     {**MAPPINGS[0], "reference_image_node_id": "110"}])
def test_missing_mapping_or_aliases_fail(mapping):
    with pytest.raises(gate.KeyframeGraphError) as error:
        gate.normalize_keyframe_mapping(mapping)
    assert error.value.code == "invalid_mapping"


@pytest.mark.parametrize("key", [
    "load_image_node_id", "reference_node_id", "character_reference_image_node_id",
    "scene_reference_image_node_id", "prop_reference_image_node_id", "custom_reference_image_node_1",
    "keyframe_reference_node_1", "keyframe_node_1", "reference_image_node_2", "reference_audio_node_id",
])
@pytest.mark.parametrize("generic", [True, False])
def test_role_slots_and_aliases_are_never_reinterpreted(key, generic):
    graph, mapping = _fixture()
    if not generic:
        del mapping["reference_image_node_id"]
    mapping[key] = "76"
    _reject(graph, mapping, "invalid_mapping")
    with pytest.raises(gate.KeyframeGraphError):
        gate.prepare_keyframe_graph(graph, mapping, has_reference=False)


def test_safe_none_removes_both_reference_conditionings_and_only_unused_image_nodes():
    graph, mapping = _fixture()
    original = deepcopy(graph)
    prepared = gate.prepare_keyframe_graph(graph, mapping, has_reference=False)
    assert set(graph) - set(prepared) == {"76", "107", "114", "115", "116"}
    assert prepared["108"]["inputs"]["positive"] == ["110", 0]
    assert prepared["108"]["inputs"]["negative"] == ["111", 0]
    assert prepared["111"]["inputs"]["conditioning"] == ["110", 0]
    assert prepared["105"] == original["105"]
    assert graph == original
    _bind(prepared, mapping, prompt="An original landscape with no picture-reference rule.")
    result = gate.validate_keyframe_graph(prepared, mapping, reference_count=0,
                                          expected_prompt="An original landscape with no picture-reference rule.")
    assert result["reference_node_id"] is result["reference_filename"] is None
    assert result["image_source_nodes"] == result["image_routes"] == []
    assert gate.prepare_keyframe_graph(prepared, mapping, has_reference=False) == prepared
    no_reference_mapping = {key: value for key, value in mapping.items() if key != "reference_image_node_id"}
    assert gate.validate_keyframe_graph(prepared, no_reference_mapping, reference_count=0) == result


@pytest.mark.parametrize("index", [1, 2], ids=["image-derived-flux-dimensions", "qwen-vae-init"])
def test_none_rejects_image_dependent_graph_without_mutation(index):
    graph, mapping = _fixture(index)
    original = deepcopy(graph)
    with pytest.raises(gate.KeyframeGraphError) as error:
        gate.prepare_keyframe_graph(graph, mapping, has_reference=False)
    assert error.value.code == "unsupported_none"
    assert graph == original


@pytest.mark.parametrize("index", range(3))
def test_none_cannot_validate_with_a_remaining_image_source(index):
    graph, mapping = _fixture(index)
    _reject(graph, mapping, reference_count=0)


@pytest.mark.parametrize("count", [-1, 2, 3, True, False, None, "1", 1.0])
def test_invalid_reference_counts(count):
    graph, mapping = _fixture()
    _reject(graph, mapping, "reference_count", reference_count=count)


@pytest.mark.parametrize("value", [0, 1, None, "false"])
def test_prepare_requires_boolean(value):
    graph, mapping = _fixture()
    with pytest.raises(gate.KeyframeGraphError) as error:
        gate.prepare_keyframe_graph(graph, mapping, has_reference=value)
    assert error.value.code == "reference_count"


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("change", ["filename", "prompt", "prompt-whitespace", "receipt-basename"])
def test_final_requires_exact_effective_prompt_and_upload_receipt(index, change):
    graph, mapping = _fixture(index)
    _bind(graph, mapping)
    expected_prompt, expected_filename = PROMPT, RECEIPT
    if change == "filename":
        graph[mapping["reference_image_node_id"]]["inputs"]["image"] = "default.png"
    elif change == "prompt":
        expected_prompt += "extra"
    elif change == "prompt-whitespace":
        expected_prompt = PROMPT.strip()
    else:
        expected_filename = Path(RECEIPT).name
    _reject(graph, mapping, "reference_binding" if change in {"filename", "receipt-basename"} else "prompt_binding",
            expected_prompt=expected_prompt, expected_filename=expected_filename)


@pytest.mark.parametrize("prompt,filename", [(None, RECEIPT), ("", RECEIPT), ("  ", RECEIPT), (3, RECEIPT),
                                                   (PROMPT, None), (PROMPT, ""), (PROMPT, 3)])
def test_partial_final_or_blank_expected_bindings_rejected(prompt, filename):
    graph, mapping = _fixture()
    _bind(graph, mapping)
    _reject(graph, mapping, expected_prompt=prompt, expected_filename=filename)


def test_zero_reference_final_disallows_upload_receipt():
    graph, mapping = _fixture()
    graph = gate.prepare_keyframe_graph(graph, mapping, has_reference=False)
    _bind(graph, mapping)
    _reject(graph, mapping, "reference_binding", reference_count=0, expected_filename=RECEIPT, expected_prompt=PROMPT)


@pytest.mark.parametrize("index", range(3))
def test_decoy_prompt_mapping_cannot_pass_even_when_text_matches(index):
    graph, mapping = _fixture(index)
    _bind(graph, mapping)
    graph["decoy"] = {"class_type": "CR Text", "inputs": {"text": PROMPT}}
    mapping["prompt_node_id"] = "decoy"
    _reject(graph, mapping, "prompt_binding", expected_filename=RECEIPT, expected_prompt=PROMPT)


def test_negative_prompt_mapping_is_not_effective_positive():
    graph, mapping = _fixture()
    graph["decoy"] = deepcopy(graph["110"])
    graph["111"]["inputs"]["conditioning"] = ["decoy", 0]
    mapping["prompt_node_id"] = "decoy"
    _reject(graph, mapping, "prompt_binding")


@pytest.mark.parametrize("change", ["save-reference", "decode-vae-encode", "positive-zero", "negative-only-reference", "dimensions-only-reference"])
def test_proof_traces_save_decode_sampler_and_positive_not_node_counts(change):
    graph, mapping = _fixture()
    if change == "save-reference":
        graph["9"]["inputs"]["images"] = ["76", 0]
    elif change == "decode-vae-encode":
        graph["101"]["inputs"]["samples"] = ["115", 0]
    elif change == "positive-zero":
        graph["108"]["inputs"]["positive"] = ["111", 0]
    elif change == "negative-only-reference":
        graph["108"]["inputs"]["positive"] = ["110", 0]
    else:
        graph, mapping = _fixture(1)
        graph["108"]["inputs"]["positive"] = ["110", 0]
        graph["108"]["inputs"]["negative"] = ["111", 0]
    _reject(graph, mapping)


@pytest.mark.parametrize("field", ["positive", "negative"])
def test_duplicate_flux_reference_additions_reject_same_source(field):
    graph, mapping = _fixture()
    graph["duplicate"] = deepcopy(graph["116"])
    graph["duplicate"]["inputs"]["conditioning"] = graph["108"]["inputs"][field]
    graph["108"]["inputs"][field] = ["duplicate", 0]
    _reject(graph, mapping, "reference_count")


@pytest.mark.parametrize("slot", ["vl_resize_image2", "vl_resize_image3", "image2", "vae_resize_image2"])
def test_qwen_multiple_image_slots_reject_even_with_same_source(slot):
    graph, mapping = _fixture(2)
    graph["165"]["inputs"][slot] = ["160", 0]
    _reject(graph, mapping)


@pytest.mark.parametrize("filename", ["default.png", "", RECEIPT])
@pytest.mark.parametrize("consumer", ["orphan", "preview", "negative", "dimensions", "initialization"])
def test_extra_load_image_cannot_hide_by_filename_or_secondary_role(filename, consumer):
    graph, mapping = _fixture(2 if consumer == "initialization" else 1)
    _bind(graph, mapping)
    graph["extra"] = {"class_type": "LoadImage", "inputs": {"image": filename}}
    if consumer == "preview":
        graph["extra-preview"] = {"class_type": "PreviewImage", "inputs": {"images": ["extra", 0]}}
    elif consumer == "negative":
        graph["extra-encode"] = deepcopy(graph["115"])
        graph["extra-encode"]["inputs"]["pixels"] = ["extra", 0]
        graph["114"]["inputs"]["latent"] = ["extra-encode", 0]
    elif consumer == "dimensions":
        graph["126"]["inputs"]["image"] = ["extra", 0]
    elif consumer == "initialization":
        graph["161"]["inputs"]["pixels"] = ["extra", 0]
    _reject(graph, mapping, "reference_count", expected_filename=RECEIPT, expected_prompt=PROMPT)
    with pytest.raises(gate.KeyframeGraphError):
        gate.prepare_keyframe_graph(graph, mapping, has_reference=False)


def test_same_qwen_source_deduplicated_across_conditioning_dimensions_init_and_preview():
    graph, mapping = _fixture(2)
    result = gate.validate_keyframe_graph(graph, mapping, reference_count=1)
    reference_routes = [route for route in result["image_routes"] if route["kind"] == "reference"]
    assert {route["role"] for route in reference_routes} == {"positive", "negative", "dimensions", "initialization", "preview"}
    assert {route["source_node_id"] for route in reference_routes} == {"170"}
    assert next(route for route in reference_routes if route["role"] == "initialization")["node_ids"] == ["170", "160", "161", "169"]
    assert next(route for route in result["image_routes"] if route["role"] == "cleanup")["kind"] == "generated"


@pytest.mark.parametrize("value", ["fixed context", " ", "\n"])
@pytest.mark.parametrize("port", ["prefix", "separator", "text3"])
def test_qwen_concat_nonidentity_context_rejected_in_preflight(value, port):
    graph, mapping = _fixture(2)
    _bind(graph, mapping, prompt="")
    if port == "prefix":
        graph["185"]["inputs"]["prompt"] = value
    else:
        graph["186"]["inputs"][port] = value
    _reject(graph, mapping, "prompt_binding")


def test_qwen_duplicate_empty_prompt_binding_is_not_an_identity():
    graph, mapping = _fixture(2)
    _bind(graph, mapping, prompt="")
    graph["186"]["inputs"]["text1"] = ["184", 0]
    _reject(graph, mapping, "prompt_binding")


@pytest.mark.parametrize("duplicate_prompt", [True, False])
def test_shared_concat_dag_proof_is_bounded_without_expanding_text(duplicate_prompt):
    graph, mapping = _fixture(2)
    _bind(graph, mapping, prompt="")
    source = "184" if duplicate_prompt else "185"
    for index in range(100):
        node_id = f"concat-{index}"
        graph[node_id] = {"class_type": "ConcatTextOfUtils", "inputs": {
            "text1": [source, 0], "text2": [source, 0], "text3": "", "separator": "",
        }}
        source = node_id
    graph["186"]["inputs"]["text1"] = [source, 0]
    if duplicate_prompt:
        _reject(graph, mapping, "prompt_binding")
    else:
        assert gate.validate_keyframe_graph(graph, mapping, reference_count=1)["effective_prompt"] == ""


def test_flux_cr_identity_chain_and_qwen_direct_prompt_binding():
    graph, mapping = _fixture(1)
    graph["identity"] = {"class_type": "CR Text", "inputs": {"text": ["117", 0]}}
    graph["110"]["inputs"]["text"] = ["identity", 0]
    assert gate.validate_keyframe_graph(graph, mapping, reference_count=1)["prompt_node_id"] == "117"
    graph, mapping = _fixture(2)
    graph["165"]["inputs"]["prompt"] = PROMPT
    for node_id in ("184", "185", "186", "187"):
        del graph[node_id]
    mapping["prompt_node_id"] = "165"
    _bind(graph, mapping)
    assert gate.validate_keyframe_graph(graph, mapping, reference_count=1, expected_filename=RECEIPT, expected_prompt=PROMPT)["prompt_field"] == "prompt"


@pytest.mark.parametrize("slot", [-1, 1, 2, 999, True, False, "0", 0.0, None])
@pytest.mark.parametrize("target", ["image", "prompt", "conditioning", "model"])
def test_source_output_slots_are_finite_and_typed(slot, target):
    graph, mapping = _fixture(1)
    node_id, field = {"image": ("107", "image"), "prompt": ("110", "text"),
                      "conditioning": ("108", "positive"), "model": ("108", "model")}[target]
    graph[node_id]["inputs"][field][1] = slot
    _reject(graph, mapping, "invalid_link")


@pytest.mark.parametrize("link", [["missing", 0], [76, 0], ["76"], ["76", 0, "extra"], ["105", 0], {"node": "76"}])
def test_malformed_dangling_or_wrong_type_links(link):
    graph, mapping = _fixture()
    graph["107"]["inputs"]["image"] = link
    _reject(graph, mapping)


@pytest.mark.parametrize("node_id,field,slot", [("101", "samples", 2), ("123", "value", 2), ("125", "value", 99)])
def test_latent_and_dimension_output_slots_are_bounded(node_id, field, slot):
    graph, mapping = _fixture(1)
    graph[node_id]["inputs"][field][1] = slot
    _reject(graph, mapping, "invalid_link")


def test_known_sampler_denoised_latent_slot_and_image_size_height_slot():
    graph, mapping = _fixture(1)
    graph["101"]["inputs"]["samples"][1] = 1
    assert graph["125"]["inputs"]["value"] == ["126", 1]
    assert gate.validate_keyframe_graph(graph, mapping, reference_count=1)["family"] == "flux2"


@pytest.mark.parametrize("kind", ["LoadImageFromURL", "LoadImagePath", "OpaqueModel", "LoraLoaderUnknown", "VHS_LoadVideo", "LoadAudio", "OpaqueText"])
def test_unknown_classes_fail_even_orphaned(kind):
    graph, mapping = _fixture()
    graph["opaque"] = {"class_type": kind, "inputs": {}}
    _reject(graph, mapping, "unsupported_node")


@pytest.mark.parametrize("port,value", [("image2", ["76", 0]), ("mask", ["76", 1]), ("audio", "default.wav"),
                                           ("video", "default.mp4"), ("context_images", []), ("opaque", {"image": "default.png"})])
def test_unknown_ports_rejected_on_allowlisted_classes(port, value):
    graph, mapping = _fixture()
    graph["103"]["inputs"][port] = value
    _reject(graph, mapping, "unsupported_port")


@pytest.mark.parametrize("branch", ["save", "preview", "purge", "orphan"])
def test_unrelated_generation_output_branches_rejected(branch):
    graph, mapping = _fixture()
    graph["other-sampler"] = deepcopy(graph["100"])
    graph["other-decode"] = deepcopy(graph["101"])
    graph["other-decode"]["inputs"]["samples"] = ["other-sampler", 0]
    if branch == "save":
        graph["other-output"] = {"class_type": "SaveImage", "inputs": {"images": ["other-decode", 0], "filename_prefix": "extra"}}
    elif branch == "preview":
        graph["other-output"] = {"class_type": "PreviewImage", "inputs": {"images": ["other-decode", 0]}}
    elif branch == "purge":
        graph["other-output"] = {"class_type": "LayerUtility: PurgeVRAM", "inputs": {"anything": ["other-decode", 0], "purge_cache": True, "purge_models": True}}
    _reject(graph, mapping)


def test_secondary_generation_cannot_hide_in_generated_preview_dimensions():
    graph, mapping = _fixture(2)
    graph["other-sampler"] = deepcopy(graph["169"])
    graph["other-decode"] = deepcopy(graph["164"])
    graph["other-decode"]["inputs"]["samples"] = ["other-sampler", 0]
    graph["other-size"] = {"class_type": "GetImageSize", "inputs": {"image": ["other-decode", 0]}}
    graph["preview-resize"] = deepcopy(graph["160"])
    graph["preview-resize"]["inputs"].update({
        "image": ["164", 0], "width": ["other-size", 0], "height": ["other-size", 1],
    })
    graph["159"]["inputs"]["images"] = ["preview-resize", 0]
    _reject(graph, mapping)


def test_approved_generated_preview_dimension_route_is_accounted():
    graph, mapping = _fixture(2)
    graph["generated-size"] = {"class_type": "GetImageSize", "inputs": {"image": ["164", 0]}}
    graph["preview-resize"] = deepcopy(graph["160"])
    graph["preview-resize"]["inputs"].update({
        "image": ["164", 0], "width": ["generated-size", 0], "height": ["generated-size", 1],
    })
    graph["159"]["inputs"]["images"] = ["preview-resize", 0]
    result = gate.validate_keyframe_graph(graph, mapping, reference_count=1)
    route = next(route for route in result["image_routes"] if route["consumer_node_id"] == "generated-size")
    assert route["role"] == "dimensions" and route["kind"] == "generated"
    assert result["image_source_nodes"] == ["170"]


def test_approved_reference_and_generated_preview_cleanup_accounted_and_none_safe():
    graph, mapping = _fixture()
    for name, source in (("reference-preview", "107"), ("generated-preview", "101")):
        graph[name] = {"class_type": "PreviewImage", "inputs": {"images": [source, 0]}}
    graph["reference-cleanup"] = {"class_type": "LayerUtility: PurgeVRAM", "inputs": {"anything": ["76", 0], "purge_cache": True, "purge_models": True}}
    result = gate.validate_keyframe_graph(graph, mapping, reference_count=1)
    assert result["image_source_nodes"] == ["76"]
    prepared = gate.prepare_keyframe_graph(graph, mapping, has_reference=False)
    assert "reference-preview" not in prepared and "reference-cleanup" not in prepared
    assert "generated-preview" in prepared
    assert gate.validate_keyframe_graph(prepared, mapping, reference_count=0)["image_source_nodes"] == []


@pytest.mark.parametrize("change", ["cycle", "missing-input", "malformed-node", "ui-graph", "batch", "nonfinite", "too-large"])
def test_malformed_and_out_of_profile_graphs_raise_coded_errors(change):
    graph, mapping = _fixture()
    if change == "cycle":
        graph["116"]["inputs"]["conditioning"] = ["116", 0]
    elif change == "missing-input":
        del graph["108"]["inputs"]["positive"]
    elif change == "malformed-node":
        graph["110"] = None
    elif change == "ui-graph":
        graph = {"nodes": list(graph.values())}
    elif change == "batch":
        graph["106"]["inputs"]["batch_size"] = 2
    elif change == "nonfinite":
        graph["108"]["inputs"]["cfg"] = float("nan")
    else:
        graph = {str(index): deepcopy(graph["76"]) for index in range(257)}
    _reject(graph, mapping)


@pytest.mark.parametrize("index", range(3))
def test_fingerprint_ignores_only_documented_volatile_fields_without_mutation(index):
    graph, mapping = _fixture(index)
    before = deepcopy(graph)
    fingerprint = gate.stable_graph_fingerprint(graph, mapping)
    assert len(fingerprint) == 64 and int(fingerprint, 16)
    assert graph == before
    _bind(graph, mapping)
    for node in graph.values():
        node["_meta"] = {"title": "changed display label"}
        if node["class_type"] == "RandomNoise":
            node["inputs"]["noise_seed"] += 1
        if node["class_type"] == "KSampler":
            node["inputs"]["seed"] += 1
        if node["class_type"] == "SaveImage":
            node["inputs"]["filename_prefix"] = "task-specific-output"
    assert gate.stable_graph_fingerprint(dict(reversed(list(graph.items()))), mapping) == fingerprint
    assert gate.stable_graph_fingerprint(graph, {key: int(value) for key, value in mapping.items()}) == fingerprint


@pytest.mark.parametrize("index,node_id,field,value", [
    (0, "103", "unet_name", "other-model.safetensors"), (0, "108", "cfg", 2),
    (0, "109", "steps", 12), (0, "123", "value", 1024),
    (2, "165", "instruction", "Changed context"), (2, "33", "lora_name", "other-lora.safetensors"),
    (2, "64", "shift", 4), (2, "65", "strength", 0.5), (2, "187", "text_0", "Changed display text"),
])
def test_fingerprint_preserves_models_context_cfg_dimensions_and_other_real_fields(index, node_id, field, value):
    graph, mapping = _fixture(index)
    fingerprint = gate.stable_graph_fingerprint(graph, mapping)
    graph[node_id]["inputs"][field] = value
    assert gate.stable_graph_fingerprint(graph, mapping) != fingerprint


def test_fingerprint_preserves_topology_and_zero_reference_mode():
    graph, mapping = _fixture()
    fingerprint = gate.stable_graph_fingerprint(graph, mapping)
    graph["101"]["inputs"]["samples"] = ["100", 1]
    assert gate.stable_graph_fingerprint(graph, mapping) != fingerprint
    prepared = gate.prepare_keyframe_graph(graph, mapping, has_reference=False)
    assert gate.stable_graph_fingerprint(prepared, mapping) != fingerprint
    _bind(prepared, mapping, prompt="")
    empty = gate.stable_graph_fingerprint(prepared, mapping)
    _bind(prepared, mapping)
    assert gate.stable_graph_fingerprint(prepared, mapping) == empty


def test_real_workflow_files_are_never_written():
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in GRAPH_FILES}
    for index in range(3):
        graph, mapping = _fixture(index)
        gate.prepare_keyframe_graph(graph, mapping, has_reference=True)
        gate.validate_keyframe_graph(graph, mapping, reference_count=1)
        gate.stable_graph_fingerprint(graph, mapping)
    graph, mapping = _fixture()
    gate.prepare_keyframe_graph(graph, mapping, has_reference=False)
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in GRAPH_FILES}
