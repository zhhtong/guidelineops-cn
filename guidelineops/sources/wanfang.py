"""Optional Wanfang API boundary; no undocumented endpoint is guessed."""

from __future__ import annotations

from guidelineops.config import Settings


class WanfangAdapter:
    """Placeholder that explicitly requires documented credentials/API access."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def unavailable_reason(self) -> str:
        return (
            "Wanfang API adapter is disabled until official endpoint documentation "
            "and credentials are configured; use CSV export import instead."
        )
