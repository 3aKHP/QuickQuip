"""Structured, revision-aware LLM configuration administration API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from quickquip.app.web.audit import audit_logger
from quickquip.llm.config_document import (
    ConfigError,
    dependencies,
    effective_parameters,
    environment_references,
    metadata,
)
from quickquip.llm.config_service import get_config_service

MAX_BODY_BYTES = 1024 * 1024
CONFLICT_CODES = {
    "revision_conflict",
    "operation_conflict",
    "dependency_conflict",
    "stale_claim",
    "database_busy",
    "services_running",
}


def error_response(error: ConfigError):
    code = error.code
    status = 409 if code in CONFLICT_CODES else 404 if code == "not_found" else 422
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": error.message,
            "field_path": getattr(error, "field_path", "") or "",
            "details": getattr(error, "details", None),
        },
    )


class ConfigurationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            # Read incrementally so a missing/false Content-Length cannot bypass the limit.
            content = bytearray()
            async for chunk in request.stream():
                content.extend(chunk)
                if len(content) > MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "code": "body_too_large",
                            "message": "Configuration request exceeds 1 MiB",
                            "field_path": "",
                            "details": {"limit_bytes": MAX_BODY_BYTES},
                        },
                    )
            request._body = bytes(content)
            try:
                return await original(request)
            except ConfigError as exc:
                return error_response(exc)
            except RequestValidationError as exc:
                errors = [
                    {"field_path": ".".join(map(str, e["loc"])), "type": e["type"]}
                    for e in exc.errors()
                ]
                return JSONResponse(
                    status_code=422,
                    content={
                        "code": "invalid_field",
                        "message": "Request fields are invalid",
                        "field_path": errors[0]["field_path"],
                        "details": errors,
                    },
                )
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "code": "unauthorized" if exc.status_code == 401 else "request_rejected",
                        "message": str(exc.detail),
                        "field_path": "",
                        "details": None,
                    },
                )

        return handle


router = APIRouter(
    prefix="/llm-configuration", tags=["LLM configuration"], route_class=ConfigurationRoute
)


class RevisionBody(BaseModel):
    expected_draft_revision: int = Field(ge=1)


class DocumentBody(RevisionBody):
    document: dict[str, Any]
    note: str | None = Field(default=None, max_length=120)


class ValidateBody(BaseModel):
    document: dict[str, Any] | None = None


class ApplyBody(RevisionBody):
    request_id: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=120)


class NoteBody(BaseModel):
    source: str = "draft"
    note: str = Field(max_length=120)


class ValueBody(RevisionBody):
    value: Any


class PatchBody(RevisionBody):
    fields: dict[str, Any]


class ProbeBody(BaseModel):
    source: str | int = "published"
    provider_id: str
    model: str
    request_id: str = Field(min_length=1, max_length=128)


class BatchBody(RevisionBody):
    changes: list[dict[str, Any]] = Field(min_length=1, max_length=100)


def _source(source):
    if source in ("draft", "published") or isinstance(source, int):
        return source
    try:
        return int(source)
    except (TypeError, ValueError):
        raise ConfigError(
            "invalid_field",
            "source must be draft, published or a snapshot revision",
            field_path="source",
        ) from None


def _audit(request, action, target="draft"):
    audit_logger.log(request, action=action, target_type="llm_configuration", target_id=target)


@router.get("/metadata")
def get_metadata():
    return metadata(config_dir=get_config_service().config_dir)


@router.get("")
def get_document(source: str = "draft"):
    return get_config_service().read(_source(source))


@router.put("")
def put_document(body: DocumentBody, request: Request):
    result = get_config_service().replace(
        body.document, body.expected_draft_revision, note=body.note
    )
    _audit(request, "update")
    return result


@router.get("/status")
def get_status():
    return get_config_service().status()


@router.put("/note")
def put_note(body: NoteBody, request: Request):
    result = get_config_service().set_note(_source(body.source), body.note)
    _audit(request, "note", body.source)
    return result


@router.get("/environment")
def get_environment(source: str = "draft"):
    document = get_config_service().read(_source(source))["document"]
    # Values are never returned; enumerate only explicitly referenced environment names.
    names = environment_references(document)
    bot = get_config_service().status()["bot"]
    observed = {
        entry["name"]: entry["configured"]
        for entry in (bot or {}).get("components", {}).get("environment", [])
    }
    return {
        "variables": [{"name": name, "configured": observed.get(name)} for name in sorted(names)],
        "available": bot is not None,
        "stale": bot is None or bot["stale"],
    }


@router.post("/validate")
def validate_config(body: ValidateBody):
    return get_config_service().validate(body.document)


@router.get("/dependencies")
def get_dependencies(source: str = "draft"):
    return {"dependencies": dependencies(get_config_service().read(_source(source))["document"])}


@router.get("/diff")
def get_diff(source: str = "draft", target: str = "published"):
    return get_config_service().diff(_source(source), _source(target))


@router.post("/import/preview")
def preview_import(body: DocumentBody):
    return get_config_service().preview_import(body.document, body.expected_draft_revision)


@router.post("/import")
def import_config(body: DocumentBody, request: Request):
    result = get_config_service().replace(body.document, body.expected_draft_revision)
    _audit(request, "import")
    return result


@router.get("/export")
def export_config(source: str = "draft"):
    return get_config_service().read(_source(source))["document"]


@router.post("/apply", status_code=202)
def apply_config(body: ApplyBody, request: Request):
    result = get_config_service().apply(
        body.expected_draft_revision, body.request_id, note=body.note
    )
    _audit(request, "apply", result["id"])
    return result


@router.post("/probe", status_code=202)
def probe_config(body: ProbeBody, request: Request):
    result = get_config_service().probe(
        _source(body.source), body.provider_id, body.model, body.request_id
    )
    _audit(request, "probe", result["id"])
    return {**result, "may_charge": True, "automatic_retry": False}


@router.get("/operations")
def list_operations(limit: int = 20):
    if not 1 <= limit <= 100:
        raise ConfigError("invalid_field", "limit must be between 1 and 100", field_path="limit")
    return {"operations": get_config_service().tasks.list(limit)}


@router.get("/operations/{operation_id}")
def get_operation(operation_id: str):
    return get_config_service().tasks.get(operation_id)


@router.post("/operations/{operation_id}/cancel")
def cancel_operation(operation_id: str, request: Request):
    result = get_config_service().tasks.cancel(operation_id)
    _audit(request, "cancel", operation_id)
    return result


@router.get("/history")
def get_history():
    return get_config_service().history()


@router.post("/history/{revision}/restore")
def restore_snapshot(revision: int, body: RevisionBody, request: Request):
    result = get_config_service().restore_snapshot(revision, body.expected_draft_revision)
    _audit(request, "restore", str(revision))
    return result


def _provider(document, provider_id):
    provider = next((p for p in document["providers"] if p["id"] == provider_id), None)
    if provider is None:
        raise ConfigError("not_found", "Provider not found")
    return provider


@router.get("/providers")
def get_providers(source: str = "draft"):
    service = get_config_service()
    result = service.read(_source(source))
    return {
        "revision": result["revision"],
        "version": service.version(result["revision"] if source != "draft" else "draft"),
        "providers": result["document"]["providers"],
    }


@router.get("/providers/{provider_id}/effective")
def get_effective(provider_id: str, model: str, source: str = "draft"):
    result = get_config_service().read(_source(source))
    return {
        "revision": result["revision"],
        "parameters": effective_parameters(
            result["document"], provider_id, model, config_dir=get_config_service().config_dir,
        ),
    }


@router.get("/providers/{provider_id}")
def get_provider(provider_id: str, source: str = "draft"):
    result = get_config_service().read(_source(source))
    provider = _provider(result["document"], provider_id)
    model_names = {model["model"] for model in provider["models"]}
    return {
        "revision": result["revision"],
        "provider": provider,
        "pricing": [
            p
            for p in result["document"]["pricing"]
            if p["provider_id"] == provider_id
        ],
        "effective_parameters": {
            model: effective_parameters(result["document"], provider_id, model)
            for model in model_names
        },
    }


@router.put("/providers/{provider_id}")
def put_provider(provider_id: str, body: ValueBody, request: Request):
    if not isinstance(body.value, dict) or body.value.get("id") != provider_id:
        raise ConfigError("invalid_field", "Provider id must match the URL", field_path="value.id")

    def transform(document):
        providers = document["providers"]
        for index, provider in enumerate(providers):
            if provider["id"] == provider_id:
                providers[index] = body.value
                break
        else:
            providers.append(body.value)

    result = get_config_service().update(body.expected_draft_revision, transform)
    _audit(request, "update", provider_id)
    return result


@router.patch("/providers/{provider_id}")
def patch_provider(provider_id: str, body: PatchBody, request: Request):
    result = get_config_service().patch_provider(
        provider_id, body.fields, body.expected_draft_revision
    )
    _audit(request, "update", provider_id)
    return result


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str, expected_draft_revision: int, request: Request):
    def transform(document):
        _provider(document, provider_id)
        document["providers"] = [p for p in document["providers"] if p["id"] != provider_id]

    try:
        result = get_config_service().update(expected_draft_revision, transform)
    except ConfigError as exc:
        if exc.code in ("invalid_reference", "dependency_conflict"):
            raise ConfigError(
                "dependency_conflict",
                "Provider is referenced",
                details=dependencies(get_config_service().read()["document"]),
            ) from None
        raise
    _audit(request, "delete", provider_id)
    return result


@router.put("/providers/{provider_id}/models")
def put_models(provider_id: str, body: ValueBody, request: Request):
    result = get_config_service().update(
        body.expected_draft_revision,
        lambda document: _provider(document, provider_id).__setitem__("models", body.value),
    )
    _audit(request, "update", provider_id)
    return result


@router.put("/providers/{provider_id}/aliases")
def put_aliases(provider_id: str, body: ValueBody, request: Request):
    result = get_config_service().update(
        body.expected_draft_revision,
        lambda document: _provider(document, provider_id).__setitem__("aliases", body.value),
    )
    _audit(request, "update", provider_id)
    return result


@router.get("/sections/{section}")
def get_section(section: str, source: str = "draft"):
    if section not in ("style_profiles", "pricing", "routes", "settings"):
        raise ConfigError("not_found", "Unknown configuration section")
    result = get_config_service().read(_source(source))
    return {"revision": result["revision"], "value": result["document"][section]}


@router.put("/sections/{section}")
def put_section(section: str, body: ValueBody, request: Request):
    if section not in ("style_profiles", "pricing", "routes", "settings"):
        raise ConfigError("not_found", "Unknown configuration section")
    result = get_config_service().update(
        body.expected_draft_revision, lambda document: document.__setitem__(section, body.value)
    )
    _audit(request, "update", section)
    return result


@router.put("/settings/{name}")
def put_settings(name: str, body: ValueBody, request: Request):
    def transform(document):
        if name not in document["settings"]:
            raise ConfigError("not_found", "Unknown settings section")
        document["settings"][name] = body.value

    result = get_config_service().update(body.expected_draft_revision, transform)
    _audit(request, "update", name)
    return result


@router.post("/batch")
def batch_update(body: BatchBody, request: Request):
    def transform(document):
        for index, change in enumerate(body.changes):
            if set(change) != {"section", "value"} or change["section"] not in (
                "providers",
                "style_profiles",
                "pricing",
                "routes",
                "settings",
            ):
                raise ConfigError(
                    "invalid_field",
                    "Batch item requires section and replacement value",
                    field_path=f"changes.{index}",
                )
            document[change["section"]] = change["value"]

    result = get_config_service().update(body.expected_draft_revision, transform)
    _audit(request, "update", "batch")
    return result
