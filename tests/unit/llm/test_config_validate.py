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


# ---------------------------------------------------------------------------
# builtin_search 解析与协议惰性
# ---------------------------------------------------------------------------

def _gemini_provider(pid: str = "gemini-main", extra: str = "") -> str:
    return f"""
[[providers]]
id = "{pid}"
protocol = "gemini"
base_url = "https://api.example.test/v1beta"
api_key_env = "GEMINI_KEY"
default_model = "gemini-x"
models = ["gemini-x"]
{extra}
"""


def test_builtin_search_defaults_to_false(tmp_path: Path):
    loaded = _load(tmp_path, _good_provider() + _PERSONA)

    assert loaded.providers["good"].builtin_search is False


def test_builtin_search_parsed_on_gemini_provider(tmp_path: Path):
    from quickquip.llm.config import provider_builtin_search_active

    loaded = _load(tmp_path, _gemini_provider(extra="builtin_search = true") + _PERSONA)

    provider = loaded.providers["gemini-main"]
    assert provider.builtin_search is True
    assert provider_builtin_search_active(provider) is True
    assert loaded.load_error is None


def test_builtin_search_on_non_gemini_protocol_warns_and_stays_inert(tmp_path, caplog):
    """非 gemini 协议误配：记 warning、provider 不剪除、生效谓词为 False（请求级惰性）。"""
    import logging

    from quickquip.llm.config import provider_builtin_search_active

    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        loaded = _load(
            tmp_path,
            _good_provider().replace('models = ["gpt-x"]', 'models = ["gpt-x"]\nbuiltin_search = true')
            + _PERSONA,
        )

    provider = loaded.providers["good"]
    assert provider.builtin_search is True  # 保留原始配置意图，仅生效层面惰性
    assert provider_builtin_search_active(provider) is False
    assert "good" in loaded.providers  # 不因该键误配剪除 provider
    assert any("builtin_search" in record.message for record in caplog.records)


def test_runtime_retry_config_stamped_to_providers(tmp_path: Path):
    """[runtime] 重试三键解析后统一盖章到所有 provider（旁路调用零改动继承）。"""
    loaded = _load(
        tmp_path,
        """
        [runtime]
        enabled = true
        default_provider = "good"
        retry_max_attempts = 5
        retry_base_delay = 2.5
        retry_jitter = 0.8
        """
        + _good_provider()
        + _PERSONA,
    )

    provider = loaded.providers["good"]
    assert provider.retry_max_attempts == 5
    assert provider.retry_base_delay == 2.5
    assert provider.retry_jitter == 0.8
    assert loaded.runtime.retry_jitter == 0.8


def test_runtime_retry_defaults_without_keys(tmp_path: Path):
    """未配置重试键时，runtime 与 provider 均落默认策略。"""
    loaded = _load(tmp_path, _good_provider() + _PERSONA)

    provider = loaded.providers["good"]
    assert provider.retry_max_attempts == 3
    assert provider.retry_base_delay == 1.0
    assert provider.retry_jitter == 0.5


def test_retry_jitter_clamped_to_unit_range(tmp_path: Path):
    """retry_jitter 钳制到 [0, 1]。"""
    loaded = _load(
        tmp_path,
        """
        [runtime]
        retry_jitter = 3.0
        """
        + _good_provider()
        + _PERSONA,
    )

    assert loaded.runtime.retry_jitter == 1.0
    assert loaded.providers["good"].retry_jitter == 1.0


def test_epoch_params_defaults_when_unconfigured(tmp_path: Path):
    loaded = _load(tmp_path, _good_provider() + _PERSONA)

    assert loaded.runtime.epoch_context_tokens == 8000
    assert loaded.runtime.epoch_cold_idle_seconds == 300
    assert loaded.runtime.epoch_cold_target_tokens == 4000
    assert loaded.runtime.epoch_cold_trigger_tokens == 5000
    assert loaded.runtime.epoch_hot_target_tokens == 32000
    assert loaded.runtime.epoch_cap_tokens == 64000
    provider = loaded.providers["good"]
    assert provider.epoch_context_tokens is None  # 未配置 = 继承 runtime
    params = loaded.resolve_epoch_params(provider)
    assert params.context_tokens == 8000
    assert params.cold_idle_seconds == 300
    assert params.cap_tokens == 64000


def test_epoch_params_runtime_parsed(tmp_path: Path):
    loaded = _load(
        tmp_path,
        """
        [runtime]
        enabled = true
        default_provider = "good"
        epoch_context_tokens = 6000
        epoch_cold_idle_seconds = 600
        """
        + _good_provider()
        + _PERSONA,
    )

    params = loaded.resolve_epoch_params(loaded.providers["good"])
    assert params.context_tokens == 6000
    assert params.cold_idle_seconds == 600
    assert params.cold_target_tokens == 4000  # 未配置的键保持默认


def test_epoch_params_provider_override_wins(tmp_path: Path):
    loaded = _load(
        tmp_path,
        """
        [runtime]
        enabled = true
        default_provider = "good"
        epoch_cold_idle_seconds = 300
        """
        + _good_provider().replace(
            'models = ["gpt-x"]',
            'models = ["gpt-x"]\nepoch_cold_idle_seconds = 21600\nepoch_cap_tokens = 128000',
        )
        + _PERSONA,
    )

    provider = loaded.providers["good"]
    assert provider.epoch_cold_idle_seconds == 21600
    params = loaded.resolve_epoch_params(provider)
    assert params.cold_idle_seconds == 21600  # provider 覆盖优先
    assert params.cap_tokens == 128000
    assert params.cold_target_tokens == 4000  # 未覆盖的键继承 runtime


