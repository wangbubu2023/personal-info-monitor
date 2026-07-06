from scripts.export_openapi import schema_to_json


def test_schema_to_json_is_stable_and_utf8():
    payload = {"z": 1, "info": {"title": "个人化资讯监控"}}

    assert schema_to_json(payload) == '{\n  "info": {\n    "title": "个人化资讯监控"\n  },\n  "z": 1\n}\n'
