"""Stable, credential-free configuration errors shared by CLI and HTTP."""

from __future__ import annotations

from typing import Any


class ConfigError(ValueError):
    def __init__(self, code: str, message: str, field_path: str = "", details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_path = field_path
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_path": self.field_path,
            "details": self.details,
        }
