from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Any
import tomllib


DEFAULT_GENERATION_CONFIG_PATH = Path("config/generation.toml")
DEFAULT_LEGACY_LLM_CONFIG_PATH = Path("config/llm.toml")
_SUPPORTED_IMAGE_PROTOCOLS = {"openai_images", "gemini_imagen", "minimax_images"}
_SUPPORTED_AUDIO_PROTOCOLS = {"minimax_t2a_http", "minimax_t2a_async"}
_SUPPORTED_MUSIC_PROTOCOLS = {"minimax_music"}
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


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
class ImageGenerationConfig:
    enabled: bool = False
    default_model: str = ""
    prompt_blocklist: list[str] = field(default_factory=list)
    providers: dict[str, ImageProviderConfig] = field(default_factory=dict)
    models: dict[str, ResolvedImageModel] = field(default_factory=dict)

    def resolve_model(self, model_id: str | None = None) -> ResolvedImageModel | None:
        candidate = (model_id or self.default_model).strip()
        if not candidate:
            return None
        return self.models.get(candidate)


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
class AudioGenerationConfig:
    enabled: bool = False
    default_model: str = ""
    prompt_blocklist: list[str] = field(default_factory=list)
    providers: dict[str, AudioProviderConfig] = field(default_factory=dict)
    models: dict[str, ResolvedAudioModel] = field(default_factory=dict)

    def resolve_model(self, model_id: str | None = None) -> ResolvedAudioModel | None:
        candidate = (model_id or self.default_model).strip()
        if not candidate:
            return None
        return self.models.get(candidate)


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
class MusicGenerationConfig:
    enabled: bool = False
    default_model: str = ""
    prompt_blocklist: list[str] = field(default_factory=list)
    providers: dict[str, MusicProviderConfig] = field(default_factory=dict)
    models: dict[str, ResolvedMusicModel] = field(default_factory=dict)

    def resolve_model(self, model_id: str | None = None) -> ResolvedMusicModel | None:
        candidate = (model_id or self.default_model).strip()
        if not candidate:
            return None
        return self.models.get(candidate)