def test_epoch_params_invalid_runtime_relation_falls_back_to_defaults(tmp_path: Path, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        loaded = _load(
            tmp_path,
            """
            [runtime]
            enabled = true
            default_provider = "good"
            epoch_cold_target_tokens = 9000
            epoch_cold_trigger_tokens = 5000
            """
            + _good_provider()
            + _PERSONA,
        )

    params = loaded.resolve_epoch_params(loaded.providers["good"])
    assert params.cold_target_tokens == 4000  # 关系非法（target >= trigger）回退内置默认
    assert params.cold_trigger_tokens == 5000
    assert any("epoch" in record.message for record in caplog.records)


def test_epoch_params_invalid_provider_override_falls_back_to_runtime(tmp_path: Path, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        loaded = _load(
            tmp_path,
            """
            [runtime]
            enabled = true
            default_provider = "good"
            epoch_cold_idle_seconds = 600
            """
            + _good_provider().replace(
                'models = ["gpt-x"]',
                'models = ["gpt-x"]\nepoch_cold_target_tokens = 100\nepoch_cold_trigger_tokens = 50',
            )
            + _PERSONA,
        )

    params = loaded.resolve_epoch_params(loaded.providers["good"])
    assert params.cold_target_tokens == 4000  # provider 覆盖非法回退 runtime（此处 runtime 即默认）
    assert params.cold_idle_seconds == 600  # runtime 合法值不受牵连
    assert any("epoch" in record.message for record in caplog.records)


def test_epoch_unknown_keys_ignored(tmp_path: Path):
    loaded = _load(
        tmp_path,
        """
        [runtime]
        enabled = true
        default_provider = "good"
        epoch_future_knob = 123
        """
        + _good_provider().replace(
            'models = ["gpt-x"]',
            'models = ["gpt-x"]\nepoch_another_future_knob = "x"',
        )
        + _PERSONA,
    )

    assert loaded.load_error is None
    assert loaded.resolve_epoch_params(loaded.providers["good"]).context_tokens == 8000


def test_epoch_params_provider_override_float_coerced(tmp_path: Path):
    """TOML 浮点字面量无损截断为 int——键级笔误不得扩大为整 provider 剪除。"""
    loaded = _load(
        tmp_path,
        _good_provider().replace(
            'models = ["gpt-x"]',
            'models = ["gpt-x"]\nepoch_cold_idle_seconds = 21600.0',
        )
        + _PERSONA,
    )

    assert "good" in loaded.providers
    assert loaded.providers["good"].epoch_cold_idle_seconds == 21600


def test_epoch_params_provider_override_garbage_falls_back_to_runtime(tmp_path: Path, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        loaded = _load(
            tmp_path,
            _good_provider().replace(
                'models = ["gpt-x"]',
                'models = ["gpt-x"]\nepoch_cap_tokens = "abc"',
            )
            + _PERSONA,
        )

    provider = loaded.providers["good"]  # provider 不被剪除
    assert provider.epoch_cap_tokens is None  # 该键回退继承 runtime
    assert loaded.resolve_epoch_params(provider).cap_tokens == 64000
    assert any("epoch" in record.message for record in caplog.records)


def test_recent_context_defaults_when_unconfigured(tmp_path: Path):
    loaded = _load(tmp_path, _good_provider() + _PERSONA)

    assert loaded.runtime.recent_context_token_budget == 800
    assert loaded.runtime.recent_context_floor_seconds == 300


def test_recent_context_runtime_parsed(tmp_path: Path):
    loaded = _load(
        tmp_path,
        """
        [runtime]
        enabled = true
        default_provider = "good"
        recent_context_token_budget = 1200
        recent_context_floor_seconds = 120
        """
        + _good_provider()
        + _PERSONA,
    )

    assert loaded.runtime.recent_context_token_budget == 1200
    assert loaded.runtime.recent_context_floor_seconds == 120


def test_recent_context_invalid_values_fall_back_with_warning(tmp_path, caplog):
    """budget<=0 / floor<0 回退默认并告警；floor=0 合法（纯增量、无保底窗）。"""
    import logging

    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        loaded = _load(
            tmp_path,
            """
            [runtime]
            enabled = true
            default_provider = "good"
            recent_context_token_budget = 0
            recent_context_floor_seconds = -5
            """
            + _good_provider()
            + _PERSONA,
        )

    assert loaded.runtime.recent_context_token_budget == 800
    assert loaded.runtime.recent_context_floor_seconds == 300
    assert any("recent_context_token_budget" in r.message for r in caplog.records)
    assert any("recent_context_floor_seconds" in r.message for r in caplog.records)


def test_recent_context_floor_zero_is_valid(tmp_path):
    loaded = _load(
        tmp_path,
        """
        [runtime]
        enabled = true
        default_provider = "good"
        recent_context_floor_seconds = 0
        """
        + _good_provider()
        + _PERSONA,
    )

    assert loaded.runtime.recent_context_floor_seconds == 0
