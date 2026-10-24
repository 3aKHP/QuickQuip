import math
import random

import pytest

from quickquip.config_workspace.codec import load_value, render_value
from quickquip.llm.config_errors import ConfigError


@pytest.mark.parametrize(
    "value",
    [
        None,
        "\n",
        "\n\n",
        "\nhello",
        {"prompt": "\n\nhello\n"},
        {},
        [],
        [None, "", False, 1, 1.0, {}, []],
        {"absent_distinct": {}, "explicit": {"a": None}},
        {"__quickquip_value__": "null"},
        {"__quickquip_value__": "object", "entries": [{"key": "v", "value": None}]},
        -(2**90),
        2**90,
        -0.0,
        '中文\r\n换行\n"""\t\x00',
        {"arrays": [{"x": [None, {"__quickquip_value__": "null"}]}]},
    ],
)
def test_json_value_domain_roundtrip_preserves_types_and_missing(value):
    from quickquip.config_sync.bundle import digest

    decoded = load_value(render_value(value), "test.toml")
    assert digest(decoded) == digest(value)
    if type(value) is float and value == 0:
        assert math.copysign(1, decoded) == math.copysign(1, value)


@pytest.mark.parametrize(
    "text",
    [
        "value = 2024-01-01\n",
        "value = nan\n",
        "value = inf\n",
        'value = { __quickquip_value__ = "unknown" }\n',
        'value = { __quickquip_value__ = "integer", decimal = "01" }\n',
    ],
)
def test_non_json_or_malformed_tagged_values_are_rejected(text):
    with pytest.raises(ConfigError):
        load_value(text.encode(), "bad.toml")


def test_unchanged_text_is_not_reserialized_and_changed_scalar_retains_comments():
    text = b"# heading\n[value]\n# timeout\ntimeout = 30.0 # seconds\nother = 'keep'\n"
    assert render_value({"timeout": 30.0, "other": "keep"}, text) == text
    changed = render_value({"timeout": 31.0, "other": "keep"}, text)
    assert b"# heading\n" in changed and b"# timeout\n" in changed
    assert b"31.0 # seconds" in changed and b"other = 'keep'" in changed


def test_model_table_comments_follow_identity_when_models_are_reordered():
    text = b"""[value]
id = "alpha"
[[value.models]]
model = "first" # first model
context_window = 32000
[[value.models]]
model = "second" # second model
context_window = 64000
"""
    value = load_value(text, "models.toml")
    value["models"].reverse()
    changed = render_value(value, text)
    assert changed.index(b'"second" # second model') < changed.index(b'"first" # first model')
    assert load_value(changed, "models.toml") == value


def test_nested_json_type_changes_roundtrip_through_existing_toml_nodes():
    from quickquip.config_sync.bundle import digest

    rng = random.Random(42)

    def value(depth=0):
        primitives = [None, True, False, 0, 1.0, -0.0, 2**90, "中文\nline", "\nhello", ""]
        if depth >= 3 or rng.randrange(3) == 0:
            return rng.choice(primitives)
        if rng.randrange(2):
            return [value(depth + 1) for _ in range(rng.randrange(4))]
        keys = ["id", "model", "alias", "__quickquip_value__", "x"]
        return {key: value(depth + 1) for key in rng.sample(keys, rng.randrange(5))}

    previous = None
    for _ in range(300):
        expected = value()
        previous = render_value(expected, previous)
        assert digest(load_value(previous, "nested.toml")) == digest(expected)


@pytest.mark.parametrize(
    "before,after",
    [
        ({"a": {}}, {}),
        ({"x": {"nested": {}}}, {"x": {}}),
        ({"a": {"b": {"c": {}}}}, {"a": {}}),
    ],
)
def test_implicit_parent_tables_remain_present_when_cleared(before, after):
    result = render_value(after, render_value(before))
    assert load_value(result, "cleared.toml") == after


def test_container_shape_changes_and_tagged_array_extensions_preserve_values():
    from quickquip.config_sync.bundle import digest

    values = [
        None,
        True,
        0,
        1.0,
        "\nhello",
        {},
        [],
        [None],
        [2**90],
        [[None]],
        {"a": {}},
        {"aliases": []},
        {"aliases": [{"alias": "a", "model": "m"}]},
        [{"a": 1}],
        [1, None, {}],
        {"__quickquip_value__": None},
    ]
    for before in values:
        original = render_value(before)
        for after in values:
            result = render_value(after, original)
            assert digest(load_value(result, "shape.toml")) == digest(after)


def test_cleared_table_array_stays_with_its_parent_after_other_child_headers():
    original = b"""[value]
id="alpha"
[[value.models]]
model="first"
[[value.aliases]]
alias="one"
model="first"
[value.parameters]
temperature=1.0
"""
    expected = load_value(original, "provider.toml")
    expected["aliases"] = []
    assert load_value(render_value(expected, original), "provider.toml") == expected


def test_interleaved_nested_tables_keep_unmodified_comments_during_updates():
    original = b"""[value.a]
x=1 # keep x
[value.b]
y=2 # keep y
[value.a.child]
z=3 # keep z
"""
    expected = load_value(original, "interleaved.toml")
    expected["a"]["x"] = 4
    result = render_value(expected, original)
    assert load_value(result, "interleaved.toml") == expected
    assert b"# keep x" in result and b"# keep y" in result and b"# keep z" in result
    assert result.index(b"[value.a]") < result.index(b"[value.b]")
    expected["a"] = {}
    cleared = render_value(expected, result)
    assert load_value(cleared, "interleaved.toml") == expected
