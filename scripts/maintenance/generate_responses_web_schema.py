#!/usr/bin/env python3
"""Generate the pinned Codex web.run contract using Rust, outside the application runtime.

Usage: python scripts/maintenance/generate_responses_web_schema.py \
    --codex-repo /path/to/codex --output-dir /path/to/output
Requires cargo and a checkout containing the pinned commit. Cargo may download build dependencies.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import tempfile

COMMIT = "77873dd0d284aeba7ce849b995b28ee8f4498d73"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    def source(path: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(args.codex_repo), "show", f"{COMMIT}:{path}"],
            text=True,
            encoding="utf-8",
        )

    search = source("codex-rs/codex-api/src/search.rs")
    start = search.index(
        "#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq, JsonSchema)]"
    )
    end = search.index(
        "#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, JsonSchema)]\n"
        '#[serde(rename_all = "snake_case")]\npub enum ExternalWebAccessMode'
    )
    types = source("codex-rs/tools/src/json_schema/types.rs")
    types = (
        types[: types.index("impl JsonSchema {")]
        + types[types.index("/// Whether additional properties") : types.index("impl From<bool>")]
    )
    rust_main = r"""
fn main() {
    let schema = schemars::gen::SchemaSettings::draft2019_09().with(|s| {
        s.inline_subschemas = true;
        s.option_add_null_type = false;
    }).into_generator().into_root_schema_for::<SearchCommands>();
    let mut value = serde_json::to_value(schema).unwrap();
    value.as_object_mut().unwrap().retain(|k, _| ["properties", "required", "type",
        "additionalProperties", "$defs", "definitions"].contains(&k.as_str()));
    value["properties"].as_object_mut().unwrap().remove("literature_search_query");
    let value: wire::JsonSchema = serde_json::from_value(value).unwrap();
    println!("{}", serde_json::to_string_pretty(&value).unwrap());
}
"""
    with tempfile.TemporaryDirectory(prefix="quickquip-web-schema-") as directory:
        crate = Path(directory)
        (crate / "src").mkdir()
        (crate / "Cargo.toml").write_text(
            '[package]\nname="web-schema-generator"\nversion="0.1.0"\nedition="2021"\n'
            '[dependencies]\nschemars="=0.8.22"\n'
            'serde={version="1",features=["derive"]}\nserde_json="1"\n',
            encoding="utf-8",
            newline="\n",
        )
        (crate / "src/main.rs").write_text(
            "use serde::{Serialize, Deserialize};\nuse schemars::JsonSchema;\n"
            + search[start:end]
            + "\nmod wire {\n"
            + types.replace("//!", "//")
            + "\n}\n"
            + rust_main,
            encoding="utf-8",
            newline="\n",
        )
        output = subprocess.check_output(
            ["cargo", "run", "--quiet", "--manifest-path", str(crate / "Cargo.toml")],
            text=True,
            encoding="utf-8",
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "responses_web_schema.json").write_text(
        output, encoding="utf-8", newline="\n"
    )
    (args.output_dir / "responses_web_description.txt").write_text(
        source("codex-rs/ext/web-search/web_run_description.md"),
        encoding="utf-8",
        newline="\n",
    )
    for name in ("LICENSE", "NOTICE"):
        (args.output_dir / f"responses_web_{name}.txt").write_text(
            source(name),
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    main()
