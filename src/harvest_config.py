"""Per-jurisdiction harvest limits and cache flags."""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass
class HarvestConfig:
    max_pages_per_jurisdiction: int = 8
    max_profile_pages_per_jurisdiction: int = 4
    max_directory_pages_per_jurisdiction: int = 3
    max_search_queries_per_jurisdiction: int = 1
    use_fetch_cache: bool = True
    fetch_cache_ttl_days: int = 7
    use_domain_cache: bool = True
    refresh_domain_cache: bool = False
    deep: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> HarvestConfig:
        deep = getattr(args, "deep", False)
        normal_defaults = {
            "max_pages": 10,
            "max_profile": 4,
            "max_directory": 4,
            "max_search": 1,
        }
        deep_defaults = {
            "max_pages": 25,
            "max_profile": 10,
            "max_directory": 8,
            "max_search": 5,
        }
        defaults = deep_defaults if deep else normal_defaults
        return cls(
            max_pages_per_jurisdiction=getattr(args, "max_pages_per_jurisdiction", None)
            or defaults["max_pages"],
            max_profile_pages_per_jurisdiction=getattr(
                args, "max_profile_pages_per_jurisdiction", None
            )
            or defaults["max_profile"],
            max_directory_pages_per_jurisdiction=getattr(
                args, "max_directory_pages_per_jurisdiction", None
            )
            or defaults["max_directory"],
            max_search_queries_per_jurisdiction=getattr(
                args, "max_search_queries_per_jurisdiction", None
            )
            or defaults["max_search"],
            use_fetch_cache=not getattr(args, "no_fetch_cache", False),
            fetch_cache_ttl_days=getattr(args, "fetch_cache_ttl_days", 7),
            use_domain_cache=not getattr(args, "no_domain_cache", False),
            refresh_domain_cache=getattr(args, "refresh_domain_cache", False),
            deep=deep,
        )
