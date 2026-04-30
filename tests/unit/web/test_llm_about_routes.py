from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from quickquip.app.web.routes import llm_about  # noqa: E402


def _patch_base(monkeypatch, tmp_path: Path) -> Path:
    base = tmp_path / "llm_about"
    monkeypatch.setattr(llm_about, "_LLM_ABOUT_DIR", base)
    return base


def test_list_llm_about_ignores_examples_and_invalid_dirs(monkeypatch, tmp_path):
    base = _patch_base(monkeypatch, tmp_path)
    (base / "_example").mkdir(parents=True)
    (base / "abc").mkdir()
    (base / "1000000001").mkdir()
    (base / "1000000001" / "vocab.yaml").write_text("核心成员:\n  Alice: [阿丽]\n", encoding="utf-8")

    result = llm_about.list_llm_about()

    scopes = [item["scope"] for item in result["scopes"]]
    assert scopes == ["global", "1000000001"]
    assert result["scopes"][1]["files"][0]["exists"] is True


def test_put_llm_about_rejects_invalid_scope(monkeypatch, tmp_path):
    _patch_base(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        llm_about.put_llm_about_file("../config", "vocab", llm_about.LLMAboutContent(content=""))

    assert exc.value.status_code == 422


def test_put_llm_about_rejects_unknown_kind(monkeypatch, tmp_path):
    _patch_base(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        llm_about.put_llm_about_file("global", "secret", llm_about.LLMAboutContent(content=""))

    assert exc.value.status_code == 404


def test_put_llm_about_validates_vocab_shape(monkeypatch, tmp_path):
    _patch_base(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        llm_about.put_llm_about_file("global", "vocab", llm_about.LLMAboutContent(content="foo: bar\n"))

    assert exc.value.status_code == 400


def test_put_llm_about_writes_valid_identity(monkeypatch, tmp_path):
    base = _patch_base(monkeypatch, tmp_path)

    llm_about.put_llm_about_file(
        "1000000001",
        "identities",
        llm_about.LLMAboutContent(
            content=(
                "people:\n"
                "  - canonical_name: Alice\n"
                "    qq_ids: [10001]\n"
                "    aliases: [阿丽]\n"
            )
        ),
    )

    saved = base / "1000000001" / "identities.yaml"
    assert saved.exists()
    assert "canonical_name: Alice" in saved.read_text(encoding="utf-8")


def test_create_llm_about_group_copies_examples(monkeypatch, tmp_path):
    base = _patch_base(monkeypatch, tmp_path)
    (base / "_example").mkdir(parents=True)
    (base / "_example" / "vocab.yaml").write_text("核心成员:\n", encoding="utf-8")
    (base / "_example" / "identities.yaml").write_text("people:\n", encoding="utf-8")

    result = llm_about.create_llm_about_group(
        llm_about.LLMAboutGroupCreate(group_id="1000000001", copy_example=True)
    )

    assert result["scope"] == "1000000001"
    assert (base / "1000000001" / "vocab.yaml").read_text(encoding="utf-8") == "核心成员:\n"
    assert (base / "1000000001" / "identities.yaml").read_text(encoding="utf-8") == "people:\n"
