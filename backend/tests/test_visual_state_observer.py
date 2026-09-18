import asyncio
import base64
from hashlib import sha256
from io import BytesIO
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from app.schemas.visual_state import ObservationQuestion
from app.services.llm import LLMConfig
from app.services import visual_state_observer as observer


def png_bytes():
    stream = BytesIO()
    Image.new("RGB", (4, 3), "blue").save(stream, "PNG")
    return stream.getvalue()


class FakeLLM:
    def __init__(self, response=None, **changes):
        values = {
            "provider": "deepseek",
            "model": "deepseek-v4-flash-vision-exp",
            "api_url": "https://example.invalid",
            "api_key": "test-key",
            "image_input": None,
            "max_tokens": 393216,
        }
        values.update(changes)
        self.__dict__.update(values)
        self.response = response
        self.calls = []

    def _get_client(self):
        return SimpleNamespace(config=LLMConfig(
            self.provider, self.model, self.api_url, self.api_key, image_input=self.image_input,
        ))

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_observer_sends_exact_bytes_and_neutral_questions_with_computed_hash():
    payload = png_bytes()
    reference = SimpleNamespace(payload=payload, sha256=sha256(payload).hexdigest())
    questions = (ObservationQuestion(predicate="character_location", subject="fox", value="tree"),)
    fact = {**questions[0].model_dump(mode="json"), "state": "PRESENT", "confidence": "HIGH",
            "evidence": "The fox is visibly supported by the tree."}
    llm = FakeLLM({"success": True, "content": json.dumps({"facts": [fact]})})

    provider = observer.LLMVisualObservationProvider(llm)
    result = asyncio.run(provider.observe(reference, questions))

    assert llm.max_tokens == 4096
    assert result == {"version": 1, "image_sha256": reference.sha256,
                      "provider": "deepseek/deepseek-v4-flash-vision-exp", "facts": [fact]}
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call["task_type"] == "visual_state_observation"
    assert call["response_format"] == "json_object" and call["temperature"] == 0
    request = json.loads(call["user_content"][0]["text"])
    assert request == {"image_sha256": reference.sha256,
                       "questions": [{"predicate": "character_location", "subject": "fox", "value": "tree"}]}
    assert not ({"expected", "critical", "protected", "source"} & set(request["questions"][0]))
    header, encoded = call["user_content"][1]["image_url"]["url"].split(",", 1)
    assert header == "data:image/png;base64" and base64.b64decode(encoded) == payload


@pytest.mark.parametrize("changes", [
    {"model": "deepseek-v4-flash"},
    {"api_url": ""},
    {"api_key": ""},
    {"provider": "anthropic"},
    {"image_input": False},
])
def test_factory_rejects_missing_or_unsupported_configuration(monkeypatch, changes):
    llm = FakeLLM(**changes)
    monkeypatch.setattr(observer, "LLMService", lambda: llm)
    assert observer.get_configured_visual_state_observer() is None


def test_factory_accepts_known_vision_model_and_explicit_keyless_custom(monkeypatch):
    known = FakeLLM()
    monkeypatch.setattr(observer, "LLMService", lambda: known)
    assert isinstance(observer.get_configured_visual_state_observer(), observer.LLMVisualObservationProvider)

    custom = FakeLLM(provider="custom", model="local-vision", api_key="", image_input=True)
    monkeypatch.setattr(observer, "LLMService", lambda: custom)
    assert isinstance(observer.get_configured_visual_state_observer(), observer.LLMVisualObservationProvider)


@pytest.mark.parametrize("response", [
    {"success": True, "content": "not-json"},
    {"success": True, "content": "[]"},
])
def test_invalid_success_response_remains_an_invalid_observation(response):
    payload = png_bytes()
    reference = SimpleNamespace(payload=payload, sha256=sha256(payload).hexdigest())
    result = asyncio.run(observer.LLMVisualObservationProvider(FakeLLM(response)).observe(
        reference, (ObservationQuestion(predicate="character_present", subject="fox"),)))
    assert result["image_sha256"] == reference.sha256 and result["facts"] is None


@pytest.mark.parametrize("fault", ["missing", "extra", "wrong", "reordered"])
def test_facts_must_match_each_question_exactly(fault):
    payload = png_bytes()
    reference = SimpleNamespace(payload=payload, sha256=sha256(payload).hexdigest())
    questions = (
        ObservationQuestion(predicate="character_present", subject="fox"),
        ObservationQuestion(predicate="character_location", subject="fox", value="tree"),
    )
    facts = [{**question.model_dump(mode="json"), "state": "PRESENT", "confidence": "HIGH", "evidence": "Visible."}
             for question in questions]
    if fault == "missing":
        facts.pop()
    elif fault == "extra":
        facts.append(dict(facts[-1]))
    elif fault == "wrong":
        facts[-1]["value"] = "rock"
    else:
        facts.reverse()
    result = asyncio.run(observer.LLMVisualObservationProvider(FakeLLM(
        {"success": True, "content": json.dumps({"facts": facts})})).observe(reference, questions))
    assert result["facts"] is None


def test_maximum_question_set_uses_bounded_scaled_output_budget():
    payload = png_bytes()
    reference = SimpleNamespace(payload=payload, sha256=sha256(payload).hexdigest())
    questions = tuple(ObservationQuestion(predicate="character_present", subject=f"actor_{index}")
                      for index in range(128))
    facts = [{**question.model_dump(mode="json"), "state": "UNKNOWN", "confidence": "LOW", "evidence": "Unclear."}
             for question in questions]
    llm = FakeLLM({"success": True, "content": json.dumps({"facts": facts})})
    result = asyncio.run(observer.LLMVisualObservationProvider(llm).observe(reference, questions))
    assert llm.max_tokens == 32768
    assert result["facts"] == facts


def test_provider_failure_is_not_converted_to_an_observation():
    payload = png_bytes()
    reference = SimpleNamespace(payload=payload, sha256=sha256(payload).hexdigest())
    with pytest.raises(RuntimeError, match="vision unavailable"):
        asyncio.run(observer.LLMVisualObservationProvider(FakeLLM(
            {"success": False, "error": "vision unavailable"})).observe(
                reference, (ObservationQuestion(predicate="character_present", subject="fox"),)))
