"""Traceable medication-safety rule contracts without prescribing logic.

Rules record what an authorized source says. They do not determine whether a
specific patient should receive, stop, or change a medicine.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SafetyCategory(str, Enum):
    """Safety topics that require explicit evidence and medical review."""

    contraindication = "contraindication"
    interaction = "interaction"
    special_population = "special_population"
    organ_impairment = "organ_impairment"
    monitoring = "monitoring"
    withdrawal = "withdrawal"


class SafetyRiskLevel(str, Enum):
    """Governance risk, not an individual patient's risk assessment."""

    high = "high"
    critical = "critical"


class MedicationSafetyRule(BaseModel):
    """One source-grounded medication safety statement for human review."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    source_unit_id: str
    medication_name: str
    category: SafetyCategory
    risk_level: SafetyRiskLevel
    statement: str
    source_locator: str
    version: str
    safety_review_status: str = "draft"
    affected_population: str | None = None
    related_medications: list[str] = Field(default_factory=list)

    @field_validator(
        "rule_id",
        "source_unit_id",
        "medication_name",
        "statement",
        "source_locator",
        "version",
    )
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("medication safety fields must not be blank")
        return value

    @field_validator("statement")
    @classmethod
    def reject_prescribing_instruction(cls, value: str) -> str:
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:mg|g|ml|mcg)\b", value, re.I):
            raise ValueError(
                "medication safety rules must not contain dosage instructions"
            )
        if re.search(r"\b(start|take)\b.*\b(for all|daily)\b", value, re.I):
            raise ValueError(
                "medication safety rules must not contain prescribing instructions"
            )
        return value

    @field_validator("affected_population")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("related_medications")
    @classmethod
    def normalize_related_medications(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("related medications must not contain blanks")
        return list(dict.fromkeys(normalized))
