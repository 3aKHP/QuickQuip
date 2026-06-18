from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib

from quickquip.common.config_utils import as_bool, as_dict, expand_env_value
from quickquip.common.paths import CONFIG_GENERATION_TOML, CONFIG_LLM_TOML


DEFAULT_GENERATION_CONFIG_PATH = CONFIG_GENERATION_TOML
DEFAULT_LEGACY_LLM_CONFIG_PATH = CONFIG_LLM_TOML
_SUPPORTED_IMAGE_PROTOCOLS = {"openai_images", "gemini_imagen", "minimax_images"}
_SUPPORTED_AUDIO_PROTOCOLS = {"minimax_t2a_http", "minimax_t2a_async"}
_SUPPORTED_MUSIC_PROTOCOLS = {"minimax_music"}
_SUPPORTED_ASR_PROTOCOLS = {"openai_transcriptions"}


class _ResolveModelMixin:
    """为各模式 generation config 容器提供统一的 resolve_model 查找逻辑。

    混入类需具备 ``default_model`` (str) 和 ``models`` (dict[str, Any]) 属性。
    四个模式（image/audio/music/asr）的 resolve_model 逐字节相同，集中于此避免漂移。

    返回类型标注为 ``Any``：由于 ``models`` 在 mixin 层是 ``dict[str, Any]``，
    具体的 ``ResolvedXxxModel`` 类型信息在子类才确定。各子类的调用方（如 service.py）
    已有显式返回类型注解，类型安全在消费侧保证。
    """

    default_model: str
    models: dict[str, Any]

    def resolve_model(self, model_id: str | None = None) -> Any:
        candidate = (model_id or self.default_model).strip()
        if not candidate:
            return None
        return self.models.get(candidate)


@dataclass(slots=True)
class ImageModelConfig:
    id: str
    model: str
    label: str = ""
    size: str = "1024x1024"
    quality: str = "standard"
    response_format: str = "b64_json"


@dataclass(slots=True)
class ImageProviderConfig:
    id: str
    protocol: str
    base_url: str
    api_key_env: str
    timeout_seconds: float = 120.0
    default_model: str = ""
    models: list[ImageModelConfig] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedImageModel:
    id: str
    model_config: ImageModelConfig
    provider: ImageProviderConfig


@dataclass(slots=True)
class ImageGenerationConfig(_ResolveModelMixin):
    enabled: bool = False
    default_model: str = ""
    prompt_blocklist: list[str] = field(default_factory=list)
    providers: dict[str, ImageProviderConfig] = field(default_factory=dict)
    models: dict[str, ResolvedImageModel] = field(default_factory=dict)


@dataclass(slots=True)
class AudioModelConfig:
    id: str
    model: str
    label: str = ""
    voice_id: str = ""
    speed: float = 1.0
    vol: float = 1.0
    pitch: int = 0
    emotion: str = ""
    sample_rate: int = 32000
    bitrate: int = 128000
    format: str = "mp3"
    channel: int = 1
    language_boost: str = ""
    subtitle_enable: bool = False
    output_format: str = "hex"
    pronunciation_dict: dict[str, Any] = field(default_factory=dict)
    voice_modify: dict[str, Any] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AudioProviderConfig:
    id: str
    protocol: str
    base_url: str
    api_key_env: str
    timeout_seconds: float = 120.0
    default_model: str = ""
    models: list[AudioModelConfig] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedAudioModel:
    id: str
    model_config: AudioModelConfig
    provider: AudioProviderConfig


@dataclass(slots=True)
class AudioGenerationConfig(_ResolveModelMixin):
    enabled: bool = False
    default_model: str = ""
    prompt_blocklist: list[str] = field(default_factory=list)
    providers: dict[str, AudioProviderConfig] = field(default_factory=dict)
    models: dict[str, ResolvedAudioModel] = field(default_factory=dict)


@dataclass(slots=True)
class MusicModelConfig:
    id: str
    model: str
    label: str = ""
    sample_rate: int = 44100
    bitrate: int = 256000
    format: str = "mp3"
    output_format: str = "hex"
    add_watermark: bool = False
    lyrics_optimizer: bool = False
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MusicProviderConfig:
    id: str
    protocol: str
    base_url: str
    api_key_env: str
    timeout_seconds: float = 180.0
    default_model: str = ""
    models: list[MusicModelConfig] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedMusicModel:
    id: str
    model_config: MusicModelConfig
    provider: MusicProviderConfig


