"""Small, deterministic normalization helpers for source metadata."""

from __future__ import annotations

import re
import unicodedata

_DOI_PREFIX = re.compile(
    r"^(?:(?:https?://)?(?:www\.)?(?:dx\.)?doi\.org/|doi:\s*)",
    flags=re.IGNORECASE,
)
_DOI_TRAILING_PUNCTUATION = frozenset(
    ".,;:!?)]}" + "'\"" + "。！？；：，、）》】》〉」』"
)


def normalize_title(value: str | None) -> str | None:
    """Return a stable comparison form for a bibliographic title.

    Unicode compatibility characters are folded with NFKC, all whitespace runs
    become one regular space, and casefolding makes ASCII comparisons
    case-insensitive while leaving Chinese characters unchanged.
    """

    if value is None:
        return None

    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    return normalized or None


def normalize_doi(value: str | None) -> str | None:
    """Canonicalize a DOI while preserving its meaningful suffix.

    Common DOI URLs and the ``doi:`` label are removed. Citation punctuation
    accidentally copied after a DOI is stripped, and the result is casefolded.
    Empty values return ``None``.
    """

    if value is None:
        return None

    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    if not normalized:
        return None

    normalized = _DOI_PREFIX.sub("", normalized)
    normalized = normalized.strip()
    while normalized and normalized[-1] in _DOI_TRAILING_PUNCTUATION:
        normalized = normalized[:-1].rstrip()

    normalized = normalized.casefold()
    return normalized or None
