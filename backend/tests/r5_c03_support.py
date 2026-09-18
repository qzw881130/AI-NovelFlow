"""Composable C03 publisher for legal current Source, Revision, RSA, and media lineage."""

import asyncio
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
from PIL import Image


SOURCE_FIRST = "Ada and Bea wait beside the gate."
SOURCE_SECOND = "Ada changes into a blue coat."
SOURCE_TEXT = SOURCE_FIRST + SOURCE_SECOND
OWNERSHIP = "chapter-shot-ownership-v2"


class _SplitLLM:
    provider, model, timeout, max_tokens, temperature = "openai", "r5-c03-split", 10, 4096, 0.2

    def __init__(self, db, value):
        self.transport = _LoggedTransport(value, self.model)

    async def chat_completion(self, **kwargs):
        return await self.transport.chat_completion(**kwargs)


class _ParseLLM:
    provider, model, timeout, max_tokens, temperature = "openai", "r5-c03-parse", 10, 4096, 0.2

    def __init__(self, db, outputs):
        self.outputs = outputs

    async def chat_completion(self, **kwargs):
        kind = kwargs["task_type"].removeprefix("parse_")
        return await _LoggedTransport(self.outputs[kind], self.model).chat_completion(**kwargs)


class _NoResolverLLM:
    provider, model, timeout = "test", "r5-c03-resolver", 10

    async def chat_completion(self, **kwargs):
        raise AssertionError("Exact current bindings must not require resolver model inference")


class _RsaLLM:
    provider, model = "openai", "r5-c03-rsa"

    def __init__(self, db):
        pass

    async def chat_completion(self, **kwargs):
        payload, _ = json.JSONDecoder().raw_decode(kwargs["user_content"][0]["text"].split("\n", 1)[1].lstrip())
        count = len(payload["reference_image_manifest"])
        pictures = ", ".join(f"<Picture {index}>" for index in range(1, count + 1))
        prompt = f"{pictures} are the frozen character and scene references. Keep Ada and Bea beside the gate."
        output = {"status": "READY", "final_prompt": prompt, "conflicts": []}
        return await _LoggedTransport(output, self.model, image_input=True).chat_completion(**kwargs)


class _LoggedTransport:
    """Use the production provider/log lifecycle while replacing only HTTP transport."""

    def __init__(self, output, model, image_input=False, runtime=None):
        self.output, self.model, self.image_input = output, model, image_input
        if runtime is None:
            from app.services.llm.base import LLMConfig
            from app.services.llm.client import LLMClient
            from app.services.llm.providers import openai as provider_module

            runtime = LLMConfig, LLMClient, provider_module
        self.runtime = runtime

    async def chat_completion(self, **kwargs):
        LLMConfig, LLMClient, provider_module = self.runtime

        raw = self.output if isinstance(self.output, str) else json.dumps(self.output, ensure_ascii=False)
        response = {"choices": [{"message": {"content": raw}, "finish_reason": "stop"}]}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
        original_client = provider_module.httpx.AsyncClient

        def client(*args, **options):
            options.pop("proxy", None)
            return original_client(*args, transport=transport, **options)

        provider_module.httpx.AsyncClient = client
        try:
            config = LLMConfig(
                "openai", self.model, "https://example.invalid/v1", "test-key",
                timeout=10, image_input=self.image_input,
            )
            return await LLMClient(config).chat_completion(**kwargs)
        finally:
            provider_module.httpx.AsyncClient = original_client


async def logged_completion(runtime, output, model, **kwargs):
    return await _LoggedTransport(output, model, runtime=runtime).chat_completion(**kwargs)


class _Remote:
    def __init__(self):
        self.submits = 0

    async def upload_image(self, path, *, upload_name, payload):
        self.payload = payload
        return {
            "success": True, "filename": upload_name, "subfolder": "", "type": "input",
            "payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_size": len(payload),
        }

    def _client(self):
        output = BytesIO()
        Image.new("RGB", (160, 96), "gold").save(output, format="PNG")

        def response(request):
            return httpx.Response(200, content=output.getvalue() if request.url.params.get("type") == "output" else self.payload)

        return httpx.AsyncClient(transport=httpx.MockTransport(response))

    async def queue_prompt(self, graph):
        self.submits += 1
        self.graph = deepcopy(graph)
        return {"success": True, "prompt_id": f"r5-c03-{self.submits}"}

    async def get_prompt_state(self, prompt_id):
        return {
            "state": "completed",
            "history": {
                "prompt": [1, prompt_id, deepcopy(self.graph)],
                "status": {"completed": True, "status_str": "success"},
                "outputs": {"9": {"images": [{"filename": "image.png", "subfolder": "", "type": "output"}]}},
            },
        }


