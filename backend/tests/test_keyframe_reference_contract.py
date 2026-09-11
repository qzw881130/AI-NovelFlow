"""Standalone #09 contract regressions: Python 3.11, pytest --noconftest.

Only local stubs, frozen model definitions, read-only workflow data, and an
isolated in-memory SQLite database are used. No P0 fixture/helper is imported.
"""

import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import Column, String, create_engine
from sqlalchemy.orm import Query, Session, declarative_base, relationship


BACKEND = Path(__file__).resolve().parents[1]
DEFAULT = object()
PAYLOAD = b"\x89PNG\r\n\x1a\nresolved-keyframe-snapshot\x00\xff"
PRIMARY = "Use Picture 1, the primary storyboard image, as the only edit base. Raise Ada's hand."
PREVIOUS = "Use Picture 1, the previous keyframe image, as the only edit base. Open the gate."
NONE = "No reference images are provided. Draw two people beside a gate."
SOURCES = [
    pytest.param("PRIMARY_STORYBOARD", "\u4e3b\u5206\u955c\u56fe", None, id="primary"),
    pytest.param("PREVIOUS_KEYFRAME", "\u4e0a\u4e00\u5173\u952e\u5e27 KF2", 2, id="previous-case2"),
    pytest.param("CUSTOM_REFERENCE", "\u81ea\u5b9a\u4e49\u53c2\u8003\u56fe", None, id="custom"),
    pytest.param("SAVED_REFERENCE", "\u5df2\u56fa\u5b9a\u53c2\u8003\u56fe", None, id="fixed"),
]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, BACKEND / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load("_isolated_keyframe_reference_contract", "app/services/keyframe_reference_contract.py")


