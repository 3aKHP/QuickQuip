from __future__ import annotations

from pathlib import Path

from quickquip.common.persistence import load_json, save_json


def test_save_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "data.json"
    payload = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}, "utf8": "中文"}
    save_json(path, payload)
    assert load_json(path) == payload


def test_load_missing_returns_none(tmp_path: Path):
    assert load_json(tmp_path / "nope.json") is None


def test_save_creates_missing_parent_dir(tmp_path: Path):
    path = tmp_path / "nested" / "deep" / "data.json"
    save_json(path, {"k": 1})
    assert path.exists()
    assert load_json(path) == {"k": 1}