def _shot(index, text, characters, description, duration):
    return {
        "id": index,
        "source_citations": [{"text": text}],
        "source_ownership": {"text": text},
        "description": description,
        "video_description": "The camera moves slowly towards the gate.",
        "characters": characters,
        "scene": "gate",
        "props": [],
        "duration": duration,
        "continuity_mode": "NORMAL",
        "dialogues": [],
        "audio_events": [],
        "source_treatments": [{
            "key": "visual",
            "type": "VISUAL",
            "source_evidence": [{"text": text}],
            "visual_targets": ["description", "video_description"],
        }],
    }


def build_legal_chain(db, root, monkeypatch, *, target_shot_id="shot"):
    """Publish a deterministic-ID target through the current production fixture semantics."""
    from app.models.appearance_timeline import CharacterAppearance
    from app.models.asset_resolution import ChapterCharacterBinding, CharacterIdentity
    from app.models.llm_log import LLMLog
    from app.models.novel import Chapter, Character, Novel, Scene
    from app.models.prompt_template import PromptTemplate
    from app.models.rsa_media import RsaImageAttempt
    from app.models.chapter_shot_split import ChapterShotSplitRun
    from app.models.shot import Shot
    from app.models.shot_revision import ShotRevision
    from app.models.workflow import Workflow
    from app.api.shots import _admit_video_execution
    from app.core import database as app_database
    from app.repositories.task import TaskRepository
    from app.services import appearance_generation_service as appearance_generation
    from app.services import appearance_image_contract as images
    from app.services import chapter_shot_split_service as split_service
    from app.services import rsa_image_service
    from app.services.appearance_timeline_service import AppearanceTimelineService
    from app.services.asset_identity import load_policy, seed_aliases
    from app.services.asset_resolution_service import AssetResolutionService
    from app.services.chapter_asset_parse_service import ChapterAssetParseService
    from app.services.chapter_governance import register_new_chapter, require_primary, require_source
    from app.services.chapter_shot_split_service import ChapterShotSplitService
    from app.services.resolved_shot_assets_service import ResolvedShotAssetsService
    from app.services.shot_revision_service import ShotRevisionService
    from app.services.task_service import TaskService
    from app.services.llm.base import LLMConfig
    from app.services.llm.client import LLMClient
    from app.services.llm.providers import openai as provider_module
    from sqlalchemy.orm import sessionmaker

    root = (Path(root) / "r5-c03-media").resolve()
    root.mkdir()
    monkeypatch.setattr(app_database, "SessionLocal", sessionmaker(bind=db.bind, autoflush=False))
    monkeypatch.setattr(images.file_storage, "base_dir", root)

    def url_to_local_path(url):
        return str(root / url.removeprefix("/api/files/")) if url and url.startswith("/api/files/") else None

    def local_path_to_url(path):
        return "/api/files/" + str(Path(path).resolve().relative_to(root))

    for module in (images, appearance_generation):
        monkeypatch.setattr(module, "url_to_local_path", url_to_local_path)
        monkeypatch.setattr(module, "local_path_to_url", local_path_to_url)

    for name, color in (("ada.png", "navy"), ("bea.png", "red"), ("gate.png", "green")):
        Image.new("RGB", (160, 96), color).save(root / name)

    novel = Novel(id="novel", title="R5 C03 legal novel", aspect_ratio="16:9")
    chapter = Chapter(id="chapter", novel=novel, number=1, title="R5 C03", content=SOURCE_TEXT)
    ada = Character(
        id="ada", novel=novel, name="Ada", description="Adult woman", appearance="blue coat",
        image_url="/api/files/ada.png",
    )
    bea = Character(
        id="bea", novel=novel, name="Bea", description="Adult woman", appearance="red coat",
        image_url="/api/files/bea.png",
    )
    scene = Scene(
        id="scene-gate", novel=novel, name="gate", description="A garden gate", setting="quiet garden",
        image_url="/api/files/gate.png",
    )
    prompts = Path(__file__).parents[1] / "prompt_templates"
    for kind, filename in (
        ("character_parse", "character_parse.txt"),
        ("scene_parse", "scene_parse.txt"),
        ("prop_parse", "prop_parse.txt"),
    ):
        db.add(PromptTemplate(name=f"R5 C03 {kind}", type=kind, is_system=True, is_active=True,
                              template=(prompts / filename).read_text()))
    db.add(PromptTemplate(
        name="R5 C03 Shot Director", type="chapter_split", is_system=True, is_active=True,
        template=(prompts / "05_NovelFlow_VideoDirector_ShotDirector_V1.txt").read_text(),
    ))
    db.add_all([novel, chapter, ada, bea, scene])
    db.flush()
    register_new_chapter(db, chapter)
    db.commit()
    for actor in (ada, bea):
        db.add(CharacterIdentity(
            character_id=actor.id, novel_id=actor.novel_id, entity_type="INDIVIDUAL",
            group_size_hint=1, context={}, provenance={"origin": "R5_C03_FIXTURE"},
        ))
        seed_aliases(db, actor, load_policy(), {"origin": "R5_C03_FIXTURE"})
    db.commit()

    ada_candidate = {
        "name": "Ada", "entity_type": "INDIVIDUAL", "group_size_hint": 1,
        "description": ada.description,
        "appearance": ada.appearance,
        "voice_prompt": None,
        "chapter_presence": {"role": "MAJOR"},
        "source_evidence": [{"text": SOURCE_TEXT}],
        "chapter_appearances": [{
            "event_key": "ada-blue-coat", "change_type": "new", "appearance_description": "blue coat",
            "source_evidence": [{"text": SOURCE_SECOND}],
        }],
    }
    bea_candidate = {
        "name": "Bea", "entity_type": "INDIVIDUAL", "group_size_hint": 1,
        "description": bea.description,
        "appearance": bea.appearance,
        "voice_prompt": None,
        "chapter_presence": {"role": "MAJOR"},
        "source_evidence": [{"text": SOURCE_TEXT}],
        "chapter_appearances": [],
    }
    outputs = {
        "characters": {"characters": [ada_candidate, bea_candidate]},
        "scenes": {"scenes": [{
            "name": "gate", "description": scene.description, "setting": scene.setting,
            "source_evidence": [{"text": "gate"}],
        }]},
        "props": {"props": []},
    }
    parsed = asyncio.run(ChapterAssetParseService(db, _ParseLLM(db, outputs)).parse(novel.id, chapter.id))
    assert parsed["success"], parsed
    resolved = asyncio.run(AssetResolutionService(db, _NoResolverLLM()).resolve(
        novel.id, chapter.id, ["characters", "scenes", "props"], False,
    ))
    assert resolved["success"], resolved
    timeline = AppearanceTimelineService(db).build(novel.id, chapter.id)
    assert timeline["success"], timeline

    candidate = {
        "source_contract_version": OWNERSHIP,
        "chapter": chapter.title,
        "characters": ["Ada", "Bea"],
        "scenes": ["gate"],
        "props": [],
        "unresolved_assets": [],
        "shots": [
            _shot(
                1, SOURCE_FIRST, ["Ada", "Bea"],
                "Scene: gate\nCharacters:\n- Ada: beside the gate\n- Bea: beside the gate\nAction: Two people wait.",
                3,
            ),
            _shot(
                2, SOURCE_SECOND, ["Ada"],
                "Scene: gate\nCharacters:\n- Ada: wearing a blue coat\nAction: Ada changes clothes.",
                4,
            ),
        ],
    }
    split_ids = iter(("source-run", "source-task", "source-token", target_shot_id, "shot-appearance"))
    original_split_uuid = split_service.uuid4
    monkeypatch.setattr(split_service, "uuid4", lambda: next(split_ids))
    try:
        published = asyncio.run(ChapterShotSplitService(db, _SplitLLM(db, candidate)).split(
            novel.id, chapter.id, source_contract_version=OWNERSHIP,
        ))
    finally:
        monkeypatch.setattr(split_service, "uuid4", original_split_uuid)
    assert published["success"], published
    shot = db.get(Shot, target_shot_id)
    revision = ShotRevisionService(db).save_batch(
        novel.id, chapter.id, [{"id": shot.id, "expected_revision": 0, "duration": 4}],
    )
    assert revision["success"], revision
    current_source = require_source(db, shot.id)
    assert current_source.revision == 1 and db.query(ShotRevision).filter_by(shot_id=shot.id).count() == 1

    rsa = ResolvedShotAssetsService(db).resolveShotAssets(shot.id)
    assert rsa["success"] and rsa["data"]["ready"], rsa
    workflows = Path(__file__).parents[1] / "workflows"
    db.add(Workflow(
        id="rsa-shot-workflow", name="R5 C03 RSA shot", type="shot_character_scene", is_active=True,
        workflow_json=(workflows / "shot_character_scene_flux2_klein_dual_ref_edit.json").read_text(),
        node_mapping=json.dumps({
            "prompt_node_id": "117", "save_image_node_id": "9", "character_reference_image_node_id": "76",
            "scene_reference_image_node_id": "127", "width_node_id": "123", "height_node_id": "125",
        }),
    ))
    db.add(PromptTemplate(
        id="rsa-shot-template", name="R5 C03 RSA prompt", type="shot_image_prompt", is_system=True, is_active=True,
        template=(prompts / "06_NovelFlow_QwenEdit2511_ShotImagePrompt_V1.txt").read_text(),
    ))
    db.commit()
    rsa_ids = iter(("rsa-primary-task", "rsa-worker-token", "rsa-primary-artifact"))
    original_rsa_uuid = rsa_image_service.uuid4
    rsa_class = rsa_image_service.RsaImageService
    monkeypatch.setattr(rsa_image_service, "uuid4", lambda: next(rsa_ids))
    try:
        task_id = rsa_class(db).enqueue(shot.id)["data"]["taskId"]
        monkeypatch.setattr(
            rsa_image_service, "RsaImageService",
            lambda session: rsa_class(session, llm=_RsaLLM(session), client=_Remote()),
        )
        assert asyncio.run(rsa_image_service.run_next_rsa_image_task()) is True
        db.expire_all()
        attempt = db.get(RsaImageAttempt, task_id)
    finally:
        monkeypatch.setattr(rsa_image_service, "RsaImageService", rsa_class)
        monkeypatch.setattr(rsa_image_service, "uuid4", original_rsa_uuid)
    assert attempt.status == "SUCCEEDED", attempt.error
    image_task = db.get(__import__("app.models.task", fromlist=["Task"]).Task, task_id)
    assert image_task.worker_id == rsa_image_service.WORKER_ID and image_task.attempt == 1
    current_rsa, primary = require_primary(db, shot.id)
    assert current_rsa.id == rsa["data"]["id"] and primary.id == "rsa-primary-artifact"
    assert db.query(ChapterCharacterBinding).count() == 2
    appearance = db.query(CharacterAppearance).filter_by(character_id=ada.id).one()
    logs = db.query(LLMLog).filter(LLMLog.task_type.in_([
        "parse_characters", "parse_scenes", "parse_props", "split_chapter", "shot_image_prompt",
    ])).all()
    assert len(logs) == 5 and all(log.status == "success" and log.request_info for log in logs)

    db.refresh(shot)
    return SimpleNamespace(
        novel=novel, chapter=chapter, shot=shot, other_shot=db.get(Shot, "shot-appearance"),
        actors=(ada, bea), scene=scene, appearance=appearance, source=current_source,
        revision=db.query(ShotRevision).filter_by(shot_id=shot.id).one(), rsa=current_rsa,
        primary=primary, primary_attempt=db.get(RsaImageAttempt, "rsa-primary-task"), root=root,
        admit_video_execution=_admit_video_execution, task_repository_class=TaskRepository,
        task_service_class=TaskService,
        style_text=db.get(ChapterShotSplitRun, current_source.run_id).inputs["basis"]["style"]["text"],
        llm_logs=tuple(logs),
        llm_runtime=(LLMConfig, LLMClient, provider_module),
        video_workflow={
            "graph": (workflows / "video_minimax_h3_ref2va_fast.json").read_text(),
            "mapping": {
                "prompt_node_id": "138", "video_save_node_id": "150", "max_side_node_id": None,
                "megapixels_node_id": "170", "megapixels_value": "0.4", "reference_image_node_id": "137",
                "frame_count_node_id": None, "reference_audio_node_id": None, "duration_seconds_node_id": "132",
            },
            "extension": {"max_clip_duration": 15, "frame_count": 1},
        },
    )


def admit_legal_video(db, chain, workflow, *, task_id="task", only_window_index=None):
    """Use the production admission function while retaining stable IDs expected by the old tests."""
    import app.models.task as task_model

    options = {
        "use_keyframes": True,
        "use_reference_audio": False,
        "selected_mode": json.loads(chain.shot.video_director_plan or "{}").get("selected_mode") or "SINGLE_FRAME",
        "workflow_id": workflow.id,
        "only_window_index": only_window_index,
        "auto_merge_clips": False,
        "skip_llm_when_prompt_exists": False,
    }
    valid, error = chain.task_service_class.validate_workflow_node_mapping(workflow, workflow.type)
    assert valid, error
    original_uuid = task_model.uuid.uuid4
    task_model.uuid.uuid4 = lambda: task_id
    try:
        task = chain.admit_video_execution(
            chain.task_repository_class(db), chain.shot, chain.chapter, workflow, "production", options,
        )
    finally:
        task_model.uuid.uuid4 = original_uuid
    assert task.id == task_id
    return task
