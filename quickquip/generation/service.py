from __future__ import annotations

from pathlib import Path

from quickquip.generation.config import (
    DEFAULT_GENERATION_CONFIG_PATH,
    DEFAULT_LEGACY_LLM_CONFIG_PATH,
    GenerationConfig,
    ResolvedAudioModel,
    ResolvedImageModel,
    ResolvedMusicModel,
    load_generation_config,
)


class GenerationService:
    def __init__(
        self,
        config_path: str | Path = DEFAULT_GENERATION_CONFIG_PATH,
        *,
        legacy_llm_path: str | Path = DEFAULT_LEGACY_LLM_CONFIG_PATH,
    ) -> None:
        self.config_path = Path(config_path)
        self.legacy_llm_path = Path(legacy_llm_path)
        self._config: GenerationConfig | None = None
        self._active_mtime: float | None = None
        self._legacy_mtime: float | None = None

    def _stat_mtime(self, path: Path) -> float | None:
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def _needs_reload(self) -> bool:
        if self._config is None:
            return True
        active_mtime = self._stat_mtime(self.config_path)
        legacy_mtime = self._stat_mtime(self.legacy_llm_path)
        return active_mtime != self._active_mtime or legacy_mtime != self._legacy_mtime

    def reload(self) -> GenerationConfig:
        self._config = load_generation_config(
            self.config_path,
            legacy_llm_path=self.legacy_llm_path,
        )
        self._active_mtime = self._stat_mtime(self.config_path)
        self._legacy_mtime = self._stat_mtime(self.legacy_llm_path)
        return self._config

    def get_config(self, *, force_reload: bool = False) -> GenerationConfig:
        if force_reload or self._needs_reload():
            return self.reload()
        return self._config

    def resolve_image_model(self, model_id: str | None = None) -> ResolvedImageModel | None:
        return self.get_config().image.resolve_model(model_id)

    def resolve_audio_model(self, model_id: str | None = None) -> ResolvedAudioModel | None:
        return self.get_config().audio.resolve_model(model_id)

    def resolve_music_model(self, model_id: str | None = None) -> ResolvedMusicModel | None:
        return self.get_config().music.resolve_model(model_id)


generation_service = GenerationService()