@pytest.fixture(autouse=True)
def isolation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Production app/settings/database/network access is forbidden")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, forbidden)

    original_connect = sqlite3.dbapi2.connect

    def memory_only(database, *args, **kwargs):
        assert database == ":memory:", "Only a fresh in-memory test database is permitted"
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", memory_only)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", memory_only)

    def stub(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    for name in ("app", "app.core", "app.models", "app.services", "app.services.comfyui"):
        stub(name, __path__=[])
    stub("app.core.config", get_settings=forbidden)
    stub("app.core.database", SessionLocal=forbidden)
    monkeypatch.setitem(sys.modules, "app.services.keyframe_reference_contract", gate)

    def load(name, relative):
        module = _load(name, relative)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    load("app.services.keyframe_reference_graph", "app/services/keyframe_reference_graph.py")
    return SimpleNamespace(stub=stub, load=load, forbidden=forbidden)


def _reject_prompt(prompt, source="PRIMARY_STORYBOARD", code=None):
    with pytest.raises(gate.KeyframeReferenceError) as error:
        gate.validate_reference_prompt(prompt, source)
    assert error.value.code
    if code is not None:
        assert error.value.code == code


@pytest.mark.parametrize("prompt,source", [
    pytest.param(PRIMARY, "PRIMARY_STORYBOARD", id="primary-english"),
    pytest.param("Edit the primary shot image.", "PRIMARY_STORYBOARD", id="no-quality-threshold"),
    pytest.param("Use the storyboard picture. Change only the light.", "PRIMARY_STORYBOARD", id="storyboard-label"),
    pytest.param("\u4ee5\u4e3b\u5206\u955c\u56fe\u4e3a\u5e95\u56fe\uff0c\u62ac\u8d77\u53f3\u624b\u3002", "PRIMARY_STORYBOARD", id="primary-chinese"),
    pytest.param("\u4ee5\u4e3b\u5206\u955cSTART\u53c2\u8003\u56fe\u4e3a\u5e95\u56fe\u3002", "PRIMARY_STORYBOARD", id="primary-start"),
    pytest.param(PREVIOUS, "PREVIOUS_KEYFRAME", id="previous-source-case2"),
    pytest.param("Keep the previous frame picture and open the door.", "PREVIOUS_KEYFRAME", id="previous-frame"),
    pytest.param("\u4ee5\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247\u4e3a\u5e95\u56fe\u3002", "PREVIOUS_KEYFRAME", id="previous-chinese"),
    pytest.param("\u6cbf\u7528\u524d\u4e00\u4e2a\u5173\u952e\u5e27\u753b\u9762\u3002", "PREVIOUS_KEYFRAME", id="previous-common-label"),
])
def test_explicit_source_accepts_edit_prose_without_artist_quality_heuristics(prompt, source):
    assert gate.validate_reference_prompt(prompt, source)["passed"] is True


@pytest.mark.parametrize("prompt,source,code", [
    ("Use Picture 1 as the edit base.", "PRIMARY_STORYBOARD", "PRIMARY_SOURCE_NOT_DECLARED"),
    ("Use Picture 1 as the edit base.", "PREVIOUS_KEYFRAME", "PREVIOUS_SOURCE_NOT_DECLARED"),
    (PREVIOUS, "PRIMARY_STORYBOARD", "WRONG_REFERENCE_SOURCE"),
    (PRIMARY, "PREVIOUS_KEYFRAME", "WRONG_REFERENCE_SOURCE"),
    (PRIMARY + " Preserve the previous keyframe image.", "PRIMARY_STORYBOARD", "WRONG_REFERENCE_SOURCE"),
    (PRIMARY + " \u6cbf\u7528\u4e0a\u4e00\u5e27\u56fe\u7247\u3002", "PRIMARY_STORYBOARD", "WRONG_REFERENCE_SOURCE"),
    ("Do not use the primary storyboard image. Use Picture 1.", "PRIMARY_STORYBOARD", "PRIMARY_SOURCE_NOT_DECLARED"),
    ("Do not use previous keyframe image. Use Picture 1.", "PREVIOUS_KEYFRAME", "PREVIOUS_SOURCE_NOT_DECLARED"),
])
def test_source_declaration_is_affirmative_and_matches_resolved_source(prompt, source, code):
    _reject_prompt(prompt, source, code)


@pytest.mark.parametrize("reference", [
    "Picture 1", "<Picture 1>", "picture \uff11", "reference image 1", "input picture 1",
    "the first reference image", "the 1st image", "image 1", "\u56fe\u7247\uff11", "\u56fe\u7247\u4e00",
    "\u53c2\u8003\u56fe1", "\u7b2c\u4e00\u5f20\u53c2\u8003\u56fe", "\u7b2c\uff11\u5f20\u56fe\u7247", "\u7b2c1\u5f20\u56fe", "\u56fe1", "\u56fe\u4e00",
])
def test_common_first_image_forms_mean_one_bound_picture(reference):
    result = gate.validate_reference_prompt(
        f"Use {reference}, the primary storyboard image, as the edit base.", "PRIMARY_STORYBOARD",
    )
    assert result == {"passed": True, "source_kind": "PRIMARY_STORYBOARD", "picture_indexes": [1]}


@pytest.mark.parametrize("reference", [
    "Picture 2", "<Picture 3>", "picture \uff14", "reference image 2", "input picture 4",
    "the second image", "the third reference picture", "the fourth input image",
    "the 2nd image", "the 3rd reference picture", "the 4th input image", "image 2",
    "\u56fe\u7247\uff12", "\u56fe\u7247\u4e8c", "\u53c2\u8003\u56fe3", "\u7b2c\u4e8c\u5f20\u53c2\u8003\u56fe", "\u7b2c\uff13\u5f20\u56fe\u7247", "\u7b2c4\u5f20\u56fe", "\u56fe2", "\u56fe\u56db",
])
def test_common_other_image_forms_cannot_reference_unbound_pictures(reference):
    _reject_prompt(PRIMARY + f" Also use {reference} for the composition.", code="UNBOUND_PICTURE_REFERENCE")


@pytest.mark.parametrize("suffix", [
    "Use Picture 2 for identity, Picture 3 for the courtyard, and Picture 4 for the sword.",
    "Use reference image 2 for identity, reference image 3 for the courtyard, and reference image 4 for the sword.",
    "\u53c2\u8003\u56fe2\u63d0\u4f9b\u4eba\u7269\uff0c\u53c2\u8003\u56fe3\u63d0\u4f9b\u5ead\u9662\uff0c\u53c2\u8003\u56fe4\u63d0\u4f9b\u957f\u5251\u3002",
    "Use Picture 1/2/3/4 as the four supplied references.",
    "Use ref1/2/3/4 as the four supplied references.",
    "\u4f7f\u7528\u53c2\u8003\u56fe1\u30012\u30013\u30014\u4fdd\u6301\u4e00\u81f4\u3002",
])
def test_slot17_multireference_regression_rejects_refs_1_2_3_4(suffix):
    # Self-contained Slot 17 reproducer; no historical/P0 fixture is rewritten.
    _reject_prompt(PRIMARY + " " + suffix, code="UNBOUND_PICTURE_REFERENCE")


@pytest.mark.parametrize("references", [
    "Picture1/2/3/4", "ref1/2/3/4", "Ref1,2,3,4", "reference images 1, 2, 3 and 4",
    "\uff30\uff49\uff43\uff54\uff55\uff52\uff45\uff11\uff0f\uff12\uff0f\uff13\uff0f\uff14", "\u53c2\u8003\u56fe\u4e00\u3001\u4e8c\u3001\u4e09\u3001\u56db",
    "\u7b2c\u4e00\u3001\u4e8c\u3001\u4e09\u3001\u56db\u5f20\u53c2\u8003\u56fe", "\u7b2c\u4e00\u5f20\u3001\u7b2c\u4e8c\u5f20\u3001\u7b2c\u4e09\u5f20\u3001\u7b2c\u56db\u5f20\u53c2\u8003\u56fe",
    "the first, second, third and fourth reference images", "the 1st, 2nd, 3rd and 4th input pictures",
])
def test_shared_prefix_and_suffix_lists_report_every_affirmative_picture_index(references):
    with pytest.raises(gate.KeyframeReferenceError) as error:
        gate.validate_reference_prompt(PRIMARY + f" Use {references}.", "PRIMARY_STORYBOARD")
    assert error.value.code == "UNBOUND_PICTURE_REFERENCE"
    assert str(error.value).endswith(": [1, 2, 3, 4]")


@pytest.mark.parametrize("reference,index", [
    ("\u56fe\u7247\u5341\u4e8c", 12), ("\u7b2c\u4e8c\u5341\u4e09\u5f20\u53c2\u8003\u56fe", 23),
    ("\u7b2c\u4e00\u767e\u96f6\u4e8c\u5f20\u56fe", 102), ("\u56fe\u4e24", 2), ("the 21st image", 21),
])
def test_other_indexes_are_decoded_not_collapsed_to_second_picture(reference, index):
    with pytest.raises(gate.KeyframeReferenceError) as error:
        gate.validate_reference_prompt(PRIMARY + f" Use {reference}.", "PRIMARY_STORYBOARD")
    assert error.value.code == "UNBOUND_PICTURE_REFERENCE"
    assert str(error.value).endswith(f": [1, {index}]")


@pytest.mark.parametrize("references", [
    "Use Picture 2 characters and Picture 3 lighting.", "\u4f7f\u7528\u56fe\u72472\u4eba\u7269\u548c\u56fe3\u5149\u7ebf\u3002",
])
def test_explicit_picture_indexes_are_not_hidden_by_following_subject_nouns(references):
    with pytest.raises(gate.KeyframeReferenceError) as error:
        gate.validate_reference_prompt(PRIMARY + " " + references, "PRIMARY_STORYBOARD")
    assert error.value.code == "UNBOUND_PICTURE_REFERENCE"
    assert str(error.value).endswith(": [1, 2, 3]")


@pytest.mark.parametrize("asset", [
    "Ada's character reference image", "the merged character reference sheet", "the courtyard scene image",
    "the sword prop picture", "\u963f\u5c9a\u7684\u89d2\u8272\u53c2\u8003\u56fe", "\u4e24\u4eba\u7684\u5408\u5e76\u89d2\u8272\u56fe",
    "\u5ead\u9662\u7684\u573a\u666f\u6b63\u5f0f\u53c2\u8003\u56fe", "\u957f\u5251\u7684\u9053\u5177\u56fe",
    "\u89d2\u8272\u3001\u573a\u666f\u6216\u9053\u5177\u53c2\u8003\u56fe",
])
def test_old_context_named_asset_references_reject_independently_of_numbering(asset):
    _reject_prompt(PRIMARY + f" Also use {asset}.", code="UNBOUND_ASSET_REFERENCE")


@pytest.mark.parametrize("suffix", [
    "Do not use Picture 2 or Picture 3.", "Never reference Picture 4.",
    "No additional character reference images are supplied.", "Work without scene reference images.",
    "Do not use previous keyframe image.", "Do not use the previous keyframe image.",
    "\u672a\u63d0\u4f9b\u56fe\u72472\u548c\u56fe\u72473\u3002",
    "\u6ca1\u6709\u63d0\u4f9b\u89d2\u8272\u53c2\u8003\u56fe\u3002", "\u7981\u6b62\u4f7f\u7528\u9053\u5177\u56fe\u3002",
    "\u672a\u63d0\u4f9b\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247\u3001\u89d2\u8272\u53c2\u8003\u56fe\u6216\u573a\u666f\u53c2\u8003\u56fe\u3002",
    "Picture 2 was not provided.", "The previous keyframe image is not supplied.",
    "The character reference image was not provided.", "The custom reference image was not supplied.",
    "\u56fe\u72472\u672a\u63d0\u4f9b\u3002", "\u89d2\u8272\u53c2\u8003\u56fe\u6ca1\u6709\u63d0\u4f9b\u3002",
    "\u660e\u786e\u4e0d\u662f\u4ee5\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u4f5c\u4e3a\u57fa\u7ebf\u3002",
])
def test_negated_or_unprovided_references_are_not_affirmative_inputs(suffix):
    assert gate.validate_reference_prompt(PRIMARY + " " + suffix, "PRIMARY_STORYBOARD")["passed"] is True


@pytest.mark.parametrize("base,source,clause", [
    pytest.param(PREVIOUS, "PREVIOUS_KEYFRAME",
                 "\u672c\u6b21\u4ec5\u7ed1\u5b9a\u8fd9\u4e00\u5f20\u53c2\u8003\u56fe\uff0c\u6ca1\u6709\u989d\u5916\u89d2\u8272\u3001\u573a\u666f\u6216\u9053\u5177\u53c2\u8003\u56fe\u3002",
                 id="kf4-exact-clause"),
    pytest.param(PRIMARY, "PRIMARY_STORYBOARD",
                 "\u672c\u6b21\u6ca1\u6709\u63d0\u4f9b\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247\uff0c\u4e5f\u6ca1\u6709\u989d\u5916\u7684\u89d2\u8272\u3001\u573a\u666f\u6216\u9053\u5177\u53c2\u8003\u56fe\u3002",
                 id="kf5-exact-clause"),
    pytest.param("\u4ee5\u672c\u6b21\u5df2\u7ed1\u5b9a\u7684\u552f\u4e00\u53c2\u8003\u56fe Picture 1\uff08\u4e3b\u5206\u955c\u56fe\uff09\u4f5c\u4e3a\u672c\u6b21\u7f16\u8f91\u57fa\u7ebf\uff1b", "PRIMARY_STORYBOARD",
                 "\u672c\u6b21\u6ca1\u6709\u63d0\u4f9b\u4e0a\u4e00\u5173\u952e\u5e27\u6216\u5176\u4ed6\u89d2\u8272\u3001\u573a\u666f\u3001\u9053\u5177\u53c2\u8003\u56fe\u3002",
                 id="shot4-exact-mixed-negation"),
    pytest.param(PRIMARY, "PRIMARY_STORYBOARD",
                 "\u672c\u6b21\u6ca1\u6709\u63d0\u4f9b\u4e0a\u4e00\u5173\u952e\u5e27\u6216\u5176\u4ed6\u7684\u89d2\u8272\u3001\u573a\u666f\u3001\u9053\u5177\u53c2\u8003\u56fe\u3002",
                 id="other-with-de"),
])
@pytest.mark.parametrize("count", ["", "\u4e00\u5f20", "1\u5f20"], ids=["original", "one-zh", "one-digit"])
def test_negated_shared_suffix_asset_lists_are_clause_local(base, source, clause, count):
    clause = clause.replace("\u89d2\u8272\u3001", count + "\u89d2\u8272\u3001")
    prompt = base + " " + clause.removesuffix("\u3002")
    assert gate.validate_reference_prompt(prompt + "\u3002", source) == {
        "passed": True, "source_kind": source, "picture_indexes": [1],
    }
    for separator in ("\u3002", "\u5e76", "\u4f46"):
        _reject_prompt(prompt + separator + "\u4f7f\u7528\u9053\u5177\u53c2\u8003\u56fe", source, "UNBOUND_ASSET_REFERENCE")
        _reject_prompt(prompt + separator + "\u4f7f\u7528Picture2", source, "UNBOUND_PICTURE_REFERENCE")
        _reject_prompt(prompt + separator + "\u4f7f\u7528\u5176\u4ed6\u89d2\u8272\u3001\u573a\u666f\u3001\u9053\u5177\u53c2\u8003\u56fe", source, "UNBOUND_ASSET_REFERENCE")


@pytest.mark.parametrize("suffix", [
    "Do not use Picture 1 but use Picture 3.",
    "Do not use Picture 1 and use Picture 3.",
    "Do not use Picture 2 but use Picture 3.",
    "Do not use Picture 2 and use Picture 3.",
    "no Picture2 butusePicture3",
    "Do not use character image but use scene image.",
    "Do not use previous keyframe image and use previous frame image.",
    "\u4e0d\u662f\u4ee5\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u4f5c\u4e3a\u57fa\u7ebf\uff0c\u4f46\u4f7f\u7528\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u3002",
    "\u4e0d\u8981\u4f7f\u7528\u56fe\u72472\u4f46\u4f7f\u7528\u56fe\u72473\u3002",
    "\u672a\u63d0\u4f9b\u56fe\u72472\u5e76\u4f7f\u7528\u56fe\u72473\u3002",
    "\u7981\u6b62\u4f7f\u7528\u89d2\u8272\u56fe\u5e76\u4f7f\u7528\u573a\u666f\u56fe\u3002",
    "\u4e0d\u8981\u4f7f\u7528\u7b2c\u4e8c\u5f20\u5e95\u56fe\u4f46\u4f7f\u7528\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247\u3002",
    "\u4e0d\u8981\u4f7f\u7528\u7b2c\u4e8c\u5f20\u5e95\u56fe\u5e76\u4f7f\u7528\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247\u3002",
    "\u4e0d\u8981\u4f7f\u7528\u7b2c\u4e8c\u5f20\u5e76\u4f7f\u7528\u7b2c\u4e09\u5f20\u53c2\u8003\u56fe",
])
def test_negative_clause_cannot_launder_affirmative_use_after_conjunction(suffix):
    _reject_prompt(PRIMARY + " " + suffix)


@pytest.mark.parametrize("negative,positive", [
    ("Do not use Picture 2/3/4", "but use Picture 4"),
    ("No ref2/3/4", "and use ref4"),
    ("Picture 2, Picture 3 and Picture 4 were not supplied", "but use Picture 3"),
    ("\u4e0d\u8981\u4f7f\u7528\u7b2c\u4e8c\u3001\u4e09\u3001\u56db\u5f20\u53c2\u8003\u56fe", "\u5e76\u4f7f\u7528\u56fe\u7247\u4e09"),
    ("\u56fe\u72472\u548c\u56fe\u72473\u672a\u63d0\u4f9b", "\u4f46\u4f7f\u7528\u56fe\u72473"),
])
def test_nonuse_or_unprovided_list_does_not_extend_into_next_affirmative_claim(negative, positive):
    assert gate.validate_reference_prompt(PRIMARY + " " + negative + ".", "PRIMARY_STORYBOARD")["picture_indexes"] == [1]
    _reject_prompt(PRIMARY + " " + negative + " " + positive, code="UNBOUND_PICTURE_REFERENCE")


@pytest.mark.parametrize("suffix", [
    "There are 2 people; the third person enters at 4 seconds. Keep both characters and the sword.",
    "\u753b\u9762\u4e2d\u6709\u4e24\u4e2a\u4eba\uff0c\u7b2c\u4e09\u4e2a\u4eba\u5728\u7b2c4\u79d2\u8d70\u5165\uff0c\u4fdd\u6301\u4e24\u4eba\u7684\u670d\u88c5\u3002",
    "\u56fe\u7247\u4e2d\u6709\uff12\u4eba\u3001\uff13\u628a\u6905\u5b50\u548c\uff14\u76cf\u706f\u3002",
    "Picture 1, 2 people, 3 chairs and 4 lights. Preserve the scene and improve image quality.",
    "Use image 1 and 2 people in the composition.", "\u56fe\u7247\u4e24\u4e2a\u4eba\u4fdd\u6301\u4e0d\u52a8\u3002",
])
def test_people_prop_and_time_counts_are_not_image_counts(suffix):
    result = gate.validate_reference_prompt(PRIMARY + " " + suffix, "PRIMARY_STORYBOARD")
    assert result["picture_indexes"] == [1]


@pytest.mark.parametrize("context", [
    "\u4e0a\u4e00\u5173\u952e\u5e27\u7684\u6587\u5b57\u63cf\u8ff0\u4ec5\u4f9b\u89c4\u5212\u4e0a\u4e0b\u6587\u3002",
    "\u524d\u4e00\u5e27\u6587\u672c\u4ec5\u63cf\u8ff0\u624b\u653e\u4e0b\u7684\u72b6\u6001\uff0c\u4e0d\u662f\u53c2\u8003\u56fe\u3002",
    "The previous keyframe description is text-only planning context, not an uploaded image.",
    "Previous frame text describes the earlier pose for planning only.",
])
def test_previous_planning_text_is_allowed_with_primary_image(context):
    assert gate.validate_reference_prompt(PRIMARY + " " + context, "PRIMARY_STORYBOARD")["passed"] is True


@pytest.mark.parametrize("source,base", [
    ("PRIMARY_STORYBOARD", "\u56fe\u7247\u4e00\u7684\u4e3b\u5206\u955c\u56fe"),
    ("PREVIOUS_KEYFRAME", "\u56fe\u7247\u4e00\u7684\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247"),
])
def test_three_field_chinese_edit_prose_declares_actual_source_not_planning_context(source, base):
    prompt = (
        f"\u56fe\u50cf\u57fa\u51c6\uff1a\u4ee5{base}\u4f5c\u4e3a\u672c\u6b21\u7f16\u8f91\u57fa\u7ebf\u3002\n"
        "\u72b6\u6001\u53d8\u5316\uff1a\u4e0a\u4e00\u5173\u952e\u5e27\u7684\u89c4\u5212\u6587\u5b57\u4ec5\u8bf4\u660e\u963f\u5c9a\u7ad9\u5728\u95e8\u53e3\uff0c\u5f53\u524d\u8ba9\u963f\u5c9a\u62ac\u624b\u3002\n"
        "\u4fdd\u7559\u5185\u5bb9\uff1a\u4e24\u540d\u4eba\u7269\u8eab\u4efd\u3001\u5ead\u9662\u5e03\u5c40\u548c\u957f\u5251\u4f4d\u7f6e\u4e0d\u53d8\u3002"
    )
    assert gate.validate_reference_prompt(prompt, source) == {"passed": True, "source_kind": source, "picture_indexes": [1]}
    other = "PREVIOUS_KEYFRAME" if source == "PRIMARY_STORYBOARD" else "PRIMARY_STORYBOARD"
    _reject_prompt(prompt, other, "WRONG_REFERENCE_SOURCE")


@pytest.mark.parametrize("suffix", [
    "Previous frame text is planning context but use the previous keyframe image as the edit base.",
    "Previous frame text is planning context and use the previous keyframe image as the edit base.",
    "\u4e0a\u4e00\u5173\u952e\u5e27\u7684\u6587\u5b57\u63cf\u8ff0\u4ec5\u4f9b\u89c4\u5212\u4f46\u4f7f\u7528\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247\u4f5c\u4e3a\u5e95\u56fe\u3002",
    "\u4e0a\u4e00\u5173\u952e\u5e27\u7684\u6587\u5b57\u63cf\u8ff0\u4ec5\u4f9b\u89c4\u5212\u5e76\u4f7f\u7528\u4e0a\u4e00\u5173\u952e\u5e27\u56fe\u7247\u4f5c\u4e3a\u5e95\u56fe\u3002",
])
def test_text_only_exemption_cannot_hide_an_affirmative_previous_image(suffix):
    _reject_prompt(PRIMARY + " " + suffix, code="WRONG_REFERENCE_SOURCE")


@pytest.mark.parametrize("prompt", [
    NONE, "\u65e0\u53c2\u8003\u56fe\u3002\u753b\u4e24\u4e2a\u4eba\u3002", "\u6ca1\u6709\u63d0\u4f9b\u4efb\u4f55\u53c2\u8003\u56fe\u3002\u753b\u4e00\u6247\u95e8\u3002",
    "0 reference images are provided. Draw two people.",
    "Reference image count: 0. Draw two people.",
    "\u53c2\u8003\u56fe\u6570\u91cf\u4e3a0\u5f20\u3002\u753b\u4e24\u4e2a\u4eba\u3002",
    "Reference images were not provided. Draw two people.", "Zero input images are provided. Draw two people.",
    "\u8f93\u5165\u56fe\u6570\u91cf\u4e3a\u96f6\u5f20\u3002\u753b\u4e24\u4e2a\u4eba\u3002",
])
def test_none_requires_and_accepts_explicit_zero_reference_declaration(prompt):
    assert gate.validate_reference_prompt(prompt, "NONE") == {
        "passed": True, "source_kind": "NONE", "picture_indexes": [],
    }


@pytest.mark.parametrize("reference", [
    "Picture 1", "the first image", "\u7b2c\u4e00\u5f20\u56fe\u7247", "previous keyframe image",
    "primary storyboard image", "character reference image", "scene image", "prop image",
    "\u4e0a\u4e00\u5e27\u56fe\u7247", "\u4e3b\u5206\u955c\u56fe", "\u89d2\u8272\u53c2\u8003\u56fe", "the custom reference image",
    "input image", "input picture", "the reference image", "the uploaded image", "input image1",
    "\u8f93\u5165\u56fe", "\u672c\u6b21\u7f16\u8f91\u53c2\u8003\u56fe", "\u81ea\u5b9a\u4e49\u53c2\u8003\u56fe", "\u5df2\u56fa\u5b9a\u53c2\u8003\u56fe",
])
def test_none_cannot_affirm_any_numbered_source_or_asset_image(reference):
    _reject_prompt(NONE + f" Use {reference} as the edit base.", "NONE")


def test_none_rejects_undeclared_zero_but_allows_explicit_negative_other_sources():
    _reject_prompt("Draw two people beside a gate.", "NONE", "NO_REFERENCE_NOT_DECLARED")
    result = gate.validate_reference_prompt(
        NONE + " Do not use Picture 1 or previous keyframe image or primary storyboard image or character image.", "NONE",
    )
    assert result["passed"] is True and result["picture_indexes"] == []


@pytest.mark.parametrize("source,prompt", [
    ("PRIMARY_STORYBOARD", PRIMARY), ("PREVIOUS_KEYFRAME", PREVIOUS),
    ("CUSTOM_REFERENCE", "Use the custom reference image."), ("SAVED_REFERENCE", "Use the fixed reference image."),
])
def test_bound_image_source_cannot_also_declare_zero_inputs(source, prompt):
    _reject_prompt(prompt + " No reference images are provided.", source, "WRONG_REFERENCE_SOURCE")


@pytest.mark.parametrize("source,label", [
    ("CUSTOM_REFERENCE", "\u81ea\u5b9a\u4e49\u53c2\u8003\u56fe"), ("SAVED_REFERENCE", "\u5df2\u56fa\u5b9a\u53c2\u8003\u56fe"),
    ("CUSTOM_REFERENCE", "\u672c\u6b21\u7f16\u8f91\u53c2\u8003\u56fe"), ("SAVED_REFERENCE", "reference image"),
    ("CUSTOM_REFERENCE", "Picture 1"), ("SAVED_REFERENCE", "Picture 1"),
])
def test_custom_and_fixed_references_use_generic_or_actual_bound_labels(source, label):
    assert gate.validate_reference_prompt(f"Use {label} as the edit base.", source)["passed"] is True
    _reject_prompt("Change the light.", source, "REFERENCE_SOURCE_NOT_DECLARED")
    _reject_prompt(PRIMARY, source, "WRONG_REFERENCE_SOURCE")
    _reject_prompt(PREVIOUS, source, "WRONG_REFERENCE_SOURCE")


@pytest.mark.parametrize("prompt", [None, "", " \n\t", False, 0, 3, [], {}, [PRIMARY], {"prompt": PRIMARY}, b"edit"])
def test_empty_and_nonstring_model_outputs_reject(prompt):
    _reject_prompt(prompt, code="PROMPT_EMPTY")


@pytest.mark.parametrize("prompt", [
    '{"unknown": "' + PRIMARY + '"}', '["' + PRIMARY + '"]',
    '```json\n{"unknown": "' + PRIMARY + '"}\n```', '{broken "' + PRIMARY,
    json.dumps(PRIMARY), "null", "true", "17",
])
def test_json_and_unknown_json_outputs_are_not_edit_prose(prompt):
    _reject_prompt(prompt)


@pytest.mark.parametrize("source", [None, "", "UNKNOWN", "primary_storyboard", 1, False])
def test_unknown_source_kind_fails_closed(source):
    _reject_prompt("Use Picture 1 as the edit base.", source)


def _bound_contract(source="PRIMARY_STORYBOARD", label="\u4e3b\u5206\u955c\u56fe", source_index=None):
    sha = hashlib.sha256(PAYLOAD).hexdigest()
    return {
        "version": gate.CONTRACT_VERSION, "attempt_id": "attempt-17", "phase": "frozen",
        "planned": {"intent": {"mode": "auto_select", "url": "/unresolved-decoy.png"}},
        "binding_resolved": True,
        "resolved": {"source_kind": source, "label": label, "source_keyframe_index": source_index,
                     "url": "/api/files/actual-resolved.png", "sha256": sha, "size": len(PAYLOAD)},
        "binding": {"picture_index": 1, "node_id": "76", "field": "image", "output_slot": 0,
                    "uploaded_filename": "references/server-renamed.png", "payload_sha256": sha, "payload_size": len(PAYLOAD)},
    }


@pytest.mark.parametrize("source,label,source_index", SOURCES)
def test_task_and_user_reference_projections_derive_only_from_actual_binding(source, label, source_index):
    contract = _bound_contract(source, label, source_index)
    contract["manifest"] = [{"picture_index": 2, "type": "CHARACTER", "label": "stale asset"}]
    contract["fallback"] = {"from": "PREVIOUS_KEYFRAME", "to": source, "reason": "PREVIOUS_IMAGE_NOT_READY"}
    task = SimpleNamespace(metadata_json=json.dumps({gate.CONTRACT_KEY: contract, "user_notes": "keep"}))
    saved = gate.read_contract(task)
    before = deepcopy(saved)
    manifest = gate.reference_manifest(saved)
    images = gate.reference_images(saved)
    assert manifest == [{"picture_index": 1, "type": source, "role": "EDIT_BASE", "label": label,
                         "source_keyframe_index": source_index}]
    assert images == [{"label": label, "url": "/api/files/actual-resolved.png"}]
    assert saved["binding"]["payload_sha256"] == saved["resolved"]["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert gate.digest(PAYLOAD) == hashlib.sha256(PAYLOAD).hexdigest()
    assert saved == before
    manifest[0]["label"] = images[0]["label"] = "caller edit"
    saved["resolved"]["label"] = "caller edit"
    assert gate.read_contract(task) == before


@pytest.mark.parametrize("projection", ["reference_manifest", "reference_images"])
@pytest.mark.parametrize("change", ["missing-flag", "false-flag", "no-binding", "wrong-hash", "missing-hash", "both-hashes-missing", "no-filename"])
def test_no_picture_number_or_projection_before_verified_binding(projection, change):
    contract = _bound_contract()
    contract["manifest"] = [{"picture_index": 1, "label": "unverified planned image"}]
    if change == "missing-flag":
        contract.pop("binding_resolved")
    elif change == "false-flag":
        contract["binding_resolved"] = False
    elif change == "no-binding":
        contract["binding"] = None
    elif change == "wrong-hash":
        contract["resolved"]["sha256"] = hashlib.sha256(b"different resolved payload").hexdigest()
    elif change in {"missing-hash", "both-hashes-missing"}:
        contract["binding"].pop("payload_sha256")
        if change == "both-hashes-missing":
            contract["resolved"].pop("sha256")
    else:
        contract["binding"]["uploaded_filename"] = ""
    before = deepcopy(contract)
    with pytest.raises(gate.KeyframeReferenceError, match="REFERENCE_NOT_BOUND"):
        getattr(gate, projection)(contract)
    assert contract == before


@pytest.mark.parametrize("sha", [None, "", "abc", "f" * 63, "f" * 65, "g" * 64, "f" * 64 + "\n", 64, True, [], {}])
def test_matching_payload_hashes_must_be_actual_sha256_strings(sha):
    contract = _bound_contract()
    contract["resolved"]["sha256"] = contract["binding"]["payload_sha256"] = sha
    for projection in (gate.reference_manifest, gate.reference_images):
        with pytest.raises(gate.KeyframeReferenceError, match="REFERENCE_NOT_BOUND"):
            projection(contract)


def test_none_manifest_is_empty_only_after_explicit_none_resolution():
    contract = _bound_contract()
    contract.update(resolved=None, binding=None, binding_resolved=False)
    contract["planned"]["intent"] = {"mode": "none", "url": None}
    with pytest.raises(gate.KeyframeReferenceError, match="REFERENCE_NOT_BOUND"):
        gate.reference_manifest(contract)
    contract["binding_resolved"] = True
    assert gate.reference_manifest(contract) == gate.reference_images(contract) == []
    contract["binding"] = _bound_contract()["binding"]
    with pytest.raises(gate.KeyframeReferenceError, match="BINDING_MISMATCH"):
        gate.reference_images(contract)
    contract["binding"] = None
    contract["planned"]["intent"]["mode"] = "auto_select"
    with pytest.raises(gate.KeyframeReferenceError, match="BINDING_MISMATCH"):
        gate.reference_manifest(contract)


@pytest.mark.parametrize("frame,selection", [
    ({}, "dynamic_auto"), ({"reference_mode": "none", "reference_image_url": "/stale.png"}, "none"),
    ({"reference_mode": "custom", "reference_image_url": "/custom.png"}, "custom"),
    ({"reference_mode": "auto_select", "reference_image_url": "/saved.png"}, "fixed_auto"),
])
def test_reference_intent_distinguishes_dynamic_custom_fixed_and_none(frame, selection):
    before = deepcopy(frame)
    assert gate.reference_intent(frame)["selection"] == selection
    assert frame == before


@pytest.mark.parametrize("frame", [
    {"reference_mode": "unknown"}, {"reference_mode": "custom"}, {"reference_mode": "custom", "reference_image_url": ""},
    {"reference_image_url": 4}, {"reference_image_url": False},
])
def test_invalid_reference_intents_reject(frame):
    with pytest.raises(gate.KeyframeReferenceError):
        gate.reference_intent(frame)


@pytest.mark.parametrize("metadata", [None, "", "{}", {gate.CONTRACT_KEY: {}}, {gate.CONTRACT_KEY: {"version": -1}}])
def test_missing_or_unknown_saved_contract_does_not_become_current(metadata):
    assert gate.read_contract(SimpleNamespace(metadata_json=metadata)) is None


@pytest.mark.parametrize("metadata", ["{broken", "[]", "null", 4])
def test_malformed_saved_task_json_rejects(metadata):
    with pytest.raises(gate.KeyframeReferenceError):
        gate.read_contract(SimpleNamespace(metadata_json=metadata))


@pytest.fixture
def state(isolation):
    base = declarative_base()
    isolation.stub("app.core.database", Base=base, SessionLocal=isolation.forbidden)

    class Chapter(base):
        __tablename__ = "chapters"
        id = Column(String, primary_key=True)
        shots = relationship("Shot", back_populates="chapter")

    Shot = isolation.load("app.models.shot", "app/models/shot.py").Shot
    Task = isolation.load("app.models.task", "app/models/task.py").Task
    engine = create_engine("sqlite:///:memory:")
    base.metadata.create_all(engine)
    with Session(engine) as db:
        frames = [
            {"frame_index": 0, "plan_keyframe_index": 2, "role": "INTERMEDIATE", "time_seconds": 1,
             "description": "Ada waits at the gate.", "image_url": "/previous.png", "image_task_id": "previous-producer"},
            {"frame_index": 1, "plan_keyframe_index": 3, "role": "INTERMEDIATE", "time_seconds": 2,
             "description": "Legacy target description", "reference_mode": "auto_select", "prompt_text": "old draft",
             "image_url": "/old-legacy.png", "image_task_id": "legacy-producer"},
            {"frame_index": 2, "plan_keyframe_index": 4, "role": "END", "time_seconds": 4,
             "description": "The gate closes.", "image_url": "/unrelated.png"},
        ]
        plan = {"selected_mode": "MULTI_KEYFRAME", "keyframes": [
            {"index": 1, "role": "START", "time_seconds": 0, "description": "Primary state", "image_url": "/primary.png"},
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 1, "description": "Ada waits at the gate."},
            {"index": 3, "role": "INTERMEDIATE", "time_seconds": 2, "description": "Ada raises her hand.",
             "prompt_text": "old draft", "image_url": "/old-formal.png", "image_task_id": "formal-producer"},
            {"index": 4, "role": "END", "time_seconds": 4, "description": "The gate closes."},
        ], "window_plans": [{"window_index": 1, "user_note": "keep window edit"}], "ai_calls": []}
        shot = Shot(id="shot-17", chapter_id="chapter", index=17, description="Two people by a gate.",
                    video_description="Ada opens the gate.", scene="courtyard", characters='["Ada", "Bea"]',
                    props='["sword"]', dialogues="[]", duration=4, continuity_mode="NORMAL", image_url="/primary.png",
                    keyframes=json.dumps(frames), video_director_plan=json.dumps(plan), video_director_plan_revision=7)
        task = Task(id="task-17", name="Keyframe Slot 17", type="keyframe_image", status="pending", novel_id="novel",
                    chapter_id="chapter", shot_id=shot.id, parent_task_id=None, prompt_text=None,
                    result_url="/old-task-result.png", current_step="Pending", progress=0, reference_images="[]")
        target = gate.snapshot_target(shot, 1)
        contract = {"version": gate.CONTRACT_VERSION, "attempt_id": "attempt-17", "phase": "planned",
                    "target": target, "draft": deepcopy(target["draft"]),
                    "planned": {"novel_id": "novel", "parent_task_id": None, "requested_workflow_id": None,
                                "intent": target["reference_intent"]},
                    "binding_resolved": False, "resolved": None, "binding": None,
                    "prompt": {"llm_invoked": False}, "submit": {"state": "not_submitted"}}
        gate.seal_contract(contract)
        task.metadata_json = json.dumps({gate.CONTRACT_KEY: contract, "unrelated": {"keep": True}})
        db.add_all([Chapter(id="chapter"), shot, task])
        db.commit()

        def append_local_call(local_shot, call):
            value = gate.json_value(local_shot.video_director_plan, dict)
            value.setdefault("ai_calls", []).append(deepcopy(call))
            return value

        append = Mock(side_effect=append_local_call)
        isolation.stub("app.services.video_director_ai", append_video_ai_call=append)
        yield SimpleNamespace(db=db, engine=engine, Shot=Shot, Task=Task, shot=shot, task=task, contract=contract, append=append)
    engine.dispose()


def _records(state):
    return {name: dict(state.db.execute(model.__table__.select()).mappings().one())
            for name, model in (("shot", state.Shot), ("task", state.Task))}


def _activate(state):
    assert gate.patch_target(state.db, state.task.id, state.contract, claiming=True) is True
    assert gate.store_contract(state.db, state.task.id, state.contract, statuses=("pending",), status="running") is True


@pytest.mark.parametrize("index", [-1, -20, 3, True, False, 1.0, "1", None])
def test_target_snapshot_rejects_negative_out_of_range_and_noninteger_frames(state, index):
    with pytest.raises(gate.KeyframeReferenceError, match="TARGET_NOT_FOUND"):
        gate.snapshot_target(state.shot, index)


@pytest.mark.parametrize("change,code", [
    ("duplicate-target", "PLAN_TARGET_NOT_UNIQUE"), ("missing-target", "PLAN_TARGET_NOT_UNIQUE"),
    ("duplicate-previous", "PREVIOUS_PLAN_NOT_UNIQUE"), ("start-target", "START_USES_PRIMARY_STORYBOARD"),
    ("invalid-target", "TARGET_NOT_FOUND"), ("invalid-previous", "INVALID_PREVIOUS_STATE"),
])
def test_snapshot_requires_one_formal_keyframe_and_valid_previous_state(state, change, code):
    frames, plan = json.loads(state.shot.keyframes), json.loads(state.shot.video_director_plan)
    if change == "duplicate-target":
        plan["keyframes"].append(deepcopy(plan["keyframes"][2]))
    elif change == "duplicate-previous":
        plan["keyframes"].append(deepcopy(plan["keyframes"][1]))
    elif change == "missing-target":
        plan["keyframes"].pop(2)
    elif change == "start-target":
        plan["keyframes"][2]["role"] = "START"
    else:
        frames[1 if change == "invalid-target" else 0] = None
    state.shot.keyframes, state.shot.video_director_plan = json.dumps(frames), json.dumps(plan)
    with pytest.raises(gate.KeyframeReferenceError, match=code):
        gate.snapshot_target(state.shot, 1)


def test_snapshot_separates_formal_state_previous_text_draft_and_old_image_provenance(state):
    target = gate.snapshot_target(state.shot, 1)
    assert target["current_state"] == {"index": 3, "role": "INTERMEDIATE", "time_seconds": 2, "description": "Ada raises her hand."}
    assert target["legacy_state"]["description"] == "Legacy target description"
    assert target["previous_state_text"] == {"index": 2, "role": "INTERMEDIATE", "time_seconds": 1, "description": "Ada waits at the gate."}
    assert target["images"] == {"legacy": "/old-legacy.png", "plan": "/old-formal.png"}
    assert target["owners"] == {"legacy": "legacy-producer", "plan": "formal-producer"}
    assert target["draft"] == {key: {"present": True, "value": "old draft"} for key in ("legacy", "plan")}
    assert not {"images", "owners", "draft"} & gate.target_semantics(target).keys()
    target["shot_state"]["characters"].append("caller edit")
    assert json.loads(state.shot.characters) == ["Ada", "Bea"]


def test_initial_claim_changes_both_owners_but_preserves_old_image_provenance(state):
    before, original_contract = _records(state), deepcopy(state.contract)
    assert gate.patch_target(state.db, state.task.id, state.contract, claiming=True) is True
    after = _records(state)
    frames, plan = json.loads(after["shot"]["keyframes"]), json.loads(after["shot"]["video_director_plan"])
    assert frames[1]["image_task_id"] == plan["keyframes"][2]["image_task_id"] == state.task.id
    assert frames[1]["image_url"] == "/old-legacy.png" and plan["keyframes"][2]["image_url"] == "/old-formal.png"
    assert frames[1]["prompt_text"] == plan["keyframes"][2]["prompt_text"] == "old draft"
    assert state.contract == gate.read_contract(state.task)
    assert state.contract["storage_revision"] == original_contract["storage_revision"] + 1
    assert state.contract["storage_hash"] != original_contract["storage_hash"]
    assert {key: value for key, value in state.contract.items() if not key.startswith("storage_")} == {
        key: value for key, value in original_contract.items() if not key.startswith("storage_")
    }
    assert after["task"]["status"] == "pending" and after["task"]["result_url"] == before["task"]["result_url"]
    assert after["shot"]["video_director_plan_revision"] == before["shot"]["video_director_plan_revision"] + 1
    gate.assert_target(state.shot, state.task.id, state.contract)
    with pytest.raises(gate.KeyframeReferenceError, match="TARGET_OWNER_CHANGED"):
        gate.patch_target(state.db, state.task.id, state.contract, claiming=True)


def test_legacy_only_first_frame_claim_and_publication_do_not_invent_a_formal_target(state):
    frame = json.loads(state.shot.keyframes)[1]
    frame.pop("plan_keyframe_index")
    frame["frame_index"] = 0
    state.shot.keyframes = json.dumps([frame])
    target = gate.snapshot_target(state.shot, 0)
    assert target["plan_keyframe_index"] is target["previous_state_text"] is None
    assert target["draft"]["plan"] == {"present": False, "value": None}
    state.contract.update(target=target, draft=deepcopy(target["draft"]))
    gate.seal_contract(state.contract)
    metadata = json.loads(state.task.metadata_json)
    metadata[gate.CONTRACT_KEY] = state.contract
    state.task.metadata_json = json.dumps(metadata)
    state.db.commit()
    old_plan, old_revision = state.shot.video_director_plan, state.shot.video_director_plan_revision
    _activate(state)
    assert gate.patch_target(state.db, state.task.id, state.contract, prompt=PRIMARY, image_url="/legacy-new.png") is True
    frame = json.loads(state.shot.keyframes)[0]
    assert frame["prompt_text"] == state.task.prompt_text == PRIMARY
    assert frame["image_url"] == state.task.result_url == "/legacy-new.png"
    assert frame["image_task_id"] == state.task.id
    assert state.shot.video_director_plan == old_plan and state.shot.video_director_plan_revision == old_revision
    assert state.contract["draft"]["plan"] == {"present": False, "value": None}


@pytest.mark.parametrize("operation", ["claim", "prompt", "image"])
@pytest.mark.parametrize("change,code", [
    ("description", "TARGET_CHANGED"), ("previous-description", "TARGET_CHANGED"),
    ("reorder", "TARGET_CHANGED"), ("formal-description", "TARGET_CHANGED"), ("formal-time", "TARGET_CHANGED"),
    ("reference", "TARGET_CHANGED"), ("legacy-image", "TARGET_CHANGED"), ("formal-image", "TARGET_CHANGED"),
    ("legacy-owner", "TARGET_OWNER_CHANGED"), ("formal-owner", "TARGET_OWNER_CHANGED"),
    ("legacy-draft", "PROMPT_EDITED"), ("formal-draft", "PROMPT_EDITED"), ("draft-removed", "PROMPT_EDITED"),
])
def test_target_edits_reorder_owner_and_draft_changes_veto_publication(state, operation, change, code):
    if operation != "claim":
        _activate(state)
    with Session(state.engine) as editor:
        shot = editor.get(state.Shot, state.shot.id)
        frames, plan = json.loads(shot.keyframes), json.loads(shot.video_director_plan)
        if change == "description":
            shot.description = "new user direction"
        elif change == "previous-description":
            plan["keyframes"][1]["description"] = "new previous planning state"
        elif change == "reorder":
            frames[0], frames[1] = frames[1], frames[0]
        elif change in {"formal-description", "formal-time"}:
            field = "description" if change == "formal-description" else "time_seconds"
            plan["keyframes"][2][field] = "changed" if field == "description" else 3
        elif change == "reference":
            frames[1].update(reference_mode="custom", reference_image_url="/user-reference.png")
        elif change == "draft-removed":
            plan["keyframes"][2].pop("prompt_text")
        else:
            representation, field = change.split("-")
            item = frames[1] if representation == "legacy" else plan["keyframes"][2]
            item[{"image": "image_url", "owner": "image_task_id", "draft": "prompt_text"}[field]] = "new user edit"
        shot.keyframes, shot.video_director_plan = json.dumps(frames), json.dumps(plan)
        shot.video_director_plan_revision += 1
        editor.commit()
    before, contract_before = _records(state), deepcopy(state.contract)
    options = {"claiming": True} if operation == "claim" else {"prompt": PRIMARY} if operation == "prompt" else {"image_url": "/new.png"}
    with pytest.raises(gate.KeyframeReferenceError, match=code):
        gate.patch_target(state.db, state.task.id, state.contract, **options)
    assert _records(state) == before and state.contract == contract_before


def test_unrelated_plan_progress_logs_other_frames_and_metadata_edits_survive(state):
    _activate(state)
    with Session(state.engine) as editor:
        shot, task = editor.get(state.Shot, state.shot.id), editor.get(state.Task, state.task.id)
        plan = json.loads(shot.video_director_plan)
        plan["window_plans"][0].update(status="RUNNING", user_note="new parallel note")
        plan["keyframes"][-1]["description"] = "unrelated frame edit"
        plan["ai_calls"].append({"step": "08", "note": "parallel log"})
        shot.video_director_plan = json.dumps(plan)
        shot.video_director_plan_revision += 1
        task.metadata_json = json.dumps({**json.loads(task.metadata_json), "parallel": {"note": "keep"}})
        task.progress = 41
        editor.commit()
    revision = _records(state)["shot"]["video_director_plan_revision"]
    call = {"step": "09", "final_prompt": PRIMARY}
    assert gate.patch_target(state.db, state.task.id, state.contract, prompt=PRIMARY, ai_call=call) is True
    plan = json.loads(state.shot.video_director_plan)
    assert plan["window_plans"][0] == {"window_index": 1, "status": "RUNNING", "user_note": "new parallel note"}
    assert plan["keyframes"][-1]["description"] == "unrelated frame edit"
    assert plan["ai_calls"] == [{"step": "08", "note": "parallel log"}, call]
    assert state.shot.video_director_plan_revision == revision + 1
    metadata = json.loads(state.task.metadata_json)
    assert metadata["parallel"] == {"note": "keep"} and metadata["unrelated"] == {"keep": True}
    assert state.task.progress == 41
    state.append.assert_called_once()


def test_prompt_and_image_publications_atomically_update_both_representations_and_task(state, monkeypatch):
    _activate(state)
    commits = []
    commit = state.db.commit

    def record_commit():
        commits.append(_records(state))
        commit()

    monkeypatch.setattr(state.db, "commit", record_commit)
    state.contract.update(phase="prompt_ready", prompt={"text": PRIMARY, "text_hash": gate.digest(PRIMARY),
                                                       "validation": gate.validate_reference_prompt(PRIMARY, "PRIMARY_STORYBOARD")})
    assert gate.patch_target(state.db, state.task.id, state.contract, prompt=PRIMARY, ai_call={"step": "09"}) is True
    assert len(commits) == 1
    prompt_commit = commits[0]
    frames, plan = json.loads(prompt_commit["shot"]["keyframes"]), json.loads(prompt_commit["shot"]["video_director_plan"])
    assert frames[1]["prompt_text"] == plan["keyframes"][2]["prompt_text"] == prompt_commit["task"]["prompt_text"] == PRIMARY
    assert frames[1]["image_url"] == "/old-legacy.png" and plan["keyframes"][2]["image_url"] == "/old-formal.png"
    assert json.loads(prompt_commit["task"]["metadata_json"])[gate.CONTRACT_KEY] == state.contract
    assert state.contract["draft"] == {key: {"present": True, "value": PRIMARY} for key in ("legacy", "plan")}
    gate.assert_target(state.shot, state.task.id, state.contract)
    assert gate.patch_target(state.db, state.task.id, state.contract, image_url="/generated.png") is True
    assert len(commits) == 2
    image_commit = commits[1]
    frames, plan = json.loads(image_commit["shot"]["keyframes"]), json.loads(image_commit["shot"]["video_director_plan"])
    assert frames[1]["image_url"] == plan["keyframes"][2]["image_url"] == image_commit["task"]["result_url"] == "/generated.png"
    assert frames[1]["image_task_id"] == plan["keyframes"][2]["image_task_id"] == state.task.id
    assert frames[1]["description"] == plan["keyframes"][2]["description"] == "Ada raises her hand."
    assert image_commit["task"]["status"] == "completed" and image_commit["task"]["progress"] == 100
    assert image_commit["task"]["completed_at"] is not None and image_commit["task"]["error_message"] is None
    assert state.contract["phase"] == "completed" and state.contract["result"] == {"url": "/generated.png", "attachment": "attached"}
    assert json.loads(image_commit["task"]["metadata_json"])[gate.CONTRACT_KEY] == state.contract


@pytest.mark.parametrize("failures", [1, 3], ids=["retry-success", "exhausted"])
@pytest.mark.parametrize("operation", ["claim", "prompt", "image"])
def test_second_task_cas_failure_rolls_back_first_shot_write_and_local_evidence(state, monkeypatch, failures, operation):
    if operation != "claim":
        _activate(state)
    before, contract_before = _records(state), deepcopy(state.contract)
    update, rollback = Query.update, state.db.rollback
    events, rolled_back = [], []
    remaining = failures

    def fail_task_cas(query, values, *args, **kwargs):
        nonlocal remaining
        model = query.column_descriptions[0]["entity"]
        events.append(model.__name__)
        if model is state.Task and remaining:
            remaining -= 1
            assert _records(state)["shot"] != before["shot"], "The first CAS must have executed real SQL"
            return 0
        return update(query, values, *args, **kwargs)

    def check_rollback():
        rollback()
        rolled_back.append(_records(state))
        assert rolled_back[-1] == before
        assert state.contract == contract_before

    monkeypatch.setattr(Query, "update", fail_task_cas)
    monkeypatch.setattr(state.db, "rollback", check_rollback)
    options = {"claiming": True} if operation == "claim" else {"prompt": PRIMARY, "ai_call": {"step": "09"}} if operation == "prompt" else {"image_url": "/new.png"}
    if failures == 3:
        with pytest.raises(gate.KeyframeReferenceError, match="TARGET_WRITE_CONFLICT"):
            gate.patch_target(state.db, state.task.id, state.contract, **options)
        assert _records(state) == before and state.contract == contract_before
    else:
        assert gate.patch_target(state.db, state.task.id, state.contract, **options) is True
        assert _records(state) != before
        assert gate.read_contract(state.task) == state.contract
        if operation == "prompt":
            assert json.loads(state.shot.video_director_plan)["ai_calls"] == [{"step": "09"}]
    assert len(rolled_back) == failures
    assert events == ["Shot", "Task"] * (2 if failures == 1 else 3)


def test_failed_first_shot_cas_never_writes_task(state, monkeypatch):
    _activate(state)
    before = _records(state)
    calls = []

    def conflict(query, values, *args, **kwargs):
        calls.append(query.column_descriptions[0]["entity"])
        return 0

    monkeypatch.setattr(Query, "update", conflict)
    with pytest.raises(gate.KeyframeReferenceError, match="TARGET_WRITE_CONFLICT"):
        gate.patch_target(state.db, state.task.id, state.contract, prompt=PRIMARY)
    assert calls == [state.Shot] * 3 and _records(state) == before


@pytest.mark.parametrize("change", ["cancel", "attempt", "unrelated-plan"])
def test_real_sql_cas_detects_edits_between_snapshot_and_first_write(state, monkeypatch, change):
    _activate(state)
    before, contract_before = _records(state), deepcopy(state.contract)
    task_id, shot_id = state.task.id, state.shot.id
    update, events = Query.update, []
    interleaved = False

    def concurrent_edit(query, values, *args, **kwargs):
        nonlocal interleaved
        model = query.column_descriptions[0]["entity"]
        if model is state.Shot and not interleaved:
            interleaved = True
            # Interleave before any UPDATE, not inside an uncommitted Shot write.
            with Session(state.engine) as editor:
                if change == "unrelated-plan":
                    shot = editor.get(state.Shot, shot_id)
                    plan = json.loads(shot.video_director_plan)
                    plan["window_plans"][0]["user_note"] = "committed during CAS"
                    shot.video_director_plan = json.dumps(plan)
                    shot.video_director_plan_revision += 1
                else:
                    task = editor.get(state.Task, task_id)
                    if change == "cancel":
                        task.status = "cancelled"
                    else:
                        metadata = json.loads(task.metadata_json)
                        metadata[gate.CONTRACT_KEY]["attempt_id"] = "new-owner-attempt"
                        task.metadata_json = json.dumps(metadata)
                editor.commit()
        count = update(query, values, *args, **kwargs)
        events.append((model.__name__, count))
        return count

    monkeypatch.setattr(Query, "update", concurrent_edit)
    if change == "unrelated-plan":
        assert gate.patch_target(state.db, task_id, state.contract, prompt=PRIMARY) is True
        assert events == [("Shot", 0), ("Shot", 1), ("Task", 1)]
        assert json.loads(state.shot.video_director_plan)["window_plans"][0]["user_note"] == "committed during CAS"
        assert state.shot.video_director_plan_revision == before["shot"]["video_director_plan_revision"] + 2
    else:
        code = "TASK_NOT_ACTIVE" if change == "cancel" else "TASK_REPLACED"
        with pytest.raises(gate.KeyframeReferenceError, match=code):
            gate.patch_target(state.db, task_id, state.contract, prompt=PRIMARY, image_url="/late.png")
        assert events == [("Shot", 1), ("Task", 0)]
        assert _records(state)["shot"] == before["shot"] and state.contract == contract_before
        assert state.task.prompt_text is None and state.task.result_url == "/old-task-result.png"
        if change == "cancel":
            assert state.task.status == "cancelled"
        else:
            assert gate.read_contract(state.task)["attempt_id"] == "new-owner-attempt"


@pytest.mark.parametrize("change", ["shot_id", "chapter_id", "novel_id", "parent_task_id", "attempt", "type", "removed-contract"])
def test_task_identity_and_attempt_replacement_veto_writes(state, change):
    _activate(state)
    if change in {"attempt", "removed-contract"}:
        metadata = json.loads(state.task.metadata_json)
        if change == "attempt":
            metadata[gate.CONTRACT_KEY]["attempt_id"] = "replacement"
        else:
            metadata.pop(gate.CONTRACT_KEY)
        state.task.metadata_json = json.dumps(metadata)
    else:
        setattr(state.task, change, "replacement")
    state.db.commit()
    before = _records(state)
    with pytest.raises(gate.KeyframeReferenceError, match="TASK_REPLACED|TASK_NOT_ACTIVE"):
        gate.patch_target(state.db, state.task.id, state.contract, prompt=PRIMARY)
    assert _records(state) == before


@pytest.mark.parametrize("removed", ["shot", "task"])
def test_deleted_task_or_target_is_not_recreated_by_late_publication(state, removed):
    _activate(state)
    task_id = state.task.id
    state.db.delete(getattr(state, removed))
    state.db.commit()
    code = "TARGET_NOT_FOUND" if removed == "shot" else "TASK_REMOVED"
    with pytest.raises(gate.KeyframeReferenceError, match=code):
        gate.patch_target(state.db, task_id, state.contract, image_url="/late.png")
    if removed == "task":
        with pytest.raises(gate.KeyframeReferenceError, match="TASK_REMOVED"):
            gate.store_contract(state.db, task_id, state.contract, terminal=True, result_url="/late.png")
    model = state.Shot if removed == "shot" else state.Task
    assert state.db.query(model).count() == 0


@pytest.mark.parametrize("parent_status", ["pending", "running", "cancelled", "failed", "completed", None])
def test_parent_must_still_be_active(state, parent_status):
    _activate(state)
    state.task.parent_task_id = state.contract["planned"]["parent_task_id"] = "parent"
    gate.seal_contract(state.contract)
    metadata = json.loads(state.task.metadata_json)
    metadata[gate.CONTRACT_KEY] = state.contract
    state.task.metadata_json = json.dumps(metadata)
    if parent_status is not None:
        state.db.add(state.Task(id="parent", name="Parent", type="keyframe_batch", status=parent_status))
    state.db.commit()
    if parent_status in {"pending", "running"}:
        gate.assert_task_active(state.db, state.task, state.contract)
    else:
        with pytest.raises(gate.KeyframeReferenceError, match="PARENT_NOT_ACTIVE"):
            gate.assert_task_active(state.db, state.task, state.contract)


@pytest.mark.parametrize("status", ["cancelled", "failed"])
def test_terminal_tasks_are_not_resurrected_by_publication_or_error_evidence(state, status):
    _activate(state)
    state.task.status, state.task.progress, state.task.current_step = status, 37, "user stopped"
    state.db.commit()
    before = _records(state)
    for options in ({"prompt": PRIMARY}, {"image_url": "/late.png"}):
        with pytest.raises(gate.KeyframeReferenceError, match="TASK_NOT_ACTIVE"):
            gate.patch_target(state.db, state.task.id, state.contract, **options)
    with pytest.raises(gate.KeyframeReferenceError, match="TASK_NOT_ACTIVE"):
        gate.store_contract(state.db, state.task.id, state.contract, status="running")
    assert _records(state) == before
    state.contract.update(phase="failed", result={"url": "/late.png", "attachment": "detached"})
    with pytest.raises(gate.KeyframeReferenceError, match="TASK_SUBMISSION_CHANGED"):
        gate.store_contract(state.db, state.task.id, state.contract, terminal=True, comfyui_prompt_id="unproven-ack")
    assert gate.store_contract(state.db, state.task.id, state.contract, terminal=True, status="completed", progress=100,
                               current_step="Completed", result_url="/late.png") is True
    after = _records(state)
    assert after["shot"] == before["shot"]
    assert after["task"]["status"] == status and after["task"]["progress"] == 37
    assert after["task"]["current_step"] == "user stopped"
    assert after["task"]["result_url"] == "/late.png" and after["task"]["comfyui_prompt_id"] is None
    assert gate.read_contract(state.task)["result"]["attachment"] == "detached"


def test_completed_attachment_is_idempotent_and_late_error_cannot_overwrite_it(state, monkeypatch):
    _activate(state)
    assert gate.patch_target(state.db, state.task.id, state.contract, prompt=PRIMARY, image_url="/completed.png") is True
    before, contract_before = _records(state), deepcopy(state.contract)
    commit = Mock(wraps=state.db.commit)
    monkeypatch.setattr(state.db, "commit", commit)
    assert gate.patch_target(state.db, state.task.id, state.contract, image_url="/completed.png") is False
    late = deepcopy(state.contract)
    late.update(phase="failed", result={"url": "/late.png", "attachment": "detached"})
    assert gate.store_contract(state.db, state.task.id, late, terminal=True, status="failed", result_url="/late.png") is False
    assert _records(state) == before and state.contract == contract_before
    commit.assert_not_called()


@pytest.mark.parametrize("failures", [1, 3])
def test_store_contract_metadata_cas_retries_without_losing_other_namespaces(state, monkeypatch, failures):
    _activate(state)
    before = _records(state)
    update, calls = Query.update, []

    def conflict(query, values, *args, **kwargs):
        calls.append(deepcopy(values))
        return 0 if len(calls) <= failures else update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", conflict)
    state.contract["phase"] = "resolved"
    if failures == 3:
        with pytest.raises(gate.KeyframeReferenceError, match="TASK_WRITE_CONFLICT"):
            gate.store_contract(state.db, state.task.id, state.contract, progress=25)
        assert _records(state) == before
    else:
        assert gate.store_contract(state.db, state.task.id, state.contract, progress=25) is True
        assert gate.read_contract(state.task) == state.contract and state.task.progress == 25
        assert json.loads(state.task.metadata_json)["unrelated"] == {"keep": True}
        assert _records(state)["shot"] == before["shot"]
    assert len(calls) == (2 if failures == 1 else 3)


def test_seal_is_canonical_initial_zero_and_advances_only_after_committed_writes(state):
    initial = deepcopy(state.contract)
    unsigned = {key: value for key, value in initial.items() if key != "storage_hash"}
    expected = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert initial["storage_revision"] == 0 and initial["storage_hash"] == expected
    reordered = dict(reversed(list(initial.items())))
    assert gate.seal_contract(reordered) is reordered and reordered == initial
    _activate(state)
    assert state.contract["storage_revision"] == 2
    stored = deepcopy(state.contract)
    state.contract["phase"] = "locally-staged"
    gate.assert_task_active(state.db, state.task, state.contract)
    assert (state.contract["storage_revision"], state.contract["storage_hash"]) == (stored["storage_revision"], stored["storage_hash"])
    assert gate.store_contract(state.db, state.task.id, state.contract, progress=12) is True
    assert state.contract["storage_revision"] == 3 and state.contract == gate.read_contract(state.task)
    assert state.contract["storage_hash"] != stored["storage_hash"]


@pytest.mark.parametrize("operation", ["store", "patch", "observe"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_sql_exception_after_task_update_rolls_back_all_rows_and_keeps_working_token(state, monkeypatch, operation, error_type):
    _activate(state)
    before, working, update = _records(state), deepcopy(state.contract), Query.update

    def fail(query, values, *args, **kwargs):
        count = update(query, values, *args, **kwargs)
        if query.column_descriptions[0]["entity"] is state.Task:
            assert count == 1 and _records(state)["task"] != before["task"]
            raise error_type("interrupted Task CAS")
        return count

    monkeypatch.setattr(Query, "update", fail)
    with pytest.raises(error_type, match="interrupted Task CAS"):
        if operation == "patch":
            gate.patch_target(state.db, state.task.id, state.contract, prompt=PRIMARY, image_url="/late.png")
        elif operation == "store":
            gate.store_contract(state.db, state.task.id, state.contract, progress=55)
        else:
            gate.record_contract_observation(state.db, state.task.id, state.contract, RuntimeError("earlier error"))
    assert _records(state) == before and state.contract == working


@pytest.mark.parametrize("change", ["missing-seal", "missing-revision", "bad-revision", "tampered-body", "malformed-json", "no-contract"])
def test_initial_claim_requires_a_valid_persisted_seal(state, change):
    metadata = json.loads(state.task.metadata_json)
    saved = metadata[gate.CONTRACT_KEY]
    if change == "missing-seal":
        saved.pop("storage_hash")
    elif change == "missing-revision":
        saved.pop("storage_revision")
    elif change == "bad-revision":
        saved["storage_revision"] = True
    elif change == "tampered-body":
        saved["phase"] = "tampered"
    elif change == "no-contract":
        metadata.pop(gate.CONTRACT_KEY)
    state.task.metadata_json = "{broken" if change == "malformed-json" else json.dumps(metadata)
    state.db.commit()
    before = _records(state)
    with pytest.raises(gate.KeyframeReferenceError):
        gate.patch_target(state.db, state.task.id, state.contract, claiming=True)
    assert _records(state) == before


def test_staged_workflow_selection_compares_task_with_stored_not_new_local_workflow(state):
    _activate(state)
    old_hash = state.contract["storage_hash"]
    state.contract.update(phase="workflow_selected", workflow={"id": "chosen", "name": "Frozen name"})
    gate.assert_task_active(state.db, state.task, state.contract)
    assert state.task.workflow_id is state.task.workflow_name is None
    assert gate.store_contract(state.db, state.task.id, state.contract, workflow_id="chosen", workflow_name="Frozen name") is True
    assert state.task.workflow_id == "chosen" and state.task.workflow_name == "Frozen name"
    assert state.contract["storage_hash"] != old_hash
    gate.assert_task_active(state.db, state.task, state.contract)


@pytest.mark.parametrize("operation", ["prompt", "image"])
@pytest.mark.parametrize("field,value", [
    ("description", "new direction"), ("video_description", "new action"), ("scene", "other courtyard"),
    ("characters", '["Bea"]'), ("props", '["shield"]'), ("dialogues", '[{"text":"new dialogue"}]'),
    ("duration", 9), ("continuity_mode", "CONTINUOUS_TAKE"), ("chapter_id", "other-chapter"),
])
def test_shot_context_column_race_is_in_the_actual_sql_cas(state, monkeypatch, operation, field, value):
    _activate(state)
    before, working = _records(state), deepcopy(state.contract)
    shot_id, update, events = state.shot.id, Query.update, []
    edited = False

    def race(query, values, *args, **kwargs):
        nonlocal edited
        model = query.column_descriptions[0]["entity"]
        if model is state.Shot and not edited:
            edited = True
            with Session(state.engine) as editor:
                setattr(editor.get(state.Shot, shot_id), field, value)
                editor.commit()
        count = update(query, values, *args, **kwargs)
        events.append((model.__name__, count))
        return count

    monkeypatch.setattr(Query, "update", race)
    with pytest.raises(gate.KeyframeReferenceError, match="TARGET_CHANGED"):
        gate.patch_target(state.db, state.task.id, state.contract, **({"prompt": PRIMARY} if operation == "prompt" else {"image_url": "/late.png"}))
    after = _records(state)
    assert after["shot"][field] == value and after["task"] == before["task"]
    for key in ("keyframes", "video_director_plan", "video_director_plan_revision"):
        assert after["shot"][key] == before["shot"][key]
    assert events == [("Shot", 0)] and state.contract == working


@pytest.mark.parametrize("operation", ["store", "patch"])
@pytest.mark.parametrize("field,value", [
    ("comfyui_prompt_id", "external-cid"), ("prompt_text", "external prompt"),
    ("reference_images", '[{"label":"external","url":"/external.png"}]'),
    ("workflow_id", "external-workflow"), ("workflow_name", "external name"), ("workflow_json", "{}"),
])
def test_task_projection_race_cannot_restore_old_data_or_complete_an_image(state, monkeypatch, operation, field, value):
    _activate(state)
    before, working = _records(state), deepcopy(state.contract)
    task_id, update, events = state.task.id, Query.update, []
    edited = False

    def race(query, values, *args, **kwargs):
        nonlocal edited
        model = query.column_descriptions[0]["entity"]
        if not edited:
            edited = True
            with Session(state.engine) as editor:
                setattr(editor.get(state.Task, task_id), field, value)
                editor.commit()
        count = update(query, values, *args, **kwargs)
        events.append((model.__name__, count))
        return count

    monkeypatch.setattr(Query, "update", race)
    with pytest.raises(gate.KeyframeReferenceError, match="TASK_PROJECTION_CHANGED|TASK_SUBMISSION_CHANGED"):
        if operation == "store":
            gate.store_contract(state.db, task_id, state.contract, terminal=True, status="failed", error_message="old failure")
        else:
            gate.patch_target(state.db, task_id, state.contract, prompt=PRIMARY, image_url="/late.png")
    after = _records(state)
    assert after["task"][field] == value and after["shot"] == before["shot"]
    assert after["task"]["metadata_json"] == before["task"]["metadata_json"]
    assert after["task"]["status"] == "running" and after["task"]["result_url"] == before["task"]["result_url"]
    assert events == ([("Task", 0)] if operation == "store" else [("Shot", 1), ("Task", 0)])
    assert state.contract == working


@pytest.mark.parametrize("operation", ["store", "patch"])
def test_parent_cancellation_between_guard_and_write_is_in_task_cas(state, monkeypatch, operation):
    state.task.parent_task_id = state.contract["planned"]["parent_task_id"] = "parent"
    gate.seal_contract(state.contract)
    state.task.metadata_json = json.dumps({gate.CONTRACT_KEY: state.contract})
    parent = state.Task(id="parent", name="Parent", type="keyframe_batch", status="running")
    state.db.add(parent)
    state.db.commit()
    _activate(state)
    frames, metadata, update = state.shot.keyframes, state.task.metadata_json, Query.update
    edited = False

    def race(query, values, *args, **kwargs):
        nonlocal edited
        if not edited:
            edited = True
            with Session(state.engine) as editor:
                editor.get(state.Task, "parent").status = "cancelled"
                editor.commit()
        return update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    with pytest.raises(gate.KeyframeReferenceError, match="PARENT_NOT_ACTIVE"):
        if operation == "store":
            gate.store_contract(state.db, state.task.id, state.contract, status="failed")
        else:
            gate.patch_target(state.db, state.task.id, state.contract, image_url="/late.png")
    state.db.refresh(state.shot)
    state.db.refresh(state.task)
    assert state.shot.keyframes == frames and state.task.metadata_json == metadata and state.task.status == "running"


@pytest.mark.parametrize("parent_status", ["cancelled", "failed", "completed", None])
def test_terminal_child_failure_preserves_stopped_or_removed_parent(state, parent_status):
    state.task.parent_task_id = state.contract["planned"]["parent_task_id"] = "parent"
    gate.seal_contract(state.contract)
    state.task.metadata_json = json.dumps({gate.CONTRACT_KEY: state.contract})
    if parent_status is not None:
        state.db.add(state.Task(id="parent", name="Parent", type="keyframe_batch", status=parent_status))
    state.db.commit()
    old_frames, revision = state.shot.keyframes, state.contract["storage_revision"]
    state.contract.update(phase="failed", failure={"code": "PARENT_NOT_ACTIVE"})
    assert gate.store_contract(state.db, state.task.id, state.contract, terminal=True, status="failed", error_message="parent stopped") is True
    assert state.task.status == "failed" and state.shot.keyframes == old_frames
    assert state.contract["storage_revision"] == revision + 1
    parent = state.db.get(state.Task, "parent")
    assert (parent.status if parent else None) == parent_status


def test_terminal_write_cas_retries_if_observed_parent_state_changes(state, monkeypatch):
    state.task.parent_task_id = state.contract["planned"]["parent_task_id"] = "parent"
    gate.seal_contract(state.contract)
    state.task.metadata_json = json.dumps({gate.CONTRACT_KEY: state.contract})
    state.db.add(state.Task(id="parent", name="Parent", type="keyframe_batch", status="cancelled"))
    state.db.commit()
    revision, update, counts = state.contract["storage_revision"], Query.update, []

    def race(query, values, *args, **kwargs):
        if not counts:
            with Session(state.engine) as editor:
                editor.get(state.Task, "parent").status = "failed"
                editor.commit()
        count = update(query, values, *args, **kwargs)
        counts.append(count)
        return count

    monkeypatch.setattr(Query, "update", race)
    state.contract["phase"] = "failed"
    assert gate.store_contract(state.db, state.task.id, state.contract, terminal=True, status="failed") is True
    assert counts == [0, 1] and state.contract["storage_revision"] == revision + 1
    assert state.task.status == state.db.get(state.Task, "parent").status == "failed"


@pytest.fixture
def proof(state, isolation):
    graphs = isolation.load("app.services.keyframe_reference_graph", "app/services/keyframe_reference_graph.py")
    _activate(state)

    def configure(source="PRIMARY_STORYBOARD", *, family="flux", submitted=True):
        if family == "flux":
            path = BACKEND / "workflows/keyframe_flux2_klein.json"
            mapping = {"prompt_node_id": "110", "save_image_node_id": "9", "reference_image_node_id": "76"}
            field = "text"
        else:
            path = next((BACKEND / "user_workflows").glob("*Qwen-Edit-2511*keyframe_image.json"))
            mapping = {"prompt_node_id": "184", "save_image_node_id": "163", "reference_image_node_id": "170"}
            field = "prompt"
        graph = graphs.prepare_keyframe_graph(json.loads(path.read_text(encoding="utf-8")), mapping, has_reference=source != "NONE")
        prompt = {"PRIMARY_STORYBOARD": PRIMARY, "PREVIOUS_KEYFRAME": PREVIOUS, "NONE": NONE,
                  "CUSTOM_REFERENCE": "Use Picture 1, the custom reference image, as the edit base.",
                  "SAVED_REFERENCE": "Use Picture 1, the fixed reference image, as the edit base."}[source]
        contract = deepcopy(state.contract)
        bound = _bound_contract(source, "Frozen reference label", 2 if source == "PREVIOUS_KEYFRAME" else None)
        contract.update({key: bound[key] for key in ("resolved", "binding", "binding_resolved")})
        if source == "NONE":
            contract.update(resolved=None, binding=None)
            contract["planned"]["intent"] = {"mode": "none", "url": None, "selection": "none"}
        else:
            mode = "custom" if source == "CUSTOM_REFERENCE" else "auto_select"
            url = contract["resolved"]["url"] if source in {"CUSTOM_REFERENCE", "SAVED_REFERENCE"} else None
            contract["planned"]["intent"] = gate.reference_intent({"reference_mode": mode, "reference_image_url": url})
            contract["binding"]["node_id"] = mapping["reference_image_node_id"]
            graph[mapping["reference_image_node_id"]]["inputs"]["image"] = contract["binding"]["uploaded_filename"]
        contract["target"]["reference_intent"] = deepcopy(contract["planned"]["intent"])
        graph[mapping["prompt_node_id"]]["inputs"][field] = prompt
        contract["manifest"] = gate.reference_manifest(contract)
        contract["frozen_binding_hash"] = gate.digest({key: contract[key] for key in ("resolved", "binding", "manifest")})
        template = (BACKEND / "prompt_templates/09_NovelFlow_QwenEdit2511_KeyframeImagePrompt_V1.txt").read_text(encoding="utf-8")
        contract.update(
            phase="submitted" if submitted else "prompt_ready", prepared_workflow=graph,
            context={"shot": {"id": state.shot.id, "index": 17, **contract["target"]["shot_state"]},
                     "current_keyframe": contract["target"]["current_state"],
                     "previous_keyframe_state_text": contract["target"]["previous_state_text"],
                     "visual_style": "ink", "aspect_ratio": "16:9"},
            llm_config={"provider": "fixture", "model": "fixture", "temperature": 0.3, "max_tokens": 2500},
            template={"id": "template", "name": "Frozen #09", "type": "keyframe_image_prompt", "text": template, "hash": gate.digest(template)},
            workflow={"id": "workflow", "name": "Frozen workflow", "type": "keyframe_image", "node_mapping": mapping,
                      "family": "flux2" if family == "flux" else "qwen", "output_node_id": mapping["save_image_node_id"],
                      "contract_hash": graphs.stable_graph_fingerprint(graph, mapping)},
            prompt={"text": prompt, "text_hash": gate.digest(prompt), "validation": gate.validate_reference_prompt(prompt, source)},
            submit={"state": "submitted", "prompt_id": "queued-17", "graph_hash": gate.digest(graph)} if submitted else {"state": "not_submitted"},
        )
        contract["prompt"]["cache_fingerprint"] = gate.reference_cache_fingerprint(contract)
        inspection = graphs.validate_keyframe_graph(graph, mapping, reference_count=int(source != "NONE"), expected_prompt=prompt,
                                                     expected_filename=contract["binding"]["uploaded_filename"] if source != "NONE" else None)
        contract["validation"] = {"passed": True, "graph": inspection}
        contract["draft"] = {key: {"present": True, "value": prompt} for key in ("legacy", "plan")}
        gate.seal_contract(contract)
        state.contract.clear()
        state.contract.update(contract)
        state.task.prompt_text = prompt
        state.task.reference_images = json.dumps(gate.reference_images(contract))
        state.task.workflow_id, state.task.workflow_name = "workflow", "Frozen workflow"
        state.task.workflow_json = json.dumps(graph) if submitted else None
        state.task.comfyui_prompt_id = "queued-17" if submitted else None
        state.task.status = "running"
        state.task.metadata_json = json.dumps({gate.CONTRACT_KEY: contract, "unrelated": {"keep": True}})
        frames, plan = json.loads(state.shot.keyframes), json.loads(state.shot.video_director_plan)
        intent = contract["planned"]["intent"]
        frames[contract["target"]["frame_index"]].update(prompt_text=prompt, reference_mode=intent["mode"], reference_image_url=intent["url"])
        next(item for item in plan["keyframes"] if item["index"] == contract["target"]["plan_keyframe_index"])["prompt_text"] = prompt
        state.shot.keyframes, state.shot.video_director_plan = json.dumps(frames), json.dumps(plan)
        state.db.commit()
        return inspection

    state.configure_proof, state.graphs = configure, graphs
    state.inspection = configure()
    return state


@pytest.mark.parametrize("source,family", [
    ("PRIMARY_STORYBOARD", "flux"), ("PREVIOUS_KEYFRAME", "flux"), ("CUSTOM_REFERENCE", "flux"),
    ("SAVED_REFERENCE", "flux"), ("NONE", "flux"), ("PRIMARY_STORYBOARD", "qwen"), ("PREVIOUS_KEYFRAME", "qwen"),
])
def test_full_proof_recomputes_real_frozen_graph_and_exact_cache_formula(proof, source, family):
    inspection = proof.configure_proof(source, family=family)
    before = deepcopy(proof.contract)
    assert gate.validate_frozen_contract(proof.contract, proof.task, require_submitted=True) == inspection
    resolved = proof.contract["resolved"]
    expected = {"version": 1, "context": proof.contract["context"],
                "reference": {key: resolved[key] for key in ("source_kind", "url", "sha256", "source_keyframe_index")} if resolved else None,
                "workflow": proof.contract["workflow"]["contract_hash"], "template": proof.contract["template"]["hash"],
                "llm_config": proof.contract["llm_config"]}
    assert gate.reference_cache_fingerprint(proof.contract) == gate.digest(expected) == proof.contract["prompt"]["cache_fingerprint"]
    assert proof.contract == before


@pytest.mark.parametrize("key", [
    "storage_revision", "storage_hash", "binding_resolved", "resolved", "binding", "manifest", "frozen_binding_hash",
    "target", "planned", "context", "llm_config", "workflow", "template", "prompt", "prepared_workflow", "validation", "submit",
])
def test_missing_frozen_proof_cannot_be_replaced_by_passed_true(proof, key):
    contract = deepcopy(proof.contract)
    contract.pop(key)
    if key not in {"storage_revision", "storage_hash"}:
        gate.seal_contract(contract)
    with pytest.raises(gate.KeyframeReferenceError):
        gate.validate_frozen_contract(contract, require_submitted=True)


@pytest.mark.parametrize("change", [
    "payload-hash", "payload-size", "boolean-size", "picture-index", "boolean-index", "binding-field", "binding-slot",
    "binding-node", "manifest", "binding-hash", "template-text", "template-type", "prompt-hash", "prompt-validation",
    "graph-prompt", "graph-image", "graph-extra-input", "graph-model", "output-node", "workflow-family", "workflow-hash",
    "graph-validation", "cache", "context", "llm-config", "submit-hash", "submit-cid", "submit-state", "none-intent",
])
def test_resealed_proof_corruption_is_recomputed_not_trusted(proof, change):
    contract = deepcopy(proof.contract)
    if change == "payload-hash":
        contract["binding"]["payload_sha256"] = "0" * 64
    elif change in {"payload-size", "boolean-size", "picture-index", "boolean-index", "binding-field", "binding-slot", "binding-node"}:
        field, value = {"payload-size": ("payload_size", 999), "boolean-size": ("payload_size", True),
                        "picture-index": ("picture_index", 2), "boolean-index": ("picture_index", True),
                        "binding-field": ("field", "other"), "binding-slot": ("output_slot", 1), "binding-node": ("node_id", "110")}[change]
        contract["binding"][field] = value
        contract["frozen_binding_hash"] = gate.digest({key: contract[key] for key in ("resolved", "binding", "manifest")})
    elif change == "manifest":
        contract["manifest"] = []
    elif change == "binding-hash":
        contract["frozen_binding_hash"] = "0" * 64
    elif change.startswith("template-"):
        contract["template"]["text" if change == "template-text" else "type"] = "changed"
    elif change == "prompt-hash":
        contract["prompt"]["text_hash"] = "0" * 64
    elif change == "prompt-validation":
        contract["prompt"]["validation"] = {"passed": True}
    elif change in {"graph-prompt", "graph-image", "graph-model"}:
        node, field = {"graph-prompt": ("110", "text"), "graph-image": ("76", "image"), "graph-model": ("103", "unet_name")}[change]
        contract["prepared_workflow"][node]["inputs"][field] = "changed"
    elif change == "graph-extra-input":
        contract["prepared_workflow"]["unbound"] = {"class_type": "LoadImage", "inputs": {"image": "extra.png"}}
    elif change in {"output-node", "workflow-family", "workflow-hash"}:
        contract["workflow"][{"output-node": "output_node_id", "workflow-family": "family", "workflow-hash": "contract_hash"}[change]] = "changed"
    elif change == "graph-validation":
        contract["validation"] = {"passed": True}
    elif change == "cache":
        contract["prompt"]["cache_fingerprint"] = "0" * 64
    elif change == "context":
        contract["context"]["visual_style"] = "new style"
    elif change == "llm-config":
        contract["llm_config"]["model"] = "different model"
    elif change.startswith("submit-"):
        contract["submit"][{"submit-hash": "graph_hash", "submit-cid": "prompt_id", "submit-state": "state"}[change]] = "" if change == "submit-cid" else "changed"
    else:
        contract["planned"]["intent"]["mode"] = "none"
    gate.seal_contract(contract)
    with pytest.raises(gate.KeyframeReferenceError):
        gate.validate_frozen_contract(contract, require_submitted=True)


def test_full_proof_checks_actual_prompt_language_even_if_all_hashes_match(proof):
    contract = deepcopy(proof.contract)
    text = PRIMARY + " Use ref1/2/3/4."
    contract["prompt"].update(text=text, text_hash=gate.digest(text))
    contract["prepared_workflow"]["110"]["inputs"]["text"] = text
    contract["submit"]["graph_hash"] = gate.digest(contract["prepared_workflow"])
    gate.seal_contract(contract)
    with pytest.raises(gate.KeyframeReferenceError, match="UNBOUND_PICTURE_REFERENCE"):
        gate.validate_frozen_contract(contract)


@pytest.mark.parametrize("field,value", [
    ("comfyui_prompt_id", "other-cid"), ("prompt_text", "other prompt"), ("reference_images", "[]"),
    ("workflow_id", "other-id"), ("workflow_name", "other name"), ("workflow_json", "{}"),
    ("metadata_json", "{broken"), ("metadata_json", "{}"),
])
def test_full_proof_optional_task_must_match_all_persisted_projections(proof, field, value):
    setattr(proof.task, field, value)
    with pytest.raises(gate.KeyframeReferenceError):
        gate.validate_frozen_contract(proof.contract, proof.task, require_submitted=True)


def test_prepared_proof_is_valid_but_not_an_acknowledged_submission(proof):
    inspection = proof.configure_proof(submitted=False)
    assert gate.validate_frozen_contract(proof.contract, proof.task) == inspection
    with pytest.raises(gate.KeyframeReferenceError, match="SUBMISSION_NOT_CONFIRMED"):
        gate.validate_frozen_contract(proof.contract, proof.task, require_submitted=True)
    proof.task.workflow_json = json.dumps(proof.contract["prepared_workflow"])
    with pytest.raises(gate.KeyframeReferenceError, match="TASK_PROJECTION_CHANGED"):
        gate.validate_frozen_contract(proof.contract, proof.task)


@pytest.mark.parametrize("key", ["context", "llm_config"])
def test_empty_context_is_missing_cache_proof_not_an_acceptable_boolean_stamp(proof, key):
    contract = deepcopy(proof.contract)
    contract[key] = {}
    gate.seal_contract(contract)
    with pytest.raises(gate.KeyframeReferenceError, match="CONTRACT_PROOF_INVALID"):
        gate.reference_cache_fingerprint(contract)
    with pytest.raises(gate.KeyframeReferenceError):
        gate.validate_frozen_contract(contract)


@pytest.mark.parametrize("record", [None, {}, {"version": 1, "validation": {"passed": True}}])
def test_legacy_records_fail_before_importing_any_graph_or_application_module(record):
    with pytest.raises(gate.KeyframeReferenceError, match="CONTRACT_SEAL_INVALID"):
        gate.validate_frozen_contract(record)


@pytest.mark.parametrize("cancelled", [False, True])
def test_explicit_ack_advances_stored_attempted_record_without_validating_against_staged_cid(proof, cancelled):
    proof.configure_proof(submitted=False)
    proof.contract.update(phase="submitting", submit={"state": "attempted", "graph_hash": gate.digest(proof.contract["prepared_workflow"])})
    gate.store_contract(proof.db, proof.task.id, proof.contract)
    before_revision = proof.contract["storage_revision"]
    if cancelled:
        proof.task.status, proof.task.error_message = "cancelled", "user stopped"
        proof.db.commit()
    proof.contract["submit"].update(state="submitted", prompt_id="new-ack")
    proof.contract["phase"] = "submitted"
    if not cancelled:
        gate.assert_task_active(proof.db, proof.task, proof.contract)
    assert proof.task.comfyui_prompt_id is None
    assert gate.store_contract(proof.db, proof.task.id, proof.contract, terminal=cancelled, comfyui_prompt_id="new-ack",
                               workflow_json=json.dumps(proof.contract["prepared_workflow"]), status="running") is True
    assert proof.contract["storage_revision"] == before_revision + 1
    assert proof.task.comfyui_prompt_id == "new-ack"
    assert gate.validate_frozen_contract(proof.contract, proof.task, require_submitted=True) == proof.inspection
    assert proof.task.status == ("cancelled" if cancelled else "running")
    if cancelled:
        assert proof.task.error_message == "user stopped"


@pytest.mark.parametrize("change", ["without-attempt", "replace-ack", "external-cid"])
def test_ack_exception_cannot_replace_existing_or_external_submission_identity(proof, change):
    if change != "replace-ack":
        proof.configure_proof(submitted=False)
    if change == "external-cid":
        proof.contract["submit"] = {"state": "attempted", "graph_hash": gate.digest(proof.contract["prepared_workflow"])}
        gate.store_contract(proof.db, proof.task.id, proof.contract)
        proof.task.comfyui_prompt_id = "external-cid"
        proof.db.commit()
    before, token = _records(proof), (proof.contract["storage_revision"], proof.contract["storage_hash"])
    proof.contract["submit"] = {"state": "submitted", "prompt_id": "new-ack", "graph_hash": gate.digest(proof.contract["prepared_workflow"])}
    with pytest.raises(gate.KeyframeReferenceError, match="TASK_SUBMISSION_CHANGED"):
        gate.store_contract(proof.db, proof.task.id, proof.contract, terminal=True, comfyui_prompt_id="new-ack",
                            workflow_json=json.dumps(proof.contract["prepared_workflow"]))
    assert _records(proof) == before
    assert (proof.contract["storage_revision"], proof.contract["storage_hash"]) == token


@pytest.mark.parametrize("operation", ["store", "patch"])
def test_same_attempt_new_seal_and_cid_during_sql_write_veto_old_worker(proof, monkeypatch, operation):
    before, old_working = _records(proof), deepcopy(proof.contract)
    task_id, update, counts = proof.task.id, Query.update, []
    latest = []

    def race(query, values, *args, **kwargs):
        if not latest:
            with Session(proof.engine) as editor:
                task = editor.get(proof.Task, task_id)
                metadata = json.loads(task.metadata_json)
                record = metadata[gate.CONTRACT_KEY]
                record["submit"]["prompt_id"] = task.comfyui_prompt_id = "newer-cid"
                gate.seal_contract(record, advance=True)
                task.metadata_json = json.dumps(metadata)
                task.error_message = "newer failure"
                editor.commit()
                latest.append(deepcopy(metadata))
        count = update(query, values, *args, **kwargs)
        counts.append((query.column_descriptions[0]["entity"].__name__, count))
        return count

    monkeypatch.setattr(Query, "update", race)
    with pytest.raises(gate.KeyframeReferenceError, match="CONTRACT_STALE"):
        if operation == "store":
            gate.store_contract(proof.db, task_id, proof.contract, terminal=True, comfyui_prompt_id="queued-17",
                                workflow_json=proof.task.workflow_json, error_message="old failure", status="failed")
        else:
            gate.patch_target(proof.db, task_id, proof.contract, image_url="/late.png")
    after = _records(proof)
    assert after["shot"] == before["shot"] and proof.contract == old_working
    assert json.loads(after["task"]["metadata_json"]) == latest[0]
    assert after["task"]["comfyui_prompt_id"] == "newer-cid" and after["task"]["error_message"] == "newer failure"
    assert counts == ([("Task", 0)] if operation == "store" else [("Shot", 1), ("Task", 0)])


@pytest.mark.parametrize("change", ["new-attempt", "same-attempt-cid", "same-attempt-freeze", "unsealed-freeze"])
def test_old_working_record_cannot_overwrite_newer_metadata_cid_or_failure(proof, change):
    working = deepcopy(proof.contract)
    metadata = json.loads(proof.task.metadata_json)
    newer = metadata[gate.CONTRACT_KEY]
    if change == "new-attempt":
        newer["attempt_id"] = "replacement-attempt"
    elif change == "same-attempt-cid":
        newer["submit"]["prompt_id"] = proof.task.comfyui_prompt_id = "newer-cid"
    else:
        newer["resolved"]["url"] = "/newer-frozen-source.png"
    if change != "unsealed-freeze":
        gate.seal_contract(newer, advance=True)
    proof.task.metadata_json = json.dumps(metadata)
    proof.task.error_message = "newer failure must survive"
    proof.db.commit()
    before = _records(proof)
    working.update(phase="failed", failure={"code": "OLD_FAILURE"})
    with pytest.raises(gate.KeyframeReferenceError) as error:
        gate.store_contract(proof.db, proof.task.id, working, terminal=True, status="failed", result_url="/old-artifact.png",
                            comfyui_prompt_id="queued-17", workflow_json=json.dumps(working["prepared_workflow"]), error_message="old failure")
    assert _records(proof) == before
    assert gate.record_contract_observation(proof.db, proof.task.id, working, error.value, artifact_url="/old-artifact.png") is True
    after = _records(proof)
    assert {key: value for key, value in after["task"].items() if key not in {"metadata_json", "updated_at"}} == {
        key: value for key, value in before["task"].items() if key not in {"metadata_json", "updated_at"}
    }
    saved = json.loads(after["task"]["metadata_json"])
    assert saved[gate.CONTRACT_KEY] == newer and saved["unrelated"] == {"keep": True}
    observation = saved[gate.OBSERVATIONS_KEY][0]
    assert observation["expected_prompt_id"] == "queued-17" and observation["expected_storage_revision"] == working["storage_revision"]
    assert observation["code"] == error.value.code and observation["artifact_url"] == "/old-artifact.png"
    assert not {"prepared_workflow", "resolved", "prompt", "binding", "failure"} & observation.keys()


@pytest.mark.parametrize("status", ["cancelled", "failed", "completed"])
def test_observation_preserves_terminal_status_result_and_contract_token(proof, status):
    proof.task.status, proof.task.result_url, proof.task.error_message = status, "/new-fact.png", "new failure"
    proof.db.commit()
    before, working = _records(proof), deepcopy(proof.contract)
    assert gate.record_contract_observation(proof.db, proof.task.id, proof.contract, RuntimeError("stale"), artifact_url="/detached.png") is True
    after = _records(proof)
    assert after["shot"] == before["shot"] and proof.contract == working
    for field in ("status", "result_url", "error_message", "comfyui_prompt_id", "workflow_json", "prompt_text", "reference_images"):
        assert after["task"][field] == before["task"][field]
    assert gate.read_contract(proof.task) == working


def test_observation_cas_retries_latest_sibling_metadata_without_resealing_contract(proof, monkeypatch):
    task_id, update = proof.task.id, Query.update
    original = deepcopy(proof.contract)
    calls = []

    def race(query, values, *args, **kwargs):
        if not calls:
            with Session(proof.engine) as editor:
                task = editor.get(proof.Task, task_id)
                metadata = json.loads(task.metadata_json)
                metadata["parallel"] = "keep"
                metadata[gate.OBSERVATIONS_KEY] = [{"code": "prior observation"}]
                task.metadata_json = json.dumps(metadata)
                task.status = "cancelled"
                editor.commit()
        calls.append(deepcopy(values))
        return update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", race)
    assert gate.record_contract_observation(proof.db, task_id, proof.contract, RuntimeError("x" * 5000)) is True
    metadata = json.loads(proof.task.metadata_json)
    assert len(calls) == 2 and metadata["parallel"] == "keep"
    assert len(metadata[gate.OBSERVATIONS_KEY]) == 2 and metadata[gate.OBSERVATIONS_KEY][0] == {"code": "prior observation"}
    assert len(metadata[gate.OBSERVATIONS_KEY][1]["reason"]) == 1024
    assert metadata[gate.CONTRACT_KEY] == original and proof.contract == original and proof.task.status == "cancelled"


@pytest.mark.parametrize("metadata", ["{broken", "[]", '{"not_json":NaN}', json.dumps({gate.OBSERVATIONS_KEY: {}})])
def test_observation_never_repairs_malformed_metadata(state, metadata):
    state.task.metadata_json = metadata
    state.db.commit()
    before = _records(state)
    with pytest.raises(gate.KeyframeReferenceError):
        gate.record_contract_observation(state.db, state.task.id, state.contract, RuntimeError("stale"))
    assert _records(state) == before


def test_observation_cas_exhaustion_has_no_partial_append_or_task_changes(state, monkeypatch):
    before, working = _records(state), deepcopy(state.contract)
    update = Mock(return_value=0)
    monkeypatch.setattr(Query, "update", update)
    with pytest.raises(gate.KeyframeReferenceError, match="OBSERVATION_WRITE_CONFLICT"):
        gate.record_contract_observation(state.db, state.task.id, state.contract, RuntimeError("conflict"))
    assert update.call_count == 3 and _records(state) == before and state.contract == working


def test_observation_for_removed_task_is_a_noop_and_cannot_recreate_it(state):
    task_id = state.task.id
    state.db.delete(state.task)
    state.db.commit()
    assert gate.record_contract_observation(state.db, task_id, state.contract, RuntimeError("removed")) is False
    assert state.db.query(state.Task).count() == 0


def _output_case(*, outputs=DEFAULT, status=DEFAULT):
    graphs = sys.modules["app.services.keyframe_reference_graph"]
    graph = json.loads((BACKEND / "workflows/keyframe_flux2_klein.json").read_text(encoding="utf-8"))
    graph["110"]["inputs"]["text"] = PRIMARY
    graph["76"]["inputs"]["image"] = "references/server-renamed.png"
    sha = hashlib.sha256(json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    mapping = {"prompt_node_id": "110", "save_image_node_id": "9", "reference_image_node_id": "76"}
    inspection = graphs.validate_keyframe_graph(graph, mapping, reference_count=1, expected_prompt=PRIMARY,
                                                 expected_filename=graph["76"]["inputs"]["image"])
    contract = _bound_contract()
    contract["planned"].update(novel_id="novel", parent_task_id=None, requested_workflow_id="workflow")
    template = "Build one bound keyframe edit prompt."
    contract.update(
        phase="submitted", target={"shot_id": "shot", "chapter_id": "chapter", "frame_index": 0},
        context={"shot": {"id": "shot", "index": 17}, "current_keyframe": {"index": 1, "description": "Raise Ada's hand."},
                 "previous_keyframe_state_text": None, "visual_style": "ink", "aspect_ratio": "16:9"},
        llm_config={"provider": "fixture", "model": "fixture", "temperature": 0.3, "max_tokens": 2500},
        template={"id": "template", "name": "Frozen #09", "type": "keyframe_image_prompt", "text": template, "hash": gate.digest(template)},
        workflow={"id": "workflow", "name": "Frozen workflow", "type": "keyframe_image", "node_mapping": mapping,
                  "family": "flux2", "output_node_id": "9", "contract_hash": graphs.stable_graph_fingerprint(graph, mapping)},
        prompt={"text": PRIMARY, "text_hash": gate.digest(PRIMARY), "validation": gate.validate_reference_prompt(PRIMARY, "PRIMARY_STORYBOARD")},
        prepared_workflow=deepcopy(graph), validation={"passed": True, "graph": inspection},
        submit={"state": "submitted", "prompt_id": "queued-17", "graph_hash": sha},
    )
    contract["manifest"] = gate.reference_manifest(contract)
    contract["frozen_binding_hash"] = gate.digest({key: contract[key] for key in ("resolved", "binding", "manifest")})
    contract["prompt"]["cache_fingerprint"] = gate.reference_cache_fingerprint(contract)
    gate.seal_contract(contract)
    assert gate.validate_frozen_contract(contract, require_submitted=True) == inspection
    image = {"filename": "keyframe_slot17_00001_.png", "subfolder": "keyframes/run17", "type": "output"}
    history = {"prompt": [17, "queued-17", deepcopy(graph), {"client_id": "frozen-client"}, ["9"]],
               "outputs": {"9": {"images": [deepcopy(image)]}} if outputs is DEFAULT else deepcopy(outputs),
               "status": {"completed": True, "status_str": "success", "messages": []} if status is DEFAULT else deepcopy(status)}
    return SimpleNamespace(contract=contract, history=history, image=image, endpoint="https://comfy.example.test/frozen")


@pytest.mark.parametrize("status", [
    {"completed": True}, {"status_str": "success"}, {"status_str": "completed"},
])
def test_output_selector_returns_only_exact_submitted_save_image_without_mutation(status):
    case = _output_case(status=status)
    case.history["outputs"]["preview"] = {"images": [{"filename": "wrong.png", "subfolder": "", "type": "temp"}]}
    before = deepcopy((case.history, case.contract))
    url = gate.select_keyframe_output(case.history, case.contract, case.endpoint + "/")
    assert url == case.endpoint + "/view?filename=keyframe_slot17_00001_.png&subfolder=keyframes%2Frun17&type=output"
    assert (case.history, case.contract) == before


@pytest.mark.parametrize("change", ["wrong-prompt-id", "wrong-graph", "wrong-saved-hash", "missing-prompt", "short-prompt", "not-object"])
def test_output_history_requires_exact_prompt_id_and_submitted_graph_hash(change):
    case = _output_case()
    if change == "wrong-prompt-id":
        case.history["prompt"][1] = "another-job"
    elif change == "wrong-graph":
        case.history["prompt"][2]["110"]["inputs"]["text"] += " changed"
    elif change == "wrong-saved-hash":
        case.contract["submit"]["graph_hash"] = "0" * 64
        # Keep the seal valid to exercise submission-proof recomputation, not CAS integrity.
        gate.seal_contract(case.contract)
    elif change == "missing-prompt":
        case.history.pop("prompt")
    elif change == "short-prompt":
        case.history["prompt"] = [17, "queued-17"]
    else:
        case.history = []
    with pytest.raises(gate.KeyframeReferenceError, match="HISTORY_SUBMISSION_MISMATCH"):
        gate.select_keyframe_output(case.history, case.contract, case.endpoint)


@pytest.mark.parametrize("status", [
    None, {}, {"completed": False}, {"status_str": "running"}, {"completed": 1},
    {"status_str": "error", "completed": False}, {"status_str": "error", "completed": True},
])
def test_output_error_or_incomplete_status_rejects_even_with_a_saved_image(status):
    case = _output_case(status=status)
    with pytest.raises(gate.KeyframeReferenceError, match="RESULT_NOT_COMPLETED"):
        gate.select_keyframe_output(case.history, case.contract, case.endpoint)


@pytest.mark.parametrize("images", [None, [], {}, "image.png", [None], [{}, {}]])
def test_output_selector_rejects_uncertain_or_multiple_images(images):
    case = _output_case(outputs={"9": {"images": images}})
    with pytest.raises(gate.KeyframeReferenceError, match="RESULT_NODE_UNCERTAIN"):
        gate.select_keyframe_output(case.history, case.contract, case.endpoint)


def test_output_selector_rejects_two_individually_valid_saved_images():
    case = _output_case()
    second = {**case.image, "filename": "keyframe_slot17_00002_.png"}
    case.history["outputs"]["9"]["images"].append(second)
    with pytest.raises(gate.KeyframeReferenceError, match="RESULT_NODE_UNCERTAIN"):
        gate.select_keyframe_output(case.history, case.contract, case.endpoint)


@pytest.mark.parametrize("outputs", [None, {}, {"9": {}}, {"9": None}, {"9": []}])
def test_output_selector_has_no_preview_or_other_save_node_fallback(outputs):
    case = _output_case(outputs=outputs)
    if isinstance(case.history["outputs"], dict):
        case.history["outputs"].update({"preview": {"images": [case.image]}, "other-save": {"images": [case.image]}})
    with pytest.raises(gate.KeyframeReferenceError, match="RESULT_NODE_UNCERTAIN"):
        gate.select_keyframe_output(case.history, case.contract, case.endpoint)


@pytest.mark.parametrize("field,value", [
    ("filename", None), ("filename", ""), ("filename", ".."), ("filename", "."), ("filename", "../escape.png"),
    ("filename", "/absolute.png"), ("filename", "folder\\image.png"), ("filename", 1),
    ("subfolder", None), ("subfolder", "/absolute"), ("subfolder", "../escape"), ("subfolder", "a/../b"),
    ("subfolder", "a\\b"), ("type", "temp"), ("type", "input"), ("type", None),
])
def test_output_locator_is_a_single_output_file_not_preview_input_or_traversal(field, value):
    case = _output_case()
    case.history["outputs"]["9"]["images"][0][field] = value
    with pytest.raises(gate.KeyframeReferenceError, match="INVALID_OUTPUT_LOCATOR"):
        gate.select_keyframe_output(case.history, case.contract, case.endpoint)


def test_output_locator_query_encoding_preserves_filename_and_subfolder():
    case = _output_case()
    image = {"filename": "\u5173\u952e\u5e27 & 17.png", "subfolder": "chapter 1/a&b", "type": "output"}
    case.history["outputs"]["9"]["images"] = [image]
    url = urlsplit(gate.select_keyframe_output(case.history, case.contract, case.endpoint))
    assert parse_qs(url.query) == {key: [value] for key, value in image.items()}
    assert url.path == "/frozen/view" and not url.fragment


@pytest.mark.parametrize("endpoint", [
    "", "comfy.example.test", "ftp://comfy.example.test", "https:///missing-host",
    "https://user:password@comfy.example.test", "https://comfy.example.test?other=host", "https://comfy.example.test#fragment",
])
def test_frozen_client_rejects_ambiguous_endpoint(endpoint, isolation):
    isolation.load("app.services.comfyui.client", "app/services/comfyui/client.py")
    with pytest.raises(gate.KeyframeReferenceError, match="INVALID_COMFYUI_ENDPOINT"):
        gate.frozen_keyframe_client(endpoint)


def test_frozen_endpoint_closure_covers_real_upload_queue_history_and_result_methods(isolation, monkeypatch):
    module = isolation.load("app.services.comfyui.client", "app/services/comfyui/client.py")
    settings = SimpleNamespace(COMFYUI_HOST="https://old.example.test")
    isolation.stub("app.core.config", get_settings=lambda: settings)
    case = _output_case()
    frozen = gate.frozen_keyframe_client(case.endpoint + "/")
    other = gate.frozen_keyframe_client("https://other.example.test")
    settings.COMFYUI_HOST = "https://new.example.test"
    assert module.ComfyUIClient().base_url == settings.COMFYUI_HOST
    assert frozen.base_url == case.endpoint and other.base_url == "https://other.example.test"
    with pytest.raises(AttributeError):
        frozen.base_url = settings.COMFYUI_HOST
    requests = []

    def respond(request):
        requests.append(request)
        suffix = request.url.path.removeprefix("/frozen")
        data = {"/upload/image": {"name": "bound.png", "subfolder": "refs", "type": "input"},
                "/prompt": {"prompt_id": "queued-17"}, "/queue": {"queue_running": [], "queue_pending": []},
                "/history/queued-17": {"queued-17": case.history}}[suffix]
        return httpx.Response(200, json=data)

    monkeypatch.setattr(frozen, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False))

    async def exercise():
        receipt = await frozen.upload_image("/never-read.png", upload_name="keyframe.png", payload=PAYLOAD)
        assert receipt["success"] is True and receipt["payload_sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
        queued = await frozen.queue_prompt(case.history["prompt"][2])
        assert queued == {"success": True, "prompt_id": "queued-17"}
        history = await frozen.get_prompt_state(queued["prompt_id"])
        assert history["state"] == "completed"
        return gate.select_keyframe_output(history["history"], case.contract, frozen.base_url)

    assert asyncio.run(exercise()).startswith(case.endpoint + "/view?")
    assert [str(request.url) for request in requests] == [case.endpoint + suffix for suffix in (
        "/upload/image", "/prompt", "/queue", "/history/queued-17",
    )]
    assert json.loads(requests[1].content) == {"prompt": case.history["prompt"][2], "client_id": frozen.client_id}
