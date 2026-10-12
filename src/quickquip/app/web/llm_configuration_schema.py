"""OpenAPI configuration schemas derived from the shared field constraint registry."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

from fastapi import FastAPI

from quickquip.llm.config import PricingRates
from quickquip.llm.config_fields import field_registry


def _field(spec):
    result = {
        key: deepcopy(value)
        for key, value in spec.items()
        if key in ("type", "enum", "minimum", "maximum") and value is not None
    }
    if spec.get("nullable"):
        result["type"] = [result["type"], "null"]
        if "enum" in result:
            result["enum"] = [*result["enum"], None]
    if result.get("type") == "array":
        result["items"] = {}
    return result


def document_schema():
    registry = field_registry()
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "properties": {name: _field(spec) for name, spec in registry["parameters"].items()},
    }
    model = {
        "type": "object",
        "additionalProperties": False,
        "required": ["model"],
        "properties": {
            "model": {"type": "string", "minLength": 1},
            "enabled": {"type": "boolean"},
            "vision": {"type": "boolean"},
            "context_window": {"type": ["integer", "null"], "minimum": 1024},
            "parameters": parameters,
        },
    }
    alias = {
        "type": "object",
        "required": ["alias", "model"],
        "additionalProperties": False,
        "properties": {"alias": {"type": "string"}, "model": {"type": "string"}},
    }
    provider = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "protocol", "base_url", "api_key_env", "default_model", "models"],
        "properties": {
            "id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]+$"},
            "protocol": {"type": "string", "enum": registry["protocols"]},
            "base_url": {"type": "string"},
            "api_key_env": {"type": "string"},
            "default_model": {"type": "string"},
            "enabled": {"type": "boolean"},
            "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            "client_fingerprint": {"type": "string", "default": "default"},
            "fallback_urls": {"type": "array", "items": {"type": "string"}},
            "proxy": {"type": "string"},
            "auth_method": {"enum": ["api_key", "bearer"]},
            "parameters": parameters,
            "models": {"type": "array", "items": model},
            "aliases": {"type": "array", "items": alias},
        },
    }
    reference = {
        "type": "object",
        "required": ["provider_id", "model"],
        "additionalProperties": False,
        "properties": {"provider_id": {"type": "string"}, "model": {"type": "string"}},
    }
    settings = {}
    for name, fields in registry["settings"].items():
        settings[name] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: _field(spec) for key, spec in fields.items()},
        }
    settings["mcp"]["properties"]["servers"] = {"type": "array", "items": {"type": "object"}}
    rates = {
        key: {"type": ["number", "null"] if key.startswith("cache_") else "number", "minimum": 0}
        if key.endswith("per_mtok")
        else {"type": "string"}
        for key in asdict(PricingRates())
    }
    return {
        "type": "object",
        "required": ["format_version"],
        "additionalProperties": False,
        "properties": {
            "format_version": {"const": 1},
            "providers": {"type": "array", "items": provider},
            "style_profiles": {"type": "object", "additionalProperties": {"type": "string"}},
            "pricing": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["model"],
                    "additionalProperties": False,
                    "properties": {
                        "provider_id": {"type": ["string", "null"]},
                        "model": {"type": "string"},
                        **rates,
                    },
                },
            },
            "routes": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    name: {"type": "array", "items": {"oneOf": [reference, {"const": "@default"}]}}
                    for name in registry["route_names"]
                },
            },
            "settings": {"type": "object", "additionalProperties": False, "properties": settings},
        },
    }


def enrich_openapi(schema):
    schema = deepcopy(schema)
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components["ConfigDocument"] = document_schema()
    components["ConfigEnvelope"] = {
        "type": "object",
        "required": ["revision", "document"],
        "properties": {
            "revision": {"type": "integer"},
            "document": {"$ref": "#/components/schemas/ConfigDocument"},
        },
    }
    components["ConfigError"] = {
        "type": "object",
        "required": ["code", "message", "field_path", "details"],
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "field_path": {"type": "string"},
            "details": {},
        },
    }
    components["ConfigOperation"] = {
        "type": "object",
        "required": ["id", "kind", "target_revision", "status", "stage"],
        "properties": {
            "id": {"type": "string"},
            "kind": {"enum": ["apply", "probe"]},
            "target_revision": {"type": "integer"},
            "status": {"enum": ["queued", "running", "succeeded", "failed", "cancelled"]},
            "stage": {"type": "string"},
            "payload": {"type": "object"},
            "result": {},
            "error": {},
            "created_at": {"type": "number"},
            "updated_at": {"type": "number"},
            "may_charge": {"type": "boolean"},
            "automatic_retry": {"type": "boolean"},
        },
    }

    def object_schema(properties, required=()):
        return {"type": "object", "properties": properties, "required": list(required)}

    def reference(name):
        return {"$ref": f"#/components/schemas/{name}"}

    def array(items):
        return {"type": "array", "items": items}

    integer, string = {"type": "integer"}, {"type": "string"}
    components["ConfigValidation"] = object_schema(
        {
            "valid": {"type": "boolean"},
            "warnings": array({"type": "object"}),
            "dependencies": array({"type": "object"}),
        },
        ("valid", "warnings", "dependencies"),
    )
    components["ConfigDiff"] = object_schema(
        {
            "changes": array(object_schema({"field_path": string, "before": {}, "after": {}})),
            "components": object_schema(
                {"mcp_reconnect": {"type": "boolean"}, "reschedule": array(string)}
            ),
        }
    )
    components["ConfigImportPreview"] = {
        "allOf": [
            reference("ConfigValidation"),
            object_schema(
                {
                    "document": reference("ConfigDocument"),
                    "expected_draft_revision": integer,
                    "changes": array({"type": "object"}),
                }
            ),
        ]
    }
    components["ConfigEnvironment"] = object_schema(
        {
            "available": {"type": "boolean"},
            "stale": {"type": "boolean"},
            "variables": array(
                object_schema({"name": string, "configured": {"type": ["boolean", "null"]}})
            ),
        }
    )
    components["ConfigStatus"] = object_schema(
        {
            "schema_version": integer,
            "draft_revision": integer,
            "published_revision": integer,
            "bot": {
                "anyOf": [
                    object_schema(
                        {
                            "boot_id": string,
                            "loaded_revision": integer,
                            "application_version": string,
                            "heartbeat_at": {"type": "number"},
                            "observed_at": {"type": "number"},
                            "stale": {"type": "boolean"},
                            "components": {"type": "object"},
                        }
                    ),
                    {"type": "null"},
                ]
            },
        }
    )
    components["ConfigHistory"] = object_schema(
        {"snapshots": array(object_schema({"revision": integer, "created_at": {"type": "number"}}))}
    )
    components["ConfigOperationList"] = object_schema(
        {"operations": array(reference("ConfigOperation"))}
    )
    components["ConfigDependencies"] = object_schema({"dependencies": array({"type": "object"})})
    components["ConfigMetadata"] = object_schema(
        {
            "format_version": integer,
            "protocols": array(string),
            "route_names": array(string),
            "parameters": {"type": "object"},
            "settings": {"type": "object"},
            "client_fingerprints": array(object_schema({
                "id": string, "label": string, "protocols": array(string),
            })),
        }
    )
    components["ConfigProviders"] = object_schema(
        {"revision": integer, "providers": components["ConfigDocument"]["properties"]["providers"]}
    )
    components["ConfigProviderDetail"] = object_schema(
        {
            "revision": integer,
            "provider": components["ConfigDocument"]["properties"]["providers"]["items"],
            "pricing": components["ConfigDocument"]["properties"]["pricing"],
        }
    )
    components["ConfigEffectiveParameters"] = object_schema(
        {
            "revision": integer,
            "parameters": {
                "type": "object",
                "additionalProperties": object_schema(
                    {"configured": {}, "value": {}, "source": string}
                ),
            },
        }
    )
    components["ConfigSection"] = object_schema({"revision": integer, "value": {}})
    if "DocumentBody" in components:
        components["DocumentBody"]["properties"]["document"] = {
            "$ref": "#/components/schemas/ConfigDocument"
        }
    if "ValidateBody" in components:
        components["ValidateBody"]["properties"]["document"] = {
            "anyOf": [{"$ref": "#/components/schemas/ConfigDocument"}, {"type": "null"}]
        }
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["AdminSession"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": "quickquip_admin_session",
    }
    for path, operations in schema["paths"].items():
        if "/llm-configuration" not in path:
            continue
        suffix = path.split("/llm-configuration", 1)[1]
        for method, spec in operations.items():
            if method not in ("get", "put", "post", "patch", "delete"):
                continue
            spec["security"] = [{"AdminSession": []}]
            for code in ("401", "403", "409", "413", "422"):
                spec["responses"][code] = {
                    "description": "Configuration request rejected",
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/ConfigError"}}
                    },
                }
            response = (
                "ConfigOperation"
                if suffix in ("/apply", "/probe") or suffix.startswith("/operations/")
                else "ConfigDocument"
                if suffix == "/export"
                else "ConfigEnvelope"
                if (
                    suffix == ""
                    or (
                        method != "get"
                        and suffix not in ("/validate", "/import/preview")
                        and not suffix.startswith("/operations/")
                    )
                )
                else None
            )
            if response is None:
                response = {
                    "/metadata": "ConfigMetadata",
                    "/status": "ConfigStatus",
                    "/environment": "ConfigEnvironment",
                    "/validate": "ConfigValidation",
                    "/dependencies": "ConfigDependencies",
                    "/diff": "ConfigDiff",
                    "/import/preview": "ConfigImportPreview",
                    "/operations": "ConfigOperationList",
                    "/history": "ConfigHistory",
                    "/providers": "ConfigProviders",
                }.get(suffix)
                if response is None:
                    response = (
                        "ConfigEffectiveParameters"
                        if suffix.endswith("/effective")
                        else "ConfigProviderDetail"
                        if suffix.startswith("/providers/")
                        else "ConfigSection"
                    )
            if response:
                status = "202" if suffix in ("/apply", "/probe") else "200"
                spec["responses"][status]["content"]["application/json"]["schema"] = {
                    "$ref": f"#/components/schemas/{response}"
                }
    return schema


def configuration_openapi():
    """Export the frozen API without initializing a configured bot or database."""
    from quickquip.app.web.routes.llm_configuration import router

    app = FastAPI(title="QuickQuip LLM Configuration API", version="1.16.2")
    app.include_router(router, prefix="/ops/api")
    return enrich_openapi(app.openapi())
