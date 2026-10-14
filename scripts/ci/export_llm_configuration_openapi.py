"""Export the public LLM configuration OpenAPI contract from its shared registry."""

from pathlib import Path
import json

from quickquip.app.web.llm_configuration_schema import configuration_openapi


def main():
    destination = Path(__file__).resolve().parents[2] / "docs/dev/llm-configuration.openapi.json"
    destination.write_text(
        json.dumps(configuration_openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
