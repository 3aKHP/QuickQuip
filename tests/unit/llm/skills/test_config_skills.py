"""[skills] 配置段解析（config.load_llm_config → SkillsConfig）。"""
from __future__ import annotations

import logging

from quickquip.llm.config import SkillsConfig, load_llm_config

from tests.fixtures.configs import MIN_LLM_CONFIG_TOML


def _load(tmp_path, extra_toml: str = ""):
    path = tmp_path / "llm.toml"
    path.write_text(f"{MIN_LLM_CONFIG_TOML}\n{extra_toml}", encoding="utf-8")
    return load_llm_config(path)


def test_skills_defaults_when_section_absent(tmp_path):
    config = _load(tmp_path)
    assert not config.load_error
    assert config.skills == SkillsConfig()
    assert config.skills.enabled is True
    assert config.skills.catalog_dir == ""
    assert config.skills.catalog_max_bytes == 8192
    assert config.skills.resource_max_bytes == 65536
    assert config.skills.search_max_results == 50
    assert config.skills.search_max_output_bytes == 32768
    assert config.skills.script_timeout_ms == 30000
    assert config.skills.script_max_output_bytes == 65536


def test_skills_explicit_values_parsed(tmp_path):
    config = _load(
        tmp_path,
        """
[skills]
enabled = false
catalog_dir = "/srv/skills"
catalog_max_bytes = 4096
resource_max_bytes = 16384
search_max_results = 20
search_max_output_bytes = 8192
script_timeout_ms = 5000
script_max_output_bytes = 4096
""",
    )
    skills = config.skills
    assert skills.enabled is False
    assert skills.catalog_dir == "/srv/skills"
    assert skills.catalog_max_bytes == 4096
    assert skills.resource_max_bytes == 16384
    assert skills.search_max_results == 20
    assert skills.search_max_output_bytes == 8192
    assert skills.script_timeout_ms == 5000
    assert skills.script_max_output_bytes == 4096


def test_skills_invalid_positive_ints_fall_back_with_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        config = _load(
            tmp_path,
            """
[skills]
catalog_max_bytes = "not-a-number"
resource_max_bytes = 0
search_max_results = -3
script_max_output_bytes = true
""",
        )
    skills = config.skills
    assert skills.catalog_max_bytes == 8192
    assert skills.resource_max_bytes == 65536
    assert skills.search_max_results == 50
    assert skills.script_max_output_bytes == 65536
    warnings = [record.getMessage() for record in caplog.records]
    assert any("catalog_max_bytes" in message for message in warnings)
    assert any("resource_max_bytes" in message for message in warnings)
    assert any("search_max_results" in message for message in warnings)
    assert any("script_max_output_bytes" in message for message in warnings)


def test_skills_timeout_clamped_to_max(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        config = _load(
            tmp_path,
            """
[skills]
script_timeout_ms = 999999
""",
        )
    assert config.skills.script_timeout_ms == 120000
    assert any("钳制" in record.getMessage() for record in caplog.records)


def test_skills_missing_keys_keep_defaults(tmp_path):
    config = _load(
        tmp_path,
        """
[skills]
enabled = false
""",
    )
    assert config.skills.enabled is False
    assert config.skills.catalog_max_bytes == 8192
    assert config.skills.script_timeout_ms == 30000
