"""Smoke test: package imports and exposes a non-empty version string."""

from __future__ import annotations


def test_package_imports_and_has_version() -> None:
    import tracecaliper

    assert isinstance(tracecaliper.__version__, str)
    assert tracecaliper.__version__.strip() != ""
