from __future__ import annotations

from quickquip.common import env


def test_project_env_loader_only_reads_root_env(monkeypatch):
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(env, "_ROOT_ENV_LOADED", False)

    def fake_load_dotenv(path, *, override=False):
        calls.append((path.as_posix(), override))

    monkeypatch.setattr(env, "load_dotenv", fake_load_dotenv)

    env.load_project_env_files()

    assert calls == [((env.PROJECT_ROOT / ".env").as_posix(), False)]