@dataclass(slots=True)
class MusicGenerationConfig(_ResolveModelMixin):
    enabled: bool = False
    default_model: str = ""
    prompt_blocklist: list[str] = field(default_factory=list)
    providers: dict[str, MusicProviderConfig] = field(default_factory=dict)
    models: dict[str, ResolvedMusicModel] = field(default_factory=dict)


@dataclass(slots=True)
class AsrModelConfig:
    id: str
    model: str
    label: str = ""
    language: str = ""
    prompt: str = ""
    response_format: str = "json"
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AsrProviderConfig:
    id: str
    protocol: str
    base_url: str
    api_key_env: str
    timeout_seconds: float = 60.0
    default_model: str = ""
    models: list[AsrModelConfig] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedAsrModel:
    id: str
    model_config: AsrModelConfig
    provider: AsrProviderConfig


@dataclass(slots=True)
class AsrConfig(_ResolveModelMixin):
    enabled: bool = False
    default_model: str = ""
    max_audio_bytes: int = 25 * 1024 * 1024
    providers: dict[str, AsrProviderConfig] = field(default_factory=dict)
    models: dict[str, ResolvedAsrModel] = field(default_factory=dict)


@dataclass(slots=True)
class GenerationConfig:
    image: ImageGenerationConfig = field(default_factory=ImageGenerationConfig)
    audio: AudioGenerationConfig = field(default_factory=AudioGenerationConfig)
    music: MusicGenerationConfig = field(default_factory=MusicGenerationConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    load_error: str | None = None
    source_path: Path | None = None
    source_kind: str = "generation"

def _read_prompt_blocklist(raw: dict[str, Any]) -> list[str]:
    """从 raw 配置读取 prompt_blocklist，统一做 strip + lower + 去空。"""
    return [
        str(word).strip().lower()
        for word in raw.get("prompt_blocklist", [])
        if str(word).strip()
    ]


def _read_generation_section_data(
    raw: dict[str, Any],
    *,
    model_factory: Callable[[dict[str, Any]], Any],
    provider_factory: Callable[[str, dict[str, Any], list[Any]], Any],
    resolved_cls: type,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """解析 providers/models 的通用骨架，供四个 _read_xxx 复用。

    遍历 ``raw["providers"]``，对每个 provider：
    - 通过 *model_factory* 从 model_entry 构造各模式的 ModelConfig（含特有字段）
    - 通过 *provider_factory* 把 provider 通用字段 + model_list 绑定为具体 ProviderConfig
    - 通过 *resolved_cls* 构造 ResolvedXxxModel（四个 Resolved 类构造签名同为
      ``(id, model_config, provider)``，故直接传 class 替代逐模式 lambda）

    provider 的通用字段（id/protocol/base_url/api_key_env/timeout/default_model/
    headers/user_agent/extra_body）在四个模式间完全同构，差异仅是 protocol 和
    timeout 的默认值——这两个差异由 provider_factory 内部的 ``.get(key, default)``
    各自处理，本骨架不感知。

    契约：skeleton 对 model_id/model_name 做非空预校验（决定是否跳过该 entry），
    之后将完整 model_entry 交给 *model_factory*。factory 必须从同一 entry 提取
    id/model 字段构造 ModelConfig，不得改用其他 key——否则预校验与实际构造不一致。

    返回 (providers, models, default_model)。
    """
    providers: dict[str, Any] = {}
    models: dict[str, Any] = {}
    raw_providers = raw.get("providers", [])
    for provider_entry in raw_providers if isinstance(raw_providers, list) else []:
        provider_entry = expand_env_value(provider_entry)
        provider_id = str(provider_entry.get("id", "")).strip()
        if not provider_id:
            continue

        model_list: list[Any] = []
        for model_entry in provider_entry.get("models", []) or []:
            model_entry = expand_env_value(model_entry)
            model_id = str(model_entry.get("id", "")).strip()
            model_name = str(model_entry.get("model", "")).strip()
            if not model_id or not model_name:
                continue
            model = model_factory(model_entry)
            model_list.append(model)

        provider = provider_factory(provider_id, provider_entry, model_list)
        providers[provider_id] = provider

        for model in model_list:
            models[model.id] = resolved_cls(id=model.id, model_config=model, provider=provider)

    default_model = str(raw.get("default_model", "")).strip()
    if not default_model and models:
        default_model = next(iter(models))

    return providers, models, default_model


def _build_image_model(entry: dict[str, Any]) -> ImageModelConfig:
    return ImageModelConfig(
        id=str(entry.get("id", "")).strip(),
        model=str(entry.get("model", "")).strip(),
        label=str(entry.get("label", "")).strip(),
        size=str(entry.get("size", "1024x1024")).strip() or "1024x1024",
        quality=str(entry.get("quality", "standard")).strip() or "standard",
        response_format=str(entry.get("response_format", "b64_json")).strip(),
    )


def _build_audio_model(entry: dict[str, Any]) -> AudioModelConfig:
    return AudioModelConfig(
        id=str(entry.get("id", "")).strip(),
        model=str(entry.get("model", "")).strip(),
        label=str(entry.get("label", "")).strip(),
        voice_id=str(entry.get("voice_id", "")).strip(),
        speed=float(entry.get("speed", 1.0)),
        vol=float(entry.get("vol", 1.0)),
        pitch=int(float(entry.get("pitch", 0))),
        emotion=str(entry.get("emotion", "")).strip(),
        sample_rate=int(entry.get("sample_rate", 32000)),
        bitrate=int(entry.get("bitrate", 128000)),
        format=str(entry.get("format", "mp3")).strip() or "mp3",
        channel=int(entry.get("channel", 1)),
        language_boost=str(entry.get("language_boost", "")).strip(),
        subtitle_enable=as_bool(entry.get("subtitle_enable", False), default=False),
        output_format=str(entry.get("output_format", "hex")).strip() or "hex",
        pronunciation_dict=expand_env_value(as_dict(entry.get("pronunciation_dict"))),
        voice_modify=expand_env_value(as_dict(entry.get("voice_modify"))),
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
    )


def _build_music_model(entry: dict[str, Any]) -> MusicModelConfig:
    return MusicModelConfig(
        id=str(entry.get("id", "")).strip(),
        model=str(entry.get("model", "")).strip(),
        label=str(entry.get("label", "")).strip(),
        sample_rate=int(entry.get("sample_rate", 44100)),
        bitrate=int(entry.get("bitrate", 256000)),
        format=str(entry.get("format", "mp3")).strip() or "mp3",
        output_format=str(entry.get("output_format", "hex")).strip() or "hex",
        add_watermark=as_bool(entry.get("add_watermark", False), default=False),
        lyrics_optimizer=as_bool(entry.get("lyrics_optimizer", False), default=False),
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
    )


def _build_asr_model(entry: dict[str, Any]) -> AsrModelConfig:
    return AsrModelConfig(
        id=str(entry.get("id", "")).strip(),
        model=str(entry.get("model", "")).strip(),
        label=str(entry.get("label", "")).strip(),
        language=str(entry.get("language", "")).strip(),
        prompt=str(entry.get("prompt", "")).strip(),
        response_format=str(entry.get("response_format", "json")).strip() or "json",
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
    )


def _image_provider_factory(pid: str, entry: dict[str, Any], models: list[Any]) -> ImageProviderConfig:
    return ImageProviderConfig(
        id=pid,
        protocol=str(entry.get("protocol", "openai_images")).strip() or "openai_images",
        base_url=str(entry.get("base_url", "")).strip(),
        api_key_env=str(entry.get("api_key_env", "")).strip(),
        timeout_seconds=float(entry.get("timeout_seconds", 120)),
        default_model=str(entry.get("default_model", "")).strip(),
        models=models,
        headers={str(k): str(v) for k, v in as_dict(entry.get("headers")).items()},
        user_agent=str(entry.get("user_agent", "")).strip(),
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
    )


def _audio_provider_factory(pid: str, entry: dict[str, Any], models: list[Any]) -> AudioProviderConfig:
    return AudioProviderConfig(
        id=pid,
        protocol=str(entry.get("protocol", "minimax_t2a_http")).strip() or "minimax_t2a_http",
        base_url=str(entry.get("base_url", "")).strip(),
        api_key_env=str(entry.get("api_key_env", "")).strip(),
        timeout_seconds=float(entry.get("timeout_seconds", 120)),
        default_model=str(entry.get("default_model", "")).strip(),
        models=models,
        headers={str(k): str(v) for k, v in as_dict(entry.get("headers")).items()},
        user_agent=str(entry.get("user_agent", "")).strip(),
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
    )


def _music_provider_factory(pid: str, entry: dict[str, Any], models: list[Any]) -> MusicProviderConfig:
    return MusicProviderConfig(
        id=pid,
        protocol=str(entry.get("protocol", "minimax_music")).strip() or "minimax_music",
        base_url=str(entry.get("base_url", "")).strip(),
        api_key_env=str(entry.get("api_key_env", "")).strip(),
        timeout_seconds=float(entry.get("timeout_seconds", 180)),
        default_model=str(entry.get("default_model", "")).strip(),
        models=models,
        headers={str(k): str(v) for k, v in as_dict(entry.get("headers")).items()},
        user_agent=str(entry.get("user_agent", "")).strip(),
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
    )


def _asr_provider_factory(pid: str, entry: dict[str, Any], models: list[Any]) -> AsrProviderConfig:
    return AsrProviderConfig(
        id=pid,
        protocol=str(entry.get("protocol", "openai_transcriptions")).strip() or "openai_transcriptions",
        base_url=str(entry.get("base_url", "")).strip(),
        api_key_env=str(entry.get("api_key_env", "")).strip(),
        timeout_seconds=float(entry.get("timeout_seconds", 60)),
        default_model=str(entry.get("default_model", "")).strip(),
        models=models,
        headers={str(k): str(v) for k, v in as_dict(entry.get("headers")).items()},
        user_agent=str(entry.get("user_agent", "")).strip(),
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
    )


def _read_image_generation(raw: dict[str, Any]) -> ImageGenerationConfig:
    providers, models, default_model = _read_generation_section_data(
        raw,
        model_factory=_build_image_model,
        provider_factory=_image_provider_factory,
        resolved_cls=ResolvedImageModel,
    )
    return ImageGenerationConfig(
        enabled=as_bool(raw.get("enabled", False), default=False),
        default_model=default_model,
        prompt_blocklist=_read_prompt_blocklist(raw),
        providers=providers,
        models=models,
    )


def _read_audio_generation(raw: dict[str, Any]) -> AudioGenerationConfig:
    providers, models, default_model = _read_generation_section_data(
        raw,
        model_factory=_build_audio_model,
        provider_factory=_audio_provider_factory,
        resolved_cls=ResolvedAudioModel,
    )
    return AudioGenerationConfig(
        enabled=as_bool(raw.get("enabled", False), default=False),
        default_model=default_model,
        prompt_blocklist=_read_prompt_blocklist(raw),
        providers=providers,
        models=models,
    )


def _read_music_generation(raw: dict[str, Any]) -> MusicGenerationConfig:
    providers, models, default_model = _read_generation_section_data(
        raw,
        model_factory=_build_music_model,
        provider_factory=_music_provider_factory,
        resolved_cls=ResolvedMusicModel,
    )
    return MusicGenerationConfig(
        enabled=as_bool(raw.get("enabled", False), default=False),
        default_model=default_model,
        prompt_blocklist=_read_prompt_blocklist(raw),
        providers=providers,
        models=models,
    )


def _read_asr(raw: dict[str, Any]) -> AsrConfig:
    providers, models, default_model = _read_generation_section_data(
        raw,
        model_factory=_build_asr_model,
        provider_factory=_asr_provider_factory,
        resolved_cls=ResolvedAsrModel,
    )
    return AsrConfig(
        enabled=as_bool(raw.get("enabled", False), default=False),
        default_model=default_model,
        max_audio_bytes=max(1, int(raw.get("max_audio_bytes", 25 * 1024 * 1024))),
        providers=providers,
        models=models,
    )




def _read_generation_section(
    data: dict[str, Any],
    section_name: str,
    legacy_section_name: str,
    reader,
):
    generation = expand_env_value(as_dict(data.get("generation")))
    if generation:
        section = expand_env_value(as_dict(generation.get(section_name)))
        if section:
            return reader(section)

    section = expand_env_value(as_dict(data.get(section_name)))
    if section:
        return reader(section)

    legacy_section = expand_env_value(as_dict(data.get(legacy_section_name)))
    if legacy_section:
        return reader(legacy_section)

    return reader({})


def _read_image_generation_section(data: dict[str, Any]) -> ImageGenerationConfig:
    return _read_generation_section(data, "image", "image_generation", _read_image_generation)


def _read_audio_generation_section(data: dict[str, Any]) -> AudioGenerationConfig:
    return _read_generation_section(data, "audio", "audio_generation", _read_audio_generation)


def _read_music_generation_section(data: dict[str, Any]) -> MusicGenerationConfig:
    return _read_generation_section(data, "music", "music_generation", _read_music_generation)


def _read_asr_section(data: dict[str, Any]) -> AsrConfig:
    return _read_generation_section(data, "asr", "asr", _read_asr)


def _validate_generation_config(config: GenerationConfig) -> GenerationConfig:
    image = config.image
    for provider in image.providers.values():
        if provider.protocol not in _SUPPORTED_IMAGE_PROTOCOLS:
            config.load_error = (
                f"图片 provider {provider.id} 使用了未知协议：{provider.protocol}"
            )
            return config
        if not provider.base_url:
            config.load_error = f"图片 provider {provider.id} 缺少 base_url"
            return config
        if not provider.api_key_env:
            config.load_error = f"图片 provider {provider.id} 缺少 api_key_env"
            return config
    if image.default_model and image.default_model not in image.models:
        config.load_error = f"图片默认模型不存在：{image.default_model}"
        return config

    audio = config.audio
    for provider in audio.providers.values():
        if provider.protocol not in _SUPPORTED_AUDIO_PROTOCOLS:
            config.load_error = (
                f"音频 provider {provider.id} 使用了未知协议：{provider.protocol}"
            )
            return config
        if not provider.base_url:
            config.load_error = f"音频 provider {provider.id} 缺少 base_url"
            return config
        if not provider.api_key_env:
            config.load_error = f"音频 provider {provider.id} 缺少 api_key_env"
            return config
    if audio.default_model and audio.default_model not in audio.models:
        config.load_error = f"音频默认模型不存在：{audio.default_model}"
        return config

    music = config.music
    for provider in music.providers.values():
        if provider.protocol not in _SUPPORTED_MUSIC_PROTOCOLS:
            config.load_error = (
                f"音乐 provider {provider.id} 使用了未知协议：{provider.protocol}"
            )
            return config
        if not provider.base_url:
            config.load_error = f"音乐 provider {provider.id} 缺少 base_url"
            return config
        if not provider.api_key_env:
            config.load_error = f"音乐 provider {provider.id} 缺少 api_key_env"
            return config
    if music.default_model and music.default_model not in music.models:
        config.load_error = f"音乐默认模型不存在：{music.default_model}"
        return config

    asr = config.asr
    for provider in asr.providers.values():
        if provider.protocol not in _SUPPORTED_ASR_PROTOCOLS:
            config.load_error = f"ASR provider {provider.id} 使用了未知协议：{provider.protocol}"
            return config
        if not provider.base_url:
            config.load_error = f"ASR provider {provider.id} 缺少 base_url"
            return config
        if not provider.api_key_env:
            config.load_error = f"ASR provider {provider.id} 缺少 api_key_env"
            return config
    if asr.default_model and asr.default_model not in asr.models:
        config.load_error = f"ASR 默认模型不存在：{asr.default_model}"
        return config

    return config


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        return tomllib.load(file)


def load_generation_config(
    path: str | Path = DEFAULT_GENERATION_CONFIG_PATH,
    *,
    legacy_llm_path: str | Path = DEFAULT_LEGACY_LLM_CONFIG_PATH,
) -> GenerationConfig:
    config_path = Path(path)
    if config_path.exists():
        data = _load_toml(config_path)
        config = GenerationConfig(
            image=_read_image_generation_section(data),
            audio=_read_audio_generation_section(data),
            music=_read_music_generation_section(data),
            asr=_read_asr_section(data),
            source_path=config_path,
            source_kind="generation",
        )
        return _validate_generation_config(config)

    legacy_path = Path(legacy_llm_path)
    if legacy_path.exists():
        data = _load_toml(legacy_path)
        config = GenerationConfig(
            image=_read_image_generation_section(data),
            audio=_read_audio_generation_section(data),
            music=_read_music_generation_section(data),
            asr=_read_asr_section(data),
            source_path=legacy_path,
            source_kind="llm_legacy",
        )
        return _validate_generation_config(config)

    return GenerationConfig(
        load_error=f"未找到配置文件：{config_path}",
        source_path=config_path,
        source_kind="generation",
    )
