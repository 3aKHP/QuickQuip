"""Protect retained unpublished drafts during server configuration exchange."""

from quickquip.configuration.errors import ConfigError
from quickquip.configuration.validation import validate_asset_tree as validate_asset_tree


def protect_draft_assets(document, before, target):
    """Asset changes must not introduce a new failure in a retained unpublished draft."""
    from quickquip.config_sync.bundle import validate_bundle

    previous_error = None
    try:
        validate_bundle({**before, "document": document})
    except ConfigError as exc:
        previous_error = (exc.code, exc.field_path)
    try:
        validate_bundle({**target, "document": document})
    except ConfigError as exc:
        if (exc.code, exc.field_path) != previous_error:
            raise ConfigError(
                "draft_conflict", "Asset changes break the retained draft", exc.field_path
            ) from exc
