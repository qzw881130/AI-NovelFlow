from app.services.comfyui.client import ComfyUIClient


def test_parse_outputs_recognizes_advanced_save_image_node(monkeypatch):
    client = ComfyUIClient()
    monkeypatch.setattr(type(client), "base_url", property(lambda _self: "http://comfy.test"))
    workflow = {
        "494": {"class_type": "SaveImageAdvanced", "inputs": {}},
        "515": {"class_type": "PreviewImage", "inputs": {}},
    }
    outputs = {
        "515": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]},
        "494": {"images": [{"filename": "final.png", "subfolder": "advanced", "type": "output"}]},
    }

    result = client._parse_outputs(outputs, workflow)

    assert result == {
        "success": True,
        "image_url": "http://comfy.test/view?filename=final.png&subfolder=advanced&type=output",
        "message": "生成成功",
    }
