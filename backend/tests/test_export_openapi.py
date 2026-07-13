from scripts.export_openapi import normalize_schema, schema_to_json


def test_schema_to_json_is_stable_and_utf8():
    payload = {"z": 1, "info": {"title": "个人化资讯监控"}}

    assert schema_to_json(payload) == '{\n  "info": {\n    "title": "个人化资讯监控"\n  },\n  "z": 1\n}\n'


def test_normalize_schema_removes_runtime_ui_routes():
    schema = {
        "paths": {
            "/": {"get": {}},
            "/{full_path}": {"get": {}},
            "/api/contents": {"get": {}},
            "/health": {"get": {}},
        }
    }

    normalized = normalize_schema(schema)

    assert set(normalized["paths"]) == {"/api/contents", "/health"}
    assert "/" in schema["paths"]
