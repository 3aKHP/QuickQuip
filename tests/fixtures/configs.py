"""Configuration text fixtures + a tmp_llm_service factory.

Provides minimal-but-valid TOML/YAML bodies for LLMService bootstrap, plus a
pytest fixture that writes them to a tmp dir and returns a live LLMService.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from plugins.llm_runtime import LLMService


MIN_LLM_CONFIG_TOML = textwrap.dedent(
    """
    [runtime]
    enabled = true
    default_provider = "openai-main"
    default_persona = "default"
    history_limit = 6
    history_max_messages_per_group = 8
    memory_limit = 3
    memory_max_items_per_group = 20
    max_prompt_chars = 1000
    tool_calling_enabled = true
    tool_max_rounds = 2
    tool_max_calls_per_round = 3

    [triggers]
    default_prefix = "/ai"
    allow_prefix = true
    allow_at = true
    empty_prompt_reply = "empty"

    [triggers.auto_search]
    enabled = true
    search_max_calls_per_round = 3

    [tools]
    enabled = []

    [[personas]]
    id = "default"
    display_name = "默认人格"
    system_prompt = "你是测试人格。"
    style_prompt = "短一点。"

    [[providers]]
    id = "openai-main"
    protocol = "openai"
    base_url = "https://example.test/v1"
    api_key_env = "OPENAI_API_KEY"
    default_model = "gpt-test"
    models = ["gpt-test", "gpt-alt"]
    timeout_seconds = 30
    temperature = 0.5
    max_output_tokens = 256
    """
).strip()


VOCAB_YAML = textwrap.dedent(
    """
    核心成员:
      镜子: [镜千翎, 镜子, 哈基镜] # 特别注意不要和王者荣耀的镜混淆

    部分黑话解析: |
      区：群里常见的内部称谓，通常是熟人间的玩笑叫法。
    """
).strip()


IDENTITIES_YAML = textwrap.dedent(
    """
    people:
      - canonical_name: 镜子
        qq_ids:
          - "2002"
        aliases:
          - 镜千翎
          - 哈基镜
        note: 特别注意不要和王者荣耀的镜混淆

      - canonical_name: 4s
        qq_ids: ["4004"]
        aliases: ["Туманность", "哈基四"]
        note: 大部分以四字开头的称呼通常指 4s
    """
).strip()


def write_llm_config_bundle(
    base_dir: Path,
    *,
    config_toml: str = MIN_LLM_CONFIG_TOML,
    vocab_yaml: str = VOCAB_YAML,
    identities_yaml: str = IDENTITIES_YAML,
) -> dict[str, Path]:
    """Write the four canonical files into `base_dir` and return their paths."""
    config_path = base_dir / "llm.toml"
    db_path = base_dir / "llm.db"
    vocab_path = base_dir / "vocab.yaml"
    identity_path = base_dir / "identities.yaml"
    config_path.write_text(config_toml, encoding="utf-8")
    vocab_path.write_text(vocab_yaml, encoding="utf-8")
    identity_path.write_text(identities_yaml, encoding="utf-8")
    return {
        "config_path": config_path,
        "db_path": db_path,
        "vocab_path": vocab_path,
        "identity_path": identity_path,
    }


@pytest.fixture
def llm_config_paths(tmp_path: Path) -> dict[str, Path]:
    return write_llm_config_bundle(tmp_path)


@pytest.fixture
def llm_service(llm_config_paths: dict[str, Path]) -> LLMService:
    return LLMService(**llm_config_paths)
