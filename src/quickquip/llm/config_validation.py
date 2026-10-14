"""Shared validation, warnings and change impacts for configuration adapters."""

from __future__ import annotations

from quickquip.llm.config_document import dependencies, validate_document


def document_diff(before, after, path=""):
    changes = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            changes.extend(
                document_diff(before.get(key), after.get(key), f"{path}.{key}" if path else key)
            )
    elif before != after:
        changes.append({"field_path": path, "before": before, "after": after})
    return changes


def validation_report(document, before=None, *, config_dir=None):
    normalized = validate_document(document, config_dir=config_dir)
    prices = {(p["provider_id"], p["model"]) for p in normalized["pricing"]}
    warnings = [
        {
            "code": "price_missing",
            "field_path": f"providers.{p['id']}.models",
            "message": "Model has no configured price",
            "details": {"model": m["model"]},
        }
        for p in normalized["providers"]
        for m in p["models"]
        if (p["id"], m["model"]) not in prices
    ]
    configured = {(p["id"], m["model"]) for p in normalized["providers"] for m in p["models"]}
    warnings.extend(
        {
            "code": "price_orphan",
            "field_path": f"pricing[{index}]",
            "message": "Price references a model the provider does not configure",
            "details": {"provider_id": price["provider_id"], "model": price["model"]},
        }
        for index, price in enumerate(normalized["pricing"])
        if (price["provider_id"], price["model"]) not in configured
    )
    report = {"valid": True, "warnings": warnings, "dependencies": dependencies(normalized)}
    if before is not None:
        changes = document_diff(before, normalized)
        paths = [change["field_path"] for change in changes]
        report.update(
            changes=changes,
            components={
                "mcp_reconnect": any(p.startswith("settings.mcp") for p in paths),
                "reschedule": [
                    name
                    for name in (
                        "daily_summary",
                        "daily_briefing",
                        "weekly_report",
                        "monthly_report",
                    )
                    if any(p.startswith(f"settings.{name}") for p in paths)
                ],
            },
        )
    return report
