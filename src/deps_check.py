"""Startup dependency verification."""

from __future__ import annotations

# (import name, pip package name for error message)
REQUIRED_PACKAGES: tuple[tuple[str, str], ...] = (
    ("httpx", "httpx"),
    ("bs4", "beautifulsoup4"),
    ("ddgs", "ddgs"),
    ("dotenv", "python-dotenv"),
    ("pdfplumber", "pdfplumber"),
)


def missing_packages() -> list[str]:
    missing: list[str] = []
    for module_name, pip_name in REQUIRED_PACKAGES:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def verify_dependencies() -> None:
    """Exit with a clear message if required packages are not importable."""
    missing = missing_packages()
    if not missing:
        return
    print("ERROR: Missing required packages:")
    for name in missing:
        print(f"  - {name}")
    print()
    print("Install dependencies with:")
    print("  pip install -r requirements.txt")
    if "ddgs" in missing:
        print()
        print(
            "DDGS search provider unavailable: install dependencies with "
            "pip install -r requirements.txt"
        )
    raise SystemExit(1)
