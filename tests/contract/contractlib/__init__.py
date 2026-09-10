"""Reusable WiseWay contract validation helpers.

Public entry points for other leaves (LT-02.2, WP-03 fixtures):

- ``load_contract`` / ``resolve_pointer`` / ``deref`` / ``iter_refs``
- ``build_registry`` / ``validate_value`` / ``iter_errors``
- ``iter_example_sites`` / ``run_checks``
"""

from .examples import ExampleSite, iter_example_sites, resolve_example_value, run_example_checks
from .fixture_checks import run_fixture_checks
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
from .semantic import (
    finite_links,
    link_errors,
    media_example_pointer,
    rule_set_consistency_errors,
    run_semantic_checks,
    semantic_errors,
    validate_fixture,
)
from .verify import run_checks
from . import batch_outcomes, dictionary_lifecycle, preview_preflight, queue_selections, rule_expectations, search_expectations, synthetic

__all__ = [
    "batch_outcomes",
    "dictionary_lifecycle",
    "preview_preflight",
    "queue_selections",
    "rule_expectations",
    "search_expectations",
    "CONTRACT_URI",
    "CheckResult",
    "ExampleSite",
    "Failure",
    "RefError",
    "Report",
    "build_registry",
    "deref",
    "finite_links",
    "format_error",
    "iter_errors",
    "iter_example_sites",
    "iter_refs",
    "link_errors",
    "load_contract",
    "make_validator",
    "media_example_pointer",
    "parse_pointer",
    "pointer",
    "resolve_example_value",
    "resolve_pointer",
    "rule_set_consistency_errors",
    "run_checks",
    "run_example_checks",
    "run_fixture_checks",
    "run_semantic_checks",
    "semantic_errors",
    "synthetic",
    "validate_fixture",
    "validate_value",
]
