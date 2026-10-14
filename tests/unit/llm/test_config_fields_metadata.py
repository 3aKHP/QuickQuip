"""契约测试：metadata 的类型标注必须与实际写入校验一致。

防止 ``field_metadata`` 把 ``list[str]`` / ``dict[str, Any]`` 等泛型误判为 string
后，前端按错误类型渲染控件、写回时被 ``check_value`` 拒绝。
"""

from __future__ import annotations

from typing import Any, get_type_hints

import pytest

from quickquip.llm.config_fields import PARAMETER_TYPES, SETTINGS, check_value, metadata

_meta = metadata()

_SAMPLE_BY_TYPE = {
    "array": ["tool_search"],
    "object": {"thinking": {"type": "enabled"}},
    "string": "sample",
    "integer": 1,
    "number": 1.5,
    "boolean": True,
}


def _check_settings_field(section: str, key: str, sample: Any) -> None:
    annotation = get_type_hints(SETTINGS[section])[key]
    check_value(sample, annotation, f"settings.{section}.{key}", f"{section}.{key}")


def test_metadata_generic_types_are_not_strings() -> None:
    assert _meta["settings"]["tools"]["enabled"]["type"] == "array"
    assert _meta["settings"]["tools"]["always_loaded"]["type"] == "array"
    assert _meta["parameters"]["extra_body"]["type"] == "object"


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("tools", "enabled"),
        ("tools", "always_loaded"),
        ("triggers", "default_prefix"),
        ("runtime", "history_limit"),
        ("runtime", "memory_enabled"),
    ],
)
def test_settings_metadata_type_matches_write_validation(section: str, key: str) -> None:
    field = _meta["settings"][section][key]
    sample = _SAMPLE_BY_TYPE[field["type"]]
    _check_settings_field(section, key, sample)


def test_parameters_metadata_type_matches_write_validation() -> None:
    for name, field in _meta["parameters"].items():
        if field["type"] not in _SAMPLE_BY_TYPE:
            continue
        annotation = PARAMETER_TYPES[name]
        sample = field["enum"][0] if field.get("enum") else _SAMPLE_BY_TYPE[field["type"]]
        if isinstance(sample, (int, float)) and not isinstance(sample, bool):
            if isinstance(field.get("minimum"), (int, float)) and sample < field["minimum"]:
                sample = field["minimum"]
            if isinstance(field.get("maximum"), (int, float)) and sample > field["maximum"]:
                sample = field["maximum"]
        check_value(
            sample, annotation,
            f"providers[0].parameters.{name}", name, inherit=True,
        )


def test_nullable_union_unwraps_to_member_type() -> None:
    # Optional[X] / X | None 必须解包为成员类型
    provider = _meta["settings"]["runtime"]["default_provider"]
    assert provider["nullable"] is True
    assert provider["type"] == "string"


def test_parameters_scalar_annotations_unchanged() -> None:
    assert _meta["parameters"]["temperature"]["type"] == "number"
    assert _meta["parameters"]["max_output_tokens"]["type"] == "integer"
    assert _meta["parameters"]["stream_enabled"]["type"] == "boolean"
    assert _meta["parameters"]["reasoning_effort"]["enum"]
