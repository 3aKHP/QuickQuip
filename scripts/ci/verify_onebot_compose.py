"""Render the public Compose templates with an independently managed OneBot endpoint."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = {
    "docker-compose.example.yml": {"quickquip", "web-admin", "env-agent", "config-init", "searxng"},
    "prod.example/docker-compose.yml": {"quickquip", "web-admin", "env-agent"},
}
TOKEN = "synthetic-onebot"
ENVIRONMENT = {
    "ONEBOT_ACCESS_TOKEN": TOKEN,
    "QUICKQUIP_SEARXNG_BASE_URL": "http://search.example.test:8080",
    "SEARXNG_SECRET": "synthetic-search",
}


def main():
    env = {
        name: value for name, value in os.environ.items()
        if name not in ENVIRONMENT
        and not name.startswith(("ONEBOT_", "QUICKQUIP_", "COMPOSE_"))
        and name != "QQ_ACCOUNT"
    }
    with tempfile.TemporaryDirectory(prefix="quickquip-compose-") as directory:
        root = Path(directory)
        environment = root / ".env"
        for relative, expected_services in TEMPLATES.items():
            compose = root / relative
            compose.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, compose)
            command = [
                "docker", "compose", "--env-file", str(environment), "-f", str(compose),
                "config", "--format", "json",
            ]
            for urls in ([], ["ws://onebot.example.test:3001/"]):
                settings = ENVIRONMENT.copy()
                if urls:
                    settings["ONEBOT_WS_URLS"] = json.dumps(urls)
                environment.write_text(
                    "".join(f"{name}={value}\n" for name, value in settings.items()),
                    encoding="utf-8",
                )
                config = json.loads(subprocess.check_output(command, cwd=root, env=env))
                services = config["services"]
                assert set(services) == expected_services, relative
                bot = services["quickquip"]["environment"]
                assert json.loads(bot["ONEBOT_WS_URLS"]) == urls, relative
                assert bot["ONEBOT_ACCESS_TOKEN"] == TOKEN, relative
            print(f"{relative}: external forward endpoint and empty reverse endpoint accepted")


if __name__ == "__main__":
    main()
