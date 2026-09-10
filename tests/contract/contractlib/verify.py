"""Top-level contract verification entry point.

``run_checks`` is reusable from tests and future leaves; it returns a
``Report`` instead of exiting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .examples import run_example_checks
from .fixture_checks import run_fixture_checks
from .loading import build_registry
from .report import Report
from .semantic import run_semantic_checks
from .structure import run_structure_checks


def run_checks(
    document: Dict[str, Any],
    registry=None,
    repo_root: Optional[Path] = None,
) -> Report:
    """Run every structural, example, semantic and fixture check."""
    report = Report()
    run_structure_checks(document, report)
    if registry is None:
        registry = build_registry(document)
    run_example_checks(document, report, registry)
    run_semantic_checks(document, report, registry)
    run_fixture_checks(report, registry, repo_root)
    return report
