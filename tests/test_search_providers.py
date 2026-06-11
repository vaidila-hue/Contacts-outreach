"""Tests for dependency check and DDGS error handling."""

import sys
import types

import pytest


def test_verify_dependencies_exits_when_ddgs_missing(monkeypatch):
    import builtins
    import src.deps_check as deps

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ddgs":
            raise ImportError("No module named 'ddgs'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit):
        deps.verify_dependencies()


def test_ddgs_search_raises_clear_message_when_ddgs_missing(monkeypatch):
    import builtins
    import src.search_providers as sp

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ddgs":
            raise ImportError("No module named 'ddgs'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="DDGS search provider unavailable"):
        sp._ddgs_search("test query")


def test_ddgs_search_records_and_raises_on_provider_failure(monkeypatch):
    import src.search_providers as sp

    class BrokenDDGS:
        def text(self, query, max_results=5):
            raise TimeoutError("upstream timeout")

    fake_ddgs = types.ModuleType("ddgs")
    fake_ddgs.DDGS = BrokenDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_ddgs)
    sp.consume_search_errors()
    with pytest.raises(sp.SearchProviderError, match="DDGS search failed"):
        sp._ddgs_search("South Burlington VT Planning Director")
    errors = sp.peek_search_errors()
    assert len(errors) == 1
    assert "South Burlington VT Planning Director" in errors[0]
