"""Optional local authorization registry for declared review roles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReviewerRegistryError(ValueError):
    """Raised when a configured reviewer registry is invalid or denies access."""


def authorize_reviewer(
    registry_path: Path | None, *, reviewer: str, reviewer_role: str
) -> None:
    """Authorize a declared role when a local registry is configured.

    The registry is an operational allow-list, not a verification of any
    professional credential. A missing configuration keeps local single-user
    workflows available while deployments can opt into authorization.
    """

    if registry_path is None:
        return
    registry = _load_registry(registry_path)
    allowed_roles = registry.get(reviewer)
    if allowed_roles is None or reviewer_role not in allowed_roles:
        raise ReviewerRegistryError(
            f"reviewer {reviewer!r} is not authorized for role {reviewer_role!r}"
        )


def _load_registry(path: Path) -> dict[str, set[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ReviewerRegistryError(f"cannot read reviewer registry: {path}") from error
    except json.JSONDecodeError as error:
        message = f"invalid reviewer registry JSON: {path}"
        raise ReviewerRegistryError(message) from error

    reviewers = _require_list(data, "reviewers")
    registry: dict[str, set[str]] = {}
    for entry in reviewers:
        if not isinstance(entry, dict):
            raise ReviewerRegistryError("reviewer registry entries must be objects")
        reviewer = _require_nonblank(entry.get("id"), "reviewer id")
        roles = _require_list(entry, "roles")
        normalized_roles = {_require_nonblank(role, "reviewer role") for role in roles}
        if not normalized_roles:
            raise ReviewerRegistryError("reviewer roles must not be empty")
        if reviewer in registry:
            raise ReviewerRegistryError(f"duplicate reviewer id: {reviewer}")
        registry[reviewer] = normalized_roles
    return registry


def _require_list(data: Any, key: str) -> list[Any]:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise ReviewerRegistryError(f"reviewer registry requires a {key!r} list")
    return data[key]


def _require_nonblank(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewerRegistryError(f"{label} is required")
    return value.strip()
