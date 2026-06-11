"""Build mode flags and run statistics."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

DEFAULT_FAST_DELAY = 0.5
DEFAULT_DEEP_DELAY = 3.0


from src.harvest_config import HarvestConfig


@dataclass
class BuildMode:
    """Controls discovery depth. Directory harvest is the default."""

    deep: bool = False
    include_pdfs: bool = False
    include_plan_signals: bool = False
    person_first: bool = False
    harvest: HarvestConfig = field(default_factory=HarvestConfig)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> BuildMode:
        harvest = HarvestConfig.from_args(args)
        if getattr(args, "deep", False):
            return cls(
                deep=True,
                include_pdfs=True,
                include_plan_signals=True,
                person_first=True,
                harvest=harvest,
            )
        return cls(
            include_pdfs=getattr(args, "include_pdfs", False),
            include_plan_signals=getattr(args, "include_plan_signals", False),
            person_first=getattr(args, "person_first", False),
            harvest=harvest,
        )


@dataclass
class BuildStats:
    search_queries_run: int = 0
    pages_fetched: int = 0
    pdfs_scanned: int = 0
    candidates_found: int = 0
    jurisdictions_processed: int = 0
    elapsed_seconds: float = 0.0

    def record_jurisdiction(
        self,
        *,
        search_queries: int = 0,
        pages: int = 0,
        pdfs: int = 0,
        found: bool = False,
    ) -> None:
        self.search_queries_run += search_queries
        self.pages_fetched += pages
        self.pdfs_scanned += pdfs
        if found:
            self.candidates_found += 1
        self.jurisdictions_processed += 1


def resolve_delay(args: argparse.Namespace) -> float:
    if args.delay is not None:
        return args.delay
    if getattr(args, "deep", False):
        return DEFAULT_DEEP_DELAY
    return DEFAULT_FAST_DELAY
