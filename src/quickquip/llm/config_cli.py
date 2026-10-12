"""Configuration administration: python -m quickquip.llm.config_cli --help."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

from quickquip.common.env import load_root_env_file
from quickquip.common.paths import CONFIG_LLM_TOML
from quickquip.llm.config_document import ConfigError, validate_document
from quickquip.llm.config_service import ConfigService, DEFAULT_CONFIG_DB
from quickquip.llm.config_validation import validation_report

MAX_IMPORT_BYTES = 1024 * 1024


def read_document(path: Path, *, config_dir: Path | None = None) -> dict:
    with path.open("rb") as stream:
        body = stream.read(MAX_IMPORT_BYTES + 1)
    if len(body) > MAX_IMPORT_BYTES:
        raise ConfigError("body_too_large", "JSON 配置不得超过 1 MiB")
    try:
        document = json.loads(body)
    except (UnicodeError, ValueError):
        raise ConfigError("invalid_json", "配置文件须为 UTF-8 JSON") from None
    return validate_document(document, config_dir=config_dir)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="QuickQuip LLM 配置数据库管理")
    p.add_argument("--db", type=Path, default=DEFAULT_CONFIG_DB, help="配置库路径")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("init", "migrate-legacy"):
        q = commands.add_parser(name)
        q.add_argument("--legacy", type=Path, default=CONFIG_LLM_TOML)
        if name == "migrate-legacy":
            q.add_argument("--expected-revision", type=int)
        else:
            q.add_argument(
                "--services-stopped", action="store_true",
                help="确认旧 bot 和 Web 已停止，用于 schema 1 配置库升级",
            )
    q = commands.add_parser("validate")
    q.add_argument("file", nargs="?", type=Path)
    q = commands.add_parser("export")
    q.add_argument("--source", default="draft", help="draft / published / 快照修订号")
    q.add_argument("--output", type=Path)
    q = commands.add_parser("import")
    q.add_argument("file", type=Path)
    q.add_argument("--expected-revision", type=int, required=True)
    q.add_argument("--preview", action="store_true")
    q = commands.add_parser("diff")
    q.add_argument("--source", default="draft")
    q.add_argument("--target", default="published")
    q = commands.add_parser("apply")
    q.add_argument("--expected-revision", type=int, required=True)
    q.add_argument("--request-id", default=None)
    q = commands.add_parser("status")
    q.add_argument("--operation", help="查询异步任务 ID")
    q.add_argument("--require-loaded", action="store_true", help="检查 bot 心跳及发布版本已加载")
    q = commands.add_parser("backup")
    q.add_argument("file", type=Path)
    q = commands.add_parser("restore")
    source = q.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--snapshot", type=int)
    q.add_argument(
        "--services-stopped", action="store_true", help="确认 bot 和 Web 已停止，数据库恢复必须提供"
    )
    q.add_argument("--expected-revision", type=int)
    return p


def _source(value: str):
    if value in ("draft", "published"):
        return value
    try:
        return int(value)
    except ValueError:
        raise ConfigError("invalid_field", "配置来源须为 draft、published 或快照修订号") from None


def execute(args) -> dict:
    service = ConfigService(args.db)
    if args.command == "init":
        return service.initialize(args.legacy, services_stopped=args.services_stopped)
    if args.command == "validate" and args.file:
        doc = read_document(args.file, config_dir=service.config_dir)
        return validation_report(doc, config_dir=service.config_dir)
    if args.command == "migrate-legacy":
        if not service.path.exists():
            return service.initialize(args.legacy)
        if args.expected_revision is None:
            raise ConfigError("missing_revision", "导入旧配置到草稿须指定 --expected-revision")
        return service.migrate_legacy(args.legacy, args.expected_revision)
    # Existing database failures never fall back to the legacy file.
    if not service.path.exists():
        raise ConfigError("not_initialized", "请先执行 init 初始化或迁移配置")
    if args.command == "validate":
        state = service.read()
        return {**service.validate(state["document"]), "revision": state["revision"]}
    if args.command == "export":
        doc = service.read(_source(args.source))["document"]
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
            return {"output": str(args.output)}
        return doc
    if args.command == "import":
        doc = read_document(args.file, config_dir=service.config_dir)
        if args.preview:
            return service.preview_import(doc, args.expected_revision)
        return service.replace(doc, args.expected_revision)
    if args.command == "diff":
        return service.diff(_source(args.source), _source(args.target))
    if args.command == "apply":
        return service.apply(args.expected_revision, args.request_id or uuid.uuid4().hex)
    if args.command == "status":
        status = service.tasks.get(args.operation) if args.operation else service.status()
        if args.require_loaded:
            bot = status.get("bot")
            if not bot or bot["stale"] or bot["loaded_revision"] != status["published_revision"]:
                raise ConfigError("bot_not_loaded", "bot 心跳过期或尚未加载发布版本")
        return status
    if args.command == "backup":
        return {"backup": str(service.backup(args.file))}
    if args.command == "restore":
        if args.file:
            return service.restore_database(args.file, stopped=args.services_stopped)
        if args.expected_revision is None:
            raise ConfigError("missing_revision", "恢复快照须指定 --expected-revision")
        return service.restore_snapshot(args.snapshot, args.expected_revision)
    raise ConfigError("invalid_command", "不支持的配置操作")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    load_root_env_file()
    try:
        result = execute(args)
    except ConfigError as error:
        print(json.dumps({"error": error.as_dict()}, ensure_ascii=False), file=sys.stderr)
        return 1
    except OSError:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "file_error",
                        "message": "配置文件操作失败",
                        "field_path": "",
                        "details": None,
                    }
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
