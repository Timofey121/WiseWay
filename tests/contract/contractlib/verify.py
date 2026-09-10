"""Top-level contract verification entry point.

``run_checks`` is reusable from tests and future leaves; it returns a
``Report`` instead of exiting.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .examples import run_example_checks
from .loading import build_registry
from .report import Report
from .structure import run_structure_checks


def run_checks(document: Dict[str, Any], registry=None) -> Report:
    """Run every structural and example check against a parsed contract."""
    report = Report()
    run_structure_checks(document, report)
    if registry is None:
        registry = build_registry(document)
    run_example_checks(document, report, registry)
    return report
