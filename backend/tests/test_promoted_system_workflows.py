import json
from pathlib import Path

from app.constants.workflow import DEFAULT_WORKFLOWS, EXTRA_SYSTEM_WORKFLOWS
from app.models.workflow import Workflow
from app.services.task_service import TaskService
from app.services.workflow_service import WorkflowService


PROMOTED = [config for config in EXTRA_SYSTEM_WORKFLOWS if config.get("legacy_user_filename")]
FLARE_COPIES = [config for config in EXTRA_SYSTEM_WORKFLOWS if config["filename"].startswith("gpt_image_2_5_flare_sub2api_")]


def test_selected_workflows_are_registered_with_their_original_graphs(db_session):
    assert len(PROMOTED) == 11
    WorkflowService(db_session).load_default_workflows()

    for config in PROMOTED:
        workflow = db_session.query(Workflow).filter_by(
            type=config["type"], name=config["name"], is_system=True,
        ).one()
        graph = json.loads(workflow.workflow_json)
        mapping = json.loads(workflow.node_mapping)
        assert Path(workflow.file_path).name == config["filename"]
        assert graph == json.loads(Path(workflow.file_path).read_text(encoding="utf-8"))
        assert mapping == config["node_mapping"]
        assert TaskService.validate_workflow_node_mapping(workflow, config["type"]) == (True, "")
        for key, value in mapping.items():
            if "node" not in key:
                continue
            node_ids = value if isinstance(value, list) else [value]
            assert all(str(node_id) in graph for node_id in node_ids if node_id)

    assert {DEFAULT_WORKFLOWS[kind] for kind in ("character", "scene", "prop")} == {
        config["filename"] for config in PROMOTED if config["type"] in {"character", "scene", "prop"}
    }


def test_matching_user_workflows_are_promoted_in_place(db_session):
    db_session.autoflush = False
    config = next(item for item in PROMOTED if item["type"] == "VIDEO_CONTINUATION")
    graph = (Path(WorkflowService.get_workflows_dir()) / config["filename"]).read_text(encoding="utf-8")
    original = Workflow(
        name=config["name"], description=config["description"], type=config["type"],
        workflow_json=graph, node_mapping=json.dumps(config["node_mapping"]),
        file_path=f"/old-install/user_workflows/{config['legacy_user_filename']}",
        is_system=False, is_active=True,
    )
    db_session.add(original)
    db_session.commit()
    original_id = original.id

    service = WorkflowService(db_session)
    service.load_default_workflows()
    service.load_default_workflows()

    workflow = db_session.get(Workflow, original_id)
    assert workflow.is_system and workflow.is_active
    assert workflow.file_path == str(Path(service.get_workflows_dir()) / config["filename"])
    assert json.loads(workflow.extension) == config["extension"]
    assert db_session.query(Workflow).filter_by(type=config["type"], name=config["name"]).count() == 1
    assert db_session.query(Workflow).filter_by(type=config["type"], is_active=True).count() == 1


def test_modified_user_graph_stays_custom(db_session):
    config = next(item for item in PROMOTED if item["type"] == "scene")
    original = Workflow(
        name=config["name"], description=config["description"], type=config["type"],
        workflow_json='{"changed": {}}', node_mapping=json.dumps(config["node_mapping"]),
        file_path=f"/old-install/user_workflows/{config['legacy_user_filename']}",
        is_system=False, is_active=True,
    )
    db_session.add(original)
    db_session.commit()

    WorkflowService(db_session).load_default_workflows()

    assert not original.is_system and original.is_active
    assert db_session.query(Workflow).filter_by(type=config["type"], is_system=True).count() == 1
    assert db_session.query(Workflow).filter_by(type=config["type"], is_active=True).count() == 1


def test_flare_sub2api_workflows_are_separate_system_copies(db_session):
    assert len(FLARE_COPIES) == 7
    original_ids = {}
    for config in FLARE_COPIES:
        graph = (Path(WorkflowService.get_workflows_dir()) / config["filename"]).read_text(encoding="utf-8")
        original = Workflow(
            name=config["name"], description=config["description"], type=config["type"],
            workflow_json=graph, node_mapping=json.dumps(config["node_mapping"]),
            file_path=f"/old-install/user_workflows/original_{config['type']}.json",
            is_system=False, is_active=True,
        )
        db_session.add(original)
        db_session.flush()
        original_ids[config["type"]] = original.id
    db_session.commit()

    service = WorkflowService(db_session)
    service.load_default_workflows()
    service.load_default_workflows()

    for config in FLARE_COPIES:
        original = db_session.get(Workflow, original_ids[config["type"]])
        assert not original.is_system and original.is_active
        assert original.file_path == f"/old-install/user_workflows/original_{config['type']}.json"
        system = db_session.query(Workflow).filter_by(
            type=config["type"], name=config["name"], is_system=True,
        ).one()
        assert system.id != original.id and not system.is_active
        assert system.file_path == str(Path(service.get_workflows_dir()) / config["filename"])
        assert json.loads(system.workflow_json) == json.loads(original.workflow_json)
        assert json.loads(system.node_mapping) == config["node_mapping"]
        assert TaskService.validate_workflow_node_mapping(system, config["type"]) == (True, "")
        assert db_session.query(Workflow).filter_by(type=config["type"], name=config["name"]).count() == 2
