"""钉住 ``load_llm_config`` / ``_validate_and_fix_config`` 的剪除与回退语义。

核心契约：llm 配置校验是"剪除坏项、尽力可用"——单个坏 provider 被跳过并记日志，
其余 provider 继续可用；跨引用缺失聚合进 ``load_error``（``"; "`` 连接）。
对照组：``generation`` 配置校验是首个错误 fail-fast，两者语义不得被无意对齐。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from quickquip.generation.config import load_generation_config
from quickquip.llm.config import load_llm_config

_PERSONA = """
[[personas]]
id = "p1"
display_name = "P1"
system_prompt = "hello"

[[personas]]
id = "p2"
display_name = "P2"
system_prompt = "world"
"""


def _good_provider(pid: str = "good") -> str:
    return f"""
[[providers]]
id = "{pid}"
protocol = "openai"
base_url = "https://api.example.test/v1"
api_key_env = "{pid.upper()}_KEY"
default_model = "gpt-x"
models = ["gpt-x"]
"""


def _load(tmp_path: Path, body: str):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(textwrap.dedent(body).strip(), encoding="utf-8")
    return load_llm_config(config_path)


def test_bad_default_provider_pruned_and_default_reselected_with_error(tmp_path: Path):
    """默认 provider 因校验失败被剪除后：回退到存活 provider 并记入 load_error（fail-visible）。"""
    loaded = _load(
        tmp_path,
        """
        [runtime]
        enabled = true
        default_provider = "bad"

        [[providers]]
        id = "bad"
        protocol = "weird-proto"
        base_url = "https://bad.example.test/v1"
        api_key_env = "BAD_KEY"
        default_model = "m1"
        models = ["m1"]
        """
        + _good_provider()
        + _PERSONA,
    )

    assert set(loaded.providers) == {"good"}
    assert loaded.runtime.default_provider == "good"
    # 剪除导致的回退不再静默：与 default_provider 指向不存在 id 的语义一致
    assert loaded.load_error is not None
    assert "已被剪除" in loaded.load_error
    assert "bad" in loaded.load_error
    assert "good" in loaded.load_error


def test_unknown_default_provider_falls_back_with_error(tmp_path: Path):
    """default_provider 指向从未存在的 id：回退到首个 provider 并记入 load_error。"""
    loaded = _load(
        tmp_path,
        """
        [runtime]
        default_provider = "ghost"
        """
        + _good_provider()
        + _PERSONA,
    )

    assert loaded.runtime.default_provider == "good"
    assert loaded.load_error is not None
    assert "ghost" in loaded.load_error
    assert "不存在" in loaded.load_error


def test_all_providers_pruned_aggregates_load_error(tmp_path: Path):
    """全部 provider 被剪除：providers 清空、default_provider 置 None、聚合错误。"""
    loaded = _load(
        tmp_path,
        """
        [[providers]]
        id = "bad1"
        protocol = "openai"
        api_key_env = "K1"
        default_model = "m1"
        models = ["m1"]

        [[providers]]
        id = "bad2"
        protocol = "claude"
        base_url = "https://bad2.example.test"
        api_key_env = "K2"
        default_model = "m2"
        models = ["m2"]
        cache_ttl = "2h"
        """
        + _PERSONA,
    )

    assert loaded.providers == {}
    assert loaded.runtime.default_provider is None
    assert loaded.load_error == "全部 2 个 provider 均被跳过：bad1, bad2"


def test_missing_default_persona_auto_selects_first(tmp_path: Path):
    """未设置 default_persona：静默选首个人格，不记错误。"""
    loaded = _load(tmp_path, _good_provider() + _PERSONA)

    assert loaded.runtime.default_persona == "p1"
    assert loaded.load_error is None


def test_unknown_default_persona_falls_back_with_error(tmp_path: Path):
    """default_persona 指向不存在的人格：回退到首个人格并记入 load_error。"""
    loaded = _load(
        tmp_path,
        """
        [runtime]
        default_persona = "ghost"
        """
        + _good_provider()
        + _PERSONA,
    )

    assert loaded.runtime.default_persona == "p1"
    assert loaded.load_error is not None
    assert "ghost" in loaded.load_error
    assert "p1" in loaded.load_error


def test_cascade_and_image_preprocessing_missing_provider_aggregated(tmp_path: Path):
    """image_preprocessing 与各 model_cascade 引用缺失 provider：逐条聚合进 load_error。

    "@default/..." 与指向存活 provider 的条目不产生错误；其余按固定顺序以 "; " 连接。
    """
    loaded = _load(
        tmp_path,
        """
        [image_preprocessing]
        enabled = true
        provider_id = "ghost_img"
        model = "m"

        [daily_summary]
        enabled = true
        model_cascade = ["ghost_sum/m1", "@default/m2", "good/m3"]

        [weekly_report]
        enabled = true
        model_cascade = ["ghost_week/m"]
        """
        + _good_provider()
        + _PERSONA,
    )

    assert set(loaded.providers) == {"good"}
    assert loaded.runtime.default_provider == "good"
    assert loaded.load_error == (
        "image_preprocessing.provider_id 'ghost_img' 不存在; "
        "daily_summary.model_cascade 引用了不存在的 provider 'ghost_sum'; "
        "weekly_report.model_cascade 引用了不存在的 provider 'ghost_week'"
    )


def test_disabled_feature_cascade_not_validated(tmp_path: Path):
    """已禁用功能的 model_cascade 不参与校验：ghost 引用不污染 load_error；
    只开启其中一个功能时，load_error 恰好只含该功能的条目。"""
    loaded = _load(
        tmp_path,
        """
        [daily_summary]
        model_cascade = ["ghost_sum/m1"]

        [weekly_report]
        model_cascade = ["ghost_week/m"]
        """
        + _good_provider()
        + _PERSONA,
    )
    assert loaded.load_error is None

    loaded_partial = _load(
        tmp_path,
        """
        [daily_summary]
        enabled = true
        model_cascade = ["ghost_sum/m1"]

        [weekly_report]
        model_cascade = ["ghost_week/m"]
        """
        + _good_provider()
        + _PERSONA,
    )
    assert loaded_partial.load_error == (
        "daily_summary.model_cascade 引用了不存在的 provider 'ghost_sum'"
    )


def test_llm_salvages_where_generation_fails_fast(tmp_path: Path):
    """跨域语义差异：llm 剪除坏 provider 继续可用；generation 首个错误即置 load_error。

    两种策略各有取舍（llm 多 provider 冗余 vs generation 单功能整体开关），
    此用例防止将来被无意"对齐"成同一种语义。
    """
    llm_loaded = _load(
        tmp_path,
        """
        [[providers]]
        id = "bad"
        protocol = "weird-proto"
        base_url = "https://bad.example.test/v1"
        api_key_env = "BAD_KEY"
        default_model = "m1"
        models = ["m1"]
        """
        + _good_provider()
        + _PERSONA,
    )
    # llm：坏项被剪除，剩余配置视为健康
    assert set(llm_loaded.providers) == {"good"}
    assert llm_loaded.load_error is None

    generation_path = tmp_path / "generation.toml"
    generation_path.write_text(
        textwrap.dedent(
            """
            [image]
            enabled = true

            [[image.providers]]
            id = "bad"
            protocol = "unknown_images"
            base_url = "https://bad.example.test/v1"
            api_key_env = "BAD_KEY"

            [[image.providers]]
            id = "good"
            protocol = "openai_images"
            base_url = "https://api.example.test/v1"
            api_key_env = "GOOD_KEY"

            [[image.providers.models]]
            id = "img-1"
            model = "img-model"
            """
        ).strip(),
        encoding="utf-8",
    )
    gen_loaded = load_generation_config(generation_path)
    # generation：不剪除任何 provider，首个错误即 fail-fast 置 load_error
    assert set(gen_loaded.image.providers) == {"bad", "good"}
    assert gen_loaded.load_error is not None
    assert "bad" in gen_loaded.load_error
    assert "未知协议" in gen_loaded.load_error


def test_empty_personas_is_fatal_load_error(tmp_path: Path):
    """provider 正常但完全没有人格（无 [[personas]] 且 personas/ 目录不存在）时，
    load_error 置为 fatal 且校验 early-return——不得被重构改为静默默认人格。"""
    loaded = _load(
        tmp_path,
        """
        [runtime]
        enabled = true
        """
        + _good_provider(),
    )
    assert loaded.load_error == "LLM 配置中没有可用的人格"
    assert loaded.personas == {}
    # fatal 后 early-return：provider 已解析保留，但配置整体不可用
    assert set(loaded.providers) == {"good"}
    assert not loaded.is_available
