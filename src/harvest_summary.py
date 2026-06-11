"""Harvest run summary persistence and formatting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from src.census_seed import Jurisdiction, STATE_FIPS
from src.paths import LAST_HARVEST_SUMMARY_JSON


@dataclass
class PrepareStats:
    candidates_eligible: int = 0
    generic_skipped: int = 0
    mismatch_skipped: int = 0
    duplicate_email: int = 0
    duplicate_contact_jurisdiction: int = 0
    duplicate_source_name: int = 0
    duplicate_email_jurisdiction: int = 0
    merged_updates: int = 0
    new_added: int = 0

    @property
    def duplicates_skipped_total(self) -> int:
        return (
            self.duplicate_email
            + self.duplicate_contact_jurisdiction
            + self.duplicate_source_name
            + self.duplicate_email_jurisdiction
        )


@dataclass
class HarvestRunSummary:
    run_started_at: str = ""
    run_completed_at: str = ""
    config_states: list[str] = field(default_factory=list)
    min_population: int = 0
    max_population: int = 0
    limit: int = 0
    include_counties: bool = False
    deep_mode: bool = False
    unsupported_states: list[str] = field(default_factory=list)
    jurisdictions_considered_count: int = 0
    jurisdictions_skipped_existing_count: int = 0
    jurisdictions_processed_count: int = 0
    candidates_found_count: int = 0
    candidates_added_count: int = 0
    duplicates_skipped_count: int = 0
    duplicate_email: int = 0
    duplicate_contact_jurisdiction: int = 0
    duplicate_source_name: int = 0
    duplicate_email_jurisdiction: int = 0
    generic_skipped: int = 0
    rejected_count: int = 0
    total_outreach_contacts_after: int = 0
    processed_jurisdictions: list[dict[str, str]] = field(default_factory=list)
    skipped_existing_jurisdictions: list[dict[str, str]] = field(default_factory=list)
    top_rejection_reasons: list[dict[str, str | int]] = field(default_factory=list)

    def config_line(self) -> str:
        states = ",".join(self.config_states)
        return (
            f"states={states}; population={self.min_population:,}–{self.max_population:,}; "
            f"limit={self.limit}"
        )

    def format_message(self) -> str:
        lines = [
            "Harvest complete:",
            f"• Config: {self.config_line()}",
        ]
        if self.unsupported_states:
            lines.append(
                f"• Unsupported states (not seeded): {', '.join(self.unsupported_states)}"
            )
        lines.extend(
            [
                f"• Jurisdictions considered: {self.jurisdictions_considered_count}",
                f"• Already represented and skipped: {self.jurisdictions_skipped_existing_count}",
                f"• Jurisdictions processed: {self.jurisdictions_processed_count}",
                f"• Candidates found before filtering: {self.candidates_found_count}",
                f"• Added new contacts: {self.candidates_added_count}",
            ]
        )
        dup_total = self.duplicates_skipped_count
        if dup_total:
            lines.append(f"• Duplicate contacts skipped: {dup_total}")
            if self.duplicate_email:
                lines.append(f"  – duplicate email: {self.duplicate_email}")
            if self.duplicate_contact_jurisdiction:
                lines.append(
                    f"  – duplicate contact/jurisdiction: {self.duplicate_contact_jurisdiction}"
                )
            if self.duplicate_source_name:
                lines.append(f"  – duplicate source/name: {self.duplicate_source_name}")
            if self.duplicate_email_jurisdiction:
                lines.append(
                    f"  – duplicate email/jurisdiction key: {self.duplicate_email_jurisdiction}"
                )
        if self.generic_skipped:
            lines.append(f"• Generic contacts skipped: {self.generic_skipped}")
        if self.rejected_count:
            lines.append(f"• Rejected contacts: {self.rejected_count}")
        lines.append(f"• Total CRM contacts: {self.total_outreach_contacts_after}")
        if self.top_rejection_reasons:
            lines.append("")
            lines.append("Top rejection reasons:")
            for item in self.top_rejection_reasons[:8]:
                reason = item.get("reason") or "(success)"
                lines.append(f"• {reason}: {item.get('count', 0)}")
        if self.candidates_added_count == 0:
            lines.append("")
            lines.append(self._zero_contacts_explanation())
        return "\n".join(lines)

    def _zero_contacts_explanation(self) -> str:
        parts = [
            "No new contacts added.",
            f"{self.jurisdictions_processed_count} jurisdictions processed.",
        ]
        if self.jurisdictions_skipped_existing_count:
            parts.append(
                f"{self.jurisdictions_skipped_existing_count} already in CRM were skipped."
            )
        for item in self.top_rejection_reasons[:6]:
            reason = item.get("reason") or ""
            count = int(item.get("count", 0))
            if not reason:
                continue
            if reason == "no_official_site_found":
                parts.append(f"{count} had no official site found.")
            elif reason == "no_planning_contact_found":
                parts.append(f"{count} had no planning contact found.")
            elif reason == "only_generic_email_found":
                parts.append(f"{count} had only generic emails.")
            elif count:
                parts.append(f"{count} — {reason}.")
        if self.duplicates_skipped_count:
            parts.append(f"{self.duplicates_skipped_count} produced contacts already in CRM.")
        return " ".join(parts)

    def print_summary(self) -> None:
        print(self.format_message())


def jurisdiction_record(j: Jurisdiction) -> dict[str, str]:
    return {
        "state": j.state,
        "jurisdiction_name": j.jurisdiction_name,
        "geography_type": j.geography_type,
        "population": str(j.population),
    }


def represented_jurisdiction_keys(rows: list[dict[str, str]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for row in rows:
        name = (row.get("jurisdiction_name") or "").strip()
        state = (row.get("state") or "").strip().upper()
        if name and state:
            keys.add((state, name))
    return keys


def partition_jurisdictions(
    jurisdictions: list[Jurisdiction],
    represented: set[tuple[str, str]],
) -> tuple[list[Jurisdiction], list[Jurisdiction]]:
    pending: list[Jurisdiction] = []
    skipped: list[Jurisdiction] = []
    for j in jurisdictions:
        key = (j.state.upper(), j.jurisdiction_name.strip())
        if key in represented:
            skipped.append(j)
        else:
            pending.append(j)
    return pending, skipped


def unsupported_config_states(states: list[str]) -> list[str]:
    return sorted({s.upper() for s in states if s.upper() not in STATE_FIPS})


def save_harvest_summary(summary: HarvestRunSummary) -> None:
    LAST_HARVEST_SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    LAST_HARVEST_SUMMARY_JSON.write_text(
        json.dumps(asdict(summary), indent=2),
        encoding="utf-8",
    )


def load_harvest_summary() -> HarvestRunSummary | None:
    if not LAST_HARVEST_SUMMARY_JSON.exists():
        return None
    try:
        raw = json.loads(LAST_HARVEST_SUMMARY_JSON.read_text(encoding="utf-8"))
        return HarvestRunSummary(**raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
