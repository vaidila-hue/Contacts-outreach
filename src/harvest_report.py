"""Detailed harvest analysis and markdown report generation."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.harvest_config import HarvestConfig
from src.harvest_summary import HarvestRunSummary, load_harvest_summary
from src.paths import (
    DIAGNOSTICS_CSV,
    LAST_HARVEST_DIAGNOSTICS_JSON,
    LAST_HARVEST_REPORT_MD,
    REJECTED_CSV,
    WORKING_CSV,
)


@dataclass
class RunAnalysis:
    discovery_implementation: str = "unknown"
    resolver_method_counts: dict[str, int] = field(default_factory=dict)
    official_sites_resolved_count: int = 0
    planning_fallback_used_count: int = 0
    avg_search_queries: float = 0.0
    max_search_queries_config: int = 0
    rejection_breakdown: dict[str, int] = field(default_factory=dict)
    top_failures: list[dict[str, str]] = field(default_factory=list)
    success_samples: list[dict[str, str]] = field(default_factory=list)
    generic_email_samples: list[dict[str, str]] = field(default_factory=list)
    discovery_miss_samples: list[dict[str, str]] = field(default_factory=list)
    recommendation: str = ""
    recommendation_code: str = ""


def discovery_implementation_label() -> str:
    """Return label for deployed discovery code path."""
    try:
        from src.directory_harvest import _resolve_official_site  # noqa: F401
        from src.site_discovery import resolve_official_site  # noqa: F401

        if HarvestConfig().max_search_queries_per_jurisdiction >= 8:
            return "site_discovery_v1"
        return "site_discovery_partial"
    except ImportError:
        return "legacy"


def _read_csv(path: Path, columns: list[str] | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _detect_run_time_discovery(
    rejected_in_run: list[dict[str, str]],
    diagnostics_rows: list[dict[str, str]],
) -> str:
    if diagnostics_rows and any((r.get("resolver_method") or "").strip() for r in diagnostics_rows):
        return discovery_implementation_label()
    legacy_markers = sum(
        1
        for r in rejected_in_run
        if "guess + one search" in (r.get("notes") or "").lower()
    )
    if legacy_markers >= 3:
        return "legacy"
    if diagnostics_rows:
        return discovery_implementation_label()
    return "legacy (inferred)"


def _processed_keys(summary: HarvestRunSummary) -> set[tuple[str, str]]:
    return {
        (j["state"].upper(), j["jurisdiction_name"].strip())
        for j in summary.processed_jurisdictions
    }


def analyze_diagnostics_rows(rows: list[dict[str, str]]) -> dict[str, object]:
    if not rows:
        return {
            "resolver_method_counts": {},
            "official_sites_resolved_count": 0,
            "planning_fallback_used_count": 0,
            "avg_search_queries": 0.0,
            "rejection_breakdown": {},
        }
    resolver_counts = Counter(
        (r.get("resolver_method") or "").strip() or "(none)" for r in rows
    )
    official_resolved = sum(1 for r in rows if (r.get("official_domain") or "").strip())
    planning_fallback = sum(
        1 for r in rows if (r.get("planning_fallback_used") or "").lower() == "yes"
    )
    search_runs = [int(r.get("search_queries_run") or 0) for r in rows]
    avg_search = sum(search_runs) / len(search_runs) if search_runs else 0.0
    rejection = Counter(
        (r.get("final_rejection_reason") or "").strip() or "(found contact)" for r in rows
    )
    return {
        "resolver_method_counts": dict(resolver_counts),
        "official_sites_resolved_count": official_resolved,
        "planning_fallback_used_count": planning_fallback,
        "avg_search_queries": round(avg_search, 2),
        "rejection_breakdown": dict(rejection),
    }


def _failure_row(
    jurisdiction: str,
    state: str,
    reason: str,
    *,
    notes: str = "",
    official_domain: str = "",
    resolver_method: str = "",
    pages_fetched: str = "",
    sources: str = "",
) -> dict[str, str]:
    return {
        "jurisdiction_name": jurisdiction,
        "state": state,
        "reason": reason,
        "notes": notes,
        "official_domain": official_domain,
        "resolver_method": resolver_method,
        "pages_fetched": pages_fetched,
        "sources": sources,
    }


def analyze_harvest_run(
    summary: HarvestRunSummary,
    *,
    diagnostics_rows: list[dict[str, str]] | None = None,
    rejected_rows: list[dict[str, str]] | None = None,
    working_rows: list[dict[str, str]] | None = None,
) -> RunAnalysis:
    diagnostics_rows = diagnostics_rows or []
    rejected_rows = rejected_rows or _read_csv(REJECTED_CSV)
    working_rows = working_rows or _read_csv(WORKING_CSV)
    processed = _processed_keys(summary)

    diag_by_key = {
        (r.get("state", "").upper(), r.get("jurisdiction_name", "").strip()): r
        for r in diagnostics_rows
    }
    diag_stats = analyze_diagnostics_rows(diagnostics_rows)

    rejected_in_run = [
        r
        for r in rejected_rows
        if (r.get("state", "").upper(), r.get("jurisdiction_name", "").strip()) in processed
    ]
    working_in_run = [
        r
        for r in working_rows
        if (r.get("state", "").upper(), r.get("jurisdiction_name", "").strip()) in processed
    ]

    rejection = Counter(r.get("rejection_reason", "") for r in rejected_in_run)
    if not rejection and diag_stats["rejection_breakdown"]:
        rejection = Counter(diag_stats["rejection_breakdown"])

    analysis = RunAnalysis(
        discovery_implementation=_detect_run_time_discovery(rejected_in_run, diagnostics_rows),
        resolver_method_counts=diag_stats["resolver_method_counts"],
        official_sites_resolved_count=int(diag_stats["official_sites_resolved_count"]),
        planning_fallback_used_count=int(diag_stats["planning_fallback_used_count"]),
        avg_search_queries=float(diag_stats["avg_search_queries"]),
        max_search_queries_config=HarvestConfig().max_search_queries_per_jurisdiction,
        rejection_breakdown=dict(rejection),
    )

    failures: list[dict[str, str]] = []
    for r in rejected_in_run:
        key = (r.get("state", "").upper(), r.get("jurisdiction_name", "").strip())
        d = diag_by_key.get(key, {})
        failures.append(
            _failure_row(
                r.get("jurisdiction_name", ""),
                r.get("state", ""),
                r.get("rejection_reason", ""),
                notes=(r.get("notes") or "")[:200],
                official_domain=d.get("official_domain", ""),
                resolver_method=d.get("resolver_method", ""),
                pages_fetched=d.get("pages_fetched", ""),
                sources=(r.get("sources") or "")[:120],
            )
        )
    failures.sort(key=lambda x: (x["reason"], x["state"], x["jurisdiction_name"]))
    analysis.top_failures = failures[:20]

    for r in working_in_run[:8]:
        key = (r.get("state", "").upper(), r.get("jurisdiction_name", "").strip())
        d = diag_by_key.get(key, {})
        analysis.success_samples.append(
            {
                "jurisdiction_name": r.get("jurisdiction_name", ""),
                "state": r.get("state", ""),
                "email": r.get("email", ""),
                "contact_name": r.get("contact_name", ""),
                "official_domain": d.get("official_domain", r.get("jurisdiction_url", "")),
                "resolver_method": d.get("resolver_method", ""),
            }
        )

    generic = [f for f in failures if f["reason"] == "only_generic_email_found"]
    for g in generic[:12]:
        notes = g.get("notes", "")
        named_hint = "named email in raw list" if "@" in notes and "planning@" not in notes.split(",")[0] else ""
        analysis.generic_email_samples.append(
            {
                **g,
                "named_planner_likely": named_hint or "check notes/sources",
            }
        )

    for name in ("Merced", "Bloomington", "San Leandro", "Santa Barbara", "Citrus Heights"):
        for f in failures:
            if f["jurisdiction_name"] == name and f["reason"] == "no_official_site_found":
                analysis.discovery_miss_samples.append(f)
                break

    analysis.recommendation_code, analysis.recommendation = _recommendation(
        summary, analysis, diagnostics_rows
    )
    return analysis


def _recommendation(
    summary: HarvestRunSummary,
    analysis: RunAnalysis,
    diagnostics_rows: list[dict[str, str]],
) -> tuple[str, str]:
    impl = analysis.discovery_implementation
    deployed = discovery_implementation_label()
    no_site = analysis.rejection_breakdown.get("no_official_site_found", 0)
    processed = max(summary.jurisdictions_processed_count, 1)
    no_site_rate = no_site / processed

    if impl.startswith("legacy") or not diagnostics_rows:
        return (
            "B",
            f"The latest harvest ran on the **legacy** resolver (single search, .gov-only). "
            f"Current deployed code is `{deployed}`. Re-run Find More Contacts — "
            f"`diagnose-discovery` already resolves Merced, Bloomington, and similar cases.",
        )

    if no_site_rate >= 0.4:
        return (
            "B",
            "Official-site resolution remains weak for many jurisdictions despite multi-query search. "
            "Extend discovery (deeper crawl, manual URL seeds, county .com domains) before widening search coverage.",
        )

    generic = analysis.rejection_breakdown.get("only_generic_email_found", 0)
    no_contact = analysis.rejection_breakdown.get("no_planning_contact_found", 0)
    if generic + no_contact >= processed * 0.35:
        return (
            "C",
            "Discovery often succeeds but **contact extraction** is the bottleneck: generic department emails "
            "or missing title matches. Improve staff-page crawl depth and allowlisted title pairing.",
        )

    if summary.candidates_added_count == 0 and summary.duplicates_skipped_count > summary.candidates_found_count:
        return (
            "A",
            "Harvest mechanics work; new jurisdictions are mostly duplicates of CRM contacts. "
            "Broaden states/population range or refresh stale jurisdictions.",
        )

    return (
        "A",
        "Harvest and discovery are performing adequately for the configured slice. "
        "Tune coverage (limit, states, deep mode) to increase yield.",
    )


def enrich_summary(summary: HarvestRunSummary, analysis: RunAnalysis) -> HarvestRunSummary:
    summary.discovery_implementation = analysis.discovery_implementation
    summary.max_search_queries_config = analysis.max_search_queries_config
    summary.resolver_method_counts = analysis.resolver_method_counts
    summary.official_sites_resolved_count = analysis.official_sites_resolved_count
    summary.planning_fallback_used_count = analysis.planning_fallback_used_count
    summary.avg_search_queries = analysis.avg_search_queries
    summary.no_official_site_count = analysis.rejection_breakdown.get("no_official_site_found", 0)
    summary.no_planning_contact_count = analysis.rejection_breakdown.get("no_planning_contact_found", 0)
    summary.only_generic_email_count = analysis.rejection_breakdown.get("only_generic_email_found", 0)
    summary.top_failures = analysis.top_failures
    summary.recommendation_code = analysis.recommendation_code
    summary.recommendation = analysis.recommendation
    return summary


def _fmt_ts(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


def format_harvest_dashboard(summary: HarvestRunSummary) -> dict[str, str]:
    """Short labels for CRM dashboard panel."""
    no_contact = summary.no_official_site_count + summary.no_planning_contact_count
    if not no_contact and summary.top_rejection_reasons:
        no_contact = sum(
            int(item.get("count", 0))
            for item in summary.top_rejection_reasons
            if item.get("reason") in ("no_official_site_found", "no_planning_contact_found")
        )
    return {
        "last_run": _fmt_ts(summary.run_completed_at or summary.run_started_at),
        "jurisdictions_processed": str(summary.jurisdictions_processed_count),
        "skipped_existing": str(summary.jurisdictions_skipped_existing_count),
        "new_contacts": str(summary.candidates_added_count),
        "duplicates_skipped": str(summary.duplicate_after_crawl_count or summary.duplicates_skipped_count),
        "no_contact_jurisdictions": str(no_contact or summary.rejected_count),
        "discovery_impl": summary.discovery_implementation or "unknown",
    }


def render_harvest_report_md(summary: HarvestRunSummary, analysis: RunAnalysis) -> str:
    lines = [
        "# Last Harvest Report",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Harvest started:** {_fmt_ts(summary.run_started_at)}",
        f"**Harvest completed:** {_fmt_ts(summary.run_completed_at)}",
        "",
        "## Config",
        "",
        f"- States: {', '.join(summary.config_states)}",
        f"- Population: {summary.min_population:,}–{summary.max_population:,}",
        f"- Limit: {summary.limit}",
        f"- Include counties: {summary.include_counties}",
        f"- Deep mode: {summary.deep_mode}",
        f"- Max search queries (current code): {analysis.max_search_queries_config}",
        f"- Discovery at harvest run: **{analysis.discovery_implementation}**",
        f"- Discovery deployed now: **{discovery_implementation_label()}**",
        "",
        "## Summary metrics",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Jurisdictions considered | {summary.jurisdictions_considered_count} |",
        f"| Skipped (already in CRM) | {summary.jurisdictions_skipped_existing_count} |",
        f"| Processed | {summary.jurisdictions_processed_count} |",
        f"| Contacts found (pre-filter) | {summary.candidates_found_count} |",
        f"| Contacts added | {summary.candidates_added_count} |",
        f"| Duplicate contacts after crawl | {summary.duplicate_after_crawl_count or summary.duplicates_skipped_count} |",
        f"| Duplicate jurisdiction skips | {summary.duplicate_contact_jurisdiction} |",
        f"| Official sites resolved | {analysis.official_sites_resolved_count} |",
        f"| Planning fallback used | {analysis.planning_fallback_used_count} |",
        f"| Avg search queries / jurisdiction | {analysis.avg_search_queries} |",
        "",
        "## Rejection breakdown",
        "",
    ]
    for reason, count in sorted(
        analysis.rejection_breakdown.items(), key=lambda x: -x[1]
    ):
        lines.append(f"- **{reason}**: {count}")

    if analysis.resolver_method_counts:
        lines.extend(["", "## Resolver methods", ""])
        for method, count in sorted(
            analysis.resolver_method_counts.items(), key=lambda x: -x[1]
        ):
            lines.append(f"- `{method}`: {count}")
    else:
        lines.extend(
            [
                "",
                "## Resolver methods",
                "",
                "_No per-jurisdiction diagnostics persisted for this run._",
            ]
        )

    lines.extend(["", "## Top 20 failures", ""])
    if analysis.top_failures:
        lines.append("| State | Jurisdiction | Reason | Domain | Notes |")
        lines.append("|-------|--------------|--------|--------|-------|")
        for f in analysis.top_failures:
            notes = (f.get("notes") or "").replace("|", "/")[:80]
            domain = f.get("official_domain") or "—"
            lines.append(
                f"| {f['state']} | {f['jurisdiction_name']} | {f['reason']} | {domain} | {notes} |"
            )
    else:
        lines.append("_None recorded._")

    lines.extend(["", "## Sample successes", ""])
    for s in analysis.success_samples:
        lines.append(
            f"- **{s['jurisdiction_name']}, {s['state']}** — {s.get('contact_name') or '(no name)'} "
            f"<{s.get('email', '')}> resolver={s.get('resolver_method') or 'n/a'}"
        )
    if not analysis.success_samples:
        lines.append("_None._")

    lines.extend(["", "## Sample generic-email failures", ""])
    for g in analysis.generic_email_samples:
        lines.append(
            f"- **{g['jurisdiction_name']}, {g['state']}** — {g.get('notes', '')[:120]}"
        )
        if g.get("sources"):
            lines.append(f"  - sources: {g['sources'][:100]}")

    lines.extend(["", "## Discovery miss samples (pre-fix cases)", ""])
    if analysis.discovery_miss_samples:
        for d in analysis.discovery_miss_samples:
            lines.append(
                f"- **{d['jurisdiction_name']}, {d['state']}** — {d.get('notes', '')[:100]}"
            )
    else:
        lines.append("_None in this run (or already resolved)._")

    lines.extend(
        [
            "",
            "## Comparison note",
            "",
            "The run archived in `last_harvest_summary.json` completed **before** the "
            "`site_discovery_v1` commit when timestamps precede deployment. "
            "`diagnose-discovery` on Merced CA and Bloomington MN now resolves official domains; "
            "the legacy harvest logged `(guess + one search)` and `search_queries_run=1`.",
            "",
            "## Recommendation",
            "",
            f"**{analysis.recommendation_code})** {analysis.recommendation}",
            "",
        ]
    )
    return "\n".join(lines)


def save_harvest_report(
    summary: HarvestRunSummary,
    analysis: RunAnalysis,
    diagnostics_rows: list[dict[str, str]] | None = None,
) -> Path:
    LAST_HARVEST_REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    LAST_HARVEST_REPORT_MD.write_text(
        render_harvest_report_md(summary, analysis),
        encoding="utf-8",
    )
    if diagnostics_rows is not None:
        import json

        LAST_HARVEST_DIAGNOSTICS_JSON.write_text(
            json.dumps(diagnostics_rows, indent=2),
            encoding="utf-8",
        )
    return LAST_HARVEST_REPORT_MD


def build_report_from_summary_file() -> Path | None:
    """Regenerate markdown report from saved summary + CSVs (no re-harvest)."""
    summary = load_harvest_summary()
    if not summary:
        return None
    diag_rows: list[dict[str, str]] = []
    if LAST_HARVEST_DIAGNOSTICS_JSON.exists():
        import json

        try:
            diag_rows = json.loads(LAST_HARVEST_DIAGNOSTICS_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            diag_rows = []
    if not diag_rows and DIAGNOSTICS_CSV.exists():
        diag_rows = _read_csv(DIAGNOSTICS_CSV)
    analysis = analyze_harvest_run(summary, diagnostics_rows=diag_rows)
    enrich_summary(summary, analysis)
    from src.harvest_summary import save_harvest_summary

    save_harvest_summary(summary)
    return save_harvest_report(summary, analysis, diagnostics_rows=diag_rows or None)