@dataclass(slots=True)
class GenerationConfig:
    image: ImageGenerationConfig = field(default_factory=ImageGenerationConfig)
    audio: AudioGenerationConfig = field(default_factory=AudioGenerationConfig)
    music: MusicGenerationConfig = field(default_factory=MusicGenerationConfig)
    load_error: str | None = None
    source_path: Path | None = None
    source_kind: str = "generation"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _expand_env_string(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        resolved = os.getenv(key)
        if resolved is None:
            return default or ""
        return resolved

    return _ENV_PATTERN.sub(_replace, value)


def _expand_env_value(value: Any) -> Any:
    if isinstance(value, str):
        return _expand_env_string(value)
    if isinstance(value, list):
        return [_expand_env_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _expand_env_value(item) for key, item in value.items()}
    return value


def _read_image_generation(raw: dict[str, Any]) -> ImageGenerationConfig:
    providers: dict[str, ImageProviderConfig] = {}
    models: dict[str, ResolvedImageModel] = {}
    raw_providers = raw.get("providers", [])
    for provider_entry in raw_providers if isinstance(raw_providers, list) else []:
        provider_entry = _expand_env_value(provider_entry)
        provider_id = str(provider_entry.get("id", "")).strip()
        if not provider_id:
            continue

        raw_headers = _as_dict(provider_entry.get("headers"))
        model_list: list[ImageModelConfig] = []
        for model_entry in provider_entry.get("models", []) or []:
            model_entry = _expand_env_value(model_entry)
            model_id = str(model_entry.get("id", "")).strip()
            model_name = str(model_entry.get("model", "")).strip()
            if not model_id or not model_name:
                continue

            model = ImageModelConfig(
                id=model_id,
                model=model_name,
                label=str(model_entry.get("label", "")).strip(),
                size=str(model_entry.get("size", "1024x1024")).strip() or "1024x1024",
                quality=str(model_entry.get("quality", "standard")).strip() or "standard",
                response_format=str(model_entry.get("response_format", "b64_json")).strip(),
            )
            model_list.append(model)

        provider = ImageProviderConfig(
            id=provider_id,
            protocol=str(provider_entry.get("protocol", "openai_images")).strip() or "openai_images",
            base_url=str(provider_entry.get("base_url", "")).strip(),
            api_key_env=str(provider_entry.get("api_key_env", "")).strip(),
            timeout_seconds=float(provider_entry.get("timeout_seconds", 120)),
            default_model=str(provider_entry.get("default_model", "")).strip(),
            models=model_list,
            headers={str(k): str(v) for k, v in raw_headers.items()},
            user_agent=str(provider_entry.get("user_agent", "")).strip(),
            extra_body=_expand_env_value(_as_dict(provider_entry.get("extra_body"))),
        )
        providers[provider_id] = provider

        for model in model_list:
            models[model.id] = ResolvedImageModel(
                id=model.id,
                model_config=model,
                provider=provider,
            )

    default_model = str(raw.get("default_model", "")).strip()
    if not default_model and models:
        default_model = next(iter(models))

    return ImageGenerationConfig(
        enabled=_as_bool(raw.get("enabled", False), default=False),
        default_model=default_model,
        prompt_blocklist=[
            str(word).strip().lower()
            for word in raw.get("prompt_blocklist", [])
            if str(word).strip()
        ],
        providers=providers,
        models=models,
    )


def _read_audio_generation(raw: dict[str, Any]) -> AudioGenerationConfig:
    providers: dict[str, AudioProviderConfig] = {}
    models: dict[str, ResolvedAudioModel] = {}
    raw_providers = raw.get("providers", [])
    for provider_entry in raw_providers if isinstance(raw_providers, list) else []:
        provider_entry = _expand_env_value(provider_entry)
        provider_id = str(provider_entry.get("id", "")).strip()
        if not provider_id:
            continue

        raw_headers = _as_dict(provider_entry.get("headers"))
        model_list: list[AudioModelConfig] = []
        for model_entry in provider_entry.get("models", []) or []:
            model_entry = _expand_env_value(model_entry)
            model_id = str(model_entry.get("id", "")).strip()
            model_name = str(model_entry.get("model", "")).strip()
            if not model_id or not model_name:
                continue

            model = AudioModelConfig(
                id=model_id,
                model=model_name,
                label=str(model_entry.get("label", "")).strip(),
                voice_id=str(model_entry.get("voice_id", "")).strip(),
                speed=float(model_entry.get("speed", 1.0)),
                vol=float(model_entry.get("vol", 1.0)),
                pitch=int(float(model_entry.get("pitch", 0))),
                emotion=str(model_entry.get("emotion", "")).strip(),
                sample_rate=int(model_entry.get("sample_rate", 32000)),
                bitrate=int(model_entry.get("bitrate", 128000)),
                format=str(model_entry.get("format", "mp3")).strip() or "mp3",
                channel=int(model_entry.get("channel", 1)),
                language_boost=str(model_entry.get("language_boost", "")).strip(),
                subtitle_enable=_as_bool(model_entry.get("subtitle_enable", False), default=False),
                output_format=str(model_entry.get("output_format", "hex")).strip() or "hex",
                pronunciation_dict=_expand_env_value(_as_dict(model_entry.get("pronunciation_dict"))),
                voice_modify=_expand_env_value(_as_dict(model_entry.get("voice_modify"))),
                extra_body=_expand_env_value(_as_dict(model_entry.get("extra_body"))),
            )
            model_list.append(model)

        provider = AudioProviderConfig(
            id=provider_id,
            protocol=str(provider_entry.get("protocol", "minimax_t2a_http")).strip()
            or "minimax_t2a_http",
            base_url=str(provider_entry.get("base_url", "")).strip(),
            api_key_env=str(provider_entry.get("api_key_env", "")).strip(),
            timeout_seconds=float(provider_entry.get("timeout_seconds", 120)),
            default_model=str(provider_entry.get("default_model", "")).strip(),
            models=model_list,
            headers={str(k): str(v) for k, v in raw_headers.items()},
            user_agent=str(provider_entry.get("user_agent", "")).strip(),
            extra_body=_expand_env_value(_as_dict(provider_entry.get("extra_body"))),
        )
        providers[provider_id] = provider

        for model in model_list:
            models[model.id] = ResolvedAudioModel(
                id=model.id,
                model_config=model,
                provider=provider,
            )

    default_model = str(raw.get("default_model", "")).strip()
    if not default_model and models:
        default_model = next(iter(models))

    return AudioGenerationConfig(
        enabled=_as_bool(raw.get("enabled", False), default=False),
        default_model=default_model,
        prompt_blocklist=[
            str(word).strip().lower()
            for word in raw.get("prompt_blocklist", [])
            if str(word).strip()
        ],
        providers=providers,
        models=models,
    )


def _read_music_generation(raw: dict[str, Any]) -> MusicGenerationConfig:
    providers: dict[str, MusicProviderConfig] = {}
    models: dict[str, ResolvedMusicModel] = {}
    raw_providers = raw.get("providers", [])
    for provider_entry in raw_providers if isinstance(raw_providers, list) else []:
        provider_entry = _expand_env_value(provider_entry)
        provider_id = str(provider_entry.get("id", "")).strip()
        if not provider_id:
            continue

        raw_headers = _as_dict(provider_entry.get("headers"))
        model_list: list[MusicModelConfig] = []
        for model_entry in provider_entry.get("models", []) or []:
            model_entry = _expand_env_value(model_entry)
            model_id = str(model_entry.get("id", "")).strip()
            model_name = str(model_entry.get("model", "")).strip()
            if not model_id or not model_name:
                continue

            model = MusicModelConfig(
                id=model_id,
                model=model_name,
                label=str(model_entry.get("label", "")).strip(),
                sample_rate=int(model_entry.get("sample_rate", 44100)),
                bitrate=int(model_entry.get("bitrate", 256000)),
                format=str(model_entry.get("format", "mp3")).strip() or "mp3",
                output_format=str(model_entry.get("output_format", "hex")).strip() or "hex",
                add_watermark=_as_bool(model_entry.get("add_watermark", False), default=False),
                lyrics_optimizer=_as_bool(model_entry.get("lyrics_optimizer", False), default=False),
                extra_body=_expand_env_value(_as_dict(model_entry.get("extra_body"))),
            )
            model_list.append(model)

        provider = MusicProviderConfig(
            id=provider_id,
            protocol=str(provider_entry.get("protocol", "minimax_music")).strip()
            or "minimax_music",
            base_url=str(provider_entry.get("base_url", "")).strip(),
            api_key_env=str(provider_entry.get("api_key_env", "")).strip(),
            timeout_seconds=float(provider_entry.get("timeout_seconds", 180)),
            default_model=str(provider_entry.get("default_model", "")).strip(),
            models=model_list,
            headers={str(k): str(v) for k, v in raw_headers.items()},
            user_agent=str(provider_entry.get("user_agent", "")).strip(),
            extra_body=_expand_env_value(_as_dict(provider_entry.get("extra_body"))),
        )
        providers[provider_id] = provider

        for model in model_list:
            models[model.id] = ResolvedMusicModel(
                id=model.id,
                model_config=model,
                provider=provider,
            )

    default_model = str(raw.get("default_model", "")).strip()
    if not default_model and models:
        default_model = next(iter(models))

    return MusicGenerationConfig(
        enabled=_as_bool(raw.get("enabled", False), default=False),
        default_model=default_model,
        prompt_blocklist=[
            str(word).strip().lower()
            for word in raw.get("prompt_blocklist", [])
            if str(word).strip()
        ],
        providers=providers,
        models=models,
    )


def _read_generation_section(
    data: dict[str, Any],
    section_name: str,
    legacy_section_name: str,
    reader,
):
    generation = _expand_env_value(_as_dict(data.get("generation")))
    if generation:
        section = _expand_env_value(_as_dict(generation.get(section_name)))
        if section:
            return reader(section)

    section = _expand_env_value(_as_dict(data.get(section_name)))
    if section:
        return reader(section)

    legacy_section = _expand_env_value(_as_dict(data.get(legacy_section_name)))
    if legacy_section:
        return reader(legacy_section)

    return reader({})


def _read_image_generation_section(data: dict[str, Any]) -> ImageGenerationConfig:
    return _read_generation_section(data, "image", "image_generation", _read_image_generation)


def _read_audio_generation_section(data: dict[str, Any]) -> AudioGenerationConfig:
    return _read_generation_section(data, "audio", "audio_generation", _read_audio_generation)


def _read_music_generation_section(data: dict[str, Any]) -> MusicGenerationConfig:
    return _read_generation_section(data, "music", "music_generation", _read_music_generation)


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
            source_path=legacy_path,
            source_kind="llm_legacy",
        )
        return _validate_generation_config(config)

    return GenerationConfig(
        load_error=f"未找到配置文件：{config_path}",
        source_path=config_path,
        source_kind="generation",
    )
