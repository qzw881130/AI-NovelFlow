import io
import json
import zipfile

from app.models.workflow import Workflow
from app.services.workflow_service import WorkflowService


def test_workflow_export_preview_and_import_preserves_metadata(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(WorkflowService, "get_user_workflows_dir", staticmethod(lambda: str(tmp_path)))

    workflow_json = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "9": {"class_type": "SaveImage", "inputs": {}},
    }
    node_mapping = {"prompt_node_id": "1", "save_image_node_id": "9"}
    extension = {"mode": "test"}
    workflow = Workflow(
        name="导出导入测试工作流",
        description="测试描述",
        type="character",
        workflow_json=json.dumps(workflow_json, ensure_ascii=False),
        is_system=False,
        is_active=False,
        created_by="test",
        node_mapping=json.dumps(node_mapping, ensure_ascii=False),
        extension=json.dumps(extension, ensure_ascii=False),
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    export_response = client.post("/api/workflows/export", json={"workflow_ids": [workflow.id]})
    assert export_response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(export_response.content), "r") as zip_file:
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
        assert manifest["kind"] == "novelflow_comfyui_workflows"
        exported_item = manifest["workflows"][0]
        assert exported_item["name"] == workflow.name
        assert exported_item["description"] == workflow.description
        assert exported_item["type"] == workflow.type
        assert exported_item["node_mapping"] == node_mapping
        assert exported_item["extension"] == extension
        assert json.loads(zip_file.read(exported_item["workflow_file"]).decode("utf-8")) == workflow_json

    zip_file_obj = io.BytesIO(export_response.content)
    preview_response = client.post(
        "/api/workflows/import/preview",
        files={"file": ("workflows.zip", zip_file_obj, "application/zip")},
    )
    assert preview_response.status_code == 200
    preview_data = preview_response.json()["data"]
    assert preview_data["valid_count"] == 1
    assert preview_data["invalid_count"] == 0
    assert preview_data["workflows"][0]["valid"] is True

    before_count = db_session.query(Workflow).count()
    import_response = client.post(
        "/api/workflows/import/execute",
        data={"selected_indexes": json.dumps([0])},
        files={"file": ("workflows.zip", io.BytesIO(export_response.content), "application/zip")},
    )
    assert import_response.status_code == 200
    assert db_session.query(Workflow).count() == before_count + 1

    imported_id = import_response.json()["data"]["imported"][0]["id"]
    imported = db_session.query(Workflow).filter(Workflow.id == imported_id).first()
    assert imported is not None
    assert imported.name == workflow.name
    assert imported.description == workflow.description
    assert imported.type == workflow.type
    assert imported.is_system is False
    assert imported.is_active is False
    assert json.loads(imported.workflow_json) == workflow_json
    assert json.loads(imported.node_mapping) == node_mapping
    assert json.loads(imported.extension) == extension


def test_workflow_import_preview_rejects_missing_mapped_node(client):
    manifest = {
        "version": 1,
        "kind": "novelflow_comfyui_workflows",
        "workflows": [{
            "name": "坏映射工作流",
            "description": "",
            "type": "character",
            "node_mapping": {"prompt_node_id": "404"},
            "extension": {},
            "workflow_file": "workflows/bad.json",
        }],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zip_file.writestr("workflows/bad.json", json.dumps({"1": {"class_type": "CLIPTextEncode"}}, ensure_ascii=False))
    buffer.seek(0)

    response = client.post(
        "/api/workflows/import/preview",
        files={"file": ("workflows.zip", buffer, "application/zip")},
    )
    assert response.status_code == 200
    item = response.json()["data"]["workflows"][0]
    assert item["valid"] is False
    assert "不存在的节点" in item["errors"][0]


def test_workflow_import_preview_accepts_nodes_array_format(client):
    manifest = {
        "version": 1,
        "kind": "novelflow_comfyui_workflows",
        "workflows": [{
            "name": "节点数组格式工作流",
            "description": "",
            "type": "character",
            "node_mapping": {"prompt_node_id": "101"},
            "extension": {},
            "workflow_file": "workflows/nodes-array.json",
        }],
    }
    workflow_json = {"nodes": [{"id": 101, "type": "CLIPTextEncode"}]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zip_file.writestr("workflows/nodes-array.json", json.dumps(workflow_json, ensure_ascii=False))
    buffer.seek(0)

    response = client.post(
        "/api/workflows/import/preview",
        files={"file": ("workflows.zip", buffer, "application/zip")},
    )
    assert response.status_code == 200
    item = response.json()["data"]["workflows"][0]
    assert item["valid"] is True
