"""Reusable WiseWay contract validation helpers.

Public entry points for other leaves (LT-02.2, WP-03 fixtures):

- ``load_contract`` / ``resolve_pointer`` / ``deref`` / ``iter_refs``
- ``build_registry`` / ``validate_value`` / ``iter_errors``
- ``iter_example_sites`` / ``run_checks``
"""

from .examples import ExampleSite, iter_example_sites, run_example_checks
from .loading import (
    CONTRACT_URI,
    RefError,
    build_registry,
    deref,
    iter_refs,
    load_contract,
    parse_pointer,
    pointer,
    resolve_pointer,
)
from .report import CheckResult, Failure, Report
from .schemas import format_error, iter_errors, make_validator, validate_value
from .verify import run_checks

__all__ = [
    "CONTRACT_URI",
    "CheckResult",
    "ExampleSite",
    "Failure",
    "RefError",
    "Report",
    "build_registry",
    "deref",
    "format_error",
    "iter_errors",
    "iter_example_sites",
    "iter_refs",
    "load_contract",
    "make_validator",
    "parse_pointer",
    "pointer",
    "resolve_pointer",
    "run_checks",
    "run_example_checks",
    "validate_value",
]
