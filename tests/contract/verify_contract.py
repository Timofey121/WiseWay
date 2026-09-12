#!/usr/bin/env python3
"""Executable OpenAPI contract verifier for WiseWay.

Usage (from the repository root, Windows):

    .venv-contract\\Scripts\\python.exe tests\\contract\\verify_contract.py

or with an explicit contract path:

    python tests/contract/verify_contract.py contracts/openapi/wiseway-v1.yaml

Exit code is ``0`` only when every check passes.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make ``contractlib`` importable both when run as a script and via discovery.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from contractlib import load_contract, run_checks  # noqa: E402

DEFAULT_CONTRACT = HERE.parents[1] / "contracts" / "openapi" / "wiseway-v1.yaml"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Validate the WiseWay OpenAPI contract.")
    parser.add_argument(
        "contract",
        nargs="?",
        default=str(DEFAULT_CONTRACT),
        help="Path to the OpenAPI YAML document (defaults to the repository contract).",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    contract_path = Path(args.contract)
    if not contract_path.is_file():
        print(f"ERROR: contract not found: {contract_path}", file=sys.stderr)
        return 2
    try:
        document = load_contract(contract_path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors clearly
        print(f"ERROR: cannot parse {contract_path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    report = run_checks(document)
    print(f"Contract: {os.path.relpath(contract_path, HERE.parents[1]) if contract_path.is_absolute() else contract_path}")
    print(f"OpenAPI:  {document.get('openapi')}  info.version: {(document.get('info') or {}).get('version')}")
    print(f"Examples: {report.examples_validated} schema-bound example(s) validated")
    print(f"Semantics: {report.semantics_checked} example(s) checked for semantic invariants")
    print(f"Fixtures: {report.fixtures_validated} public example(s), {report.corpus_files} corpus file(s) and {report.lifecycle_fixtures} lifecycle payload(s) validated")
    print(f"Search expectations: {report.search_scenarios} search, {report.facet_scenarios} facet, {report.error_scenarios} error, {report.race_scenarios} race, {report.format_samples} format scenario(s)")
    print(f"Rule expectations: {report.rule_scenarios} rule, {report.target_scenarios} target, {report.invalid_rule_cases} invalid-rule scenario(s)")
    print(f"Dictionary lifecycle: {report.lifecycle_timeline} timeline, {report.lifecycle_failures} failure, {report.lifecycle_replays} replay, {report.lifecycle_simulations} simulation page(s)")
    print(f"Queue expectations: {report.queue_profiles} profile(s), {report.queue_queries} query(ies), {report.selection_scenarios} selection, {report.selection_errors} error, {report.readiness_sequences} readiness, {report.ownership_scenarios} ownership scenario(s)")
    print(f"Preview/preflight expectations: {report.preview_scenarios} preview(s), {report.preview_rows} row(s), {report.preflight_scenarios} preflight scenario(s), {report.preflight_failures} rejection(s), {report.post_acceptance_outcomes} post-acceptance outcome(s)")
    print(f"Batch/outcome expectations: {report.batch_scenarios} batch(es), {report.batch_pages} page(s), {report.batch_outcomes} outcome(s), {report.batch_summaries} summary(ies), {report.batch_mutations} mutation(s)")
    print(f"Batch scenario expectations: {report.scenario_scenarios} scenario(s), {report.scenario_replays} replay(s), {report.scenario_containment} containment case(s), {report.scenario_audit} audit event(s), {report.scenario_mutations} mutation(s)")
    print(f"Quarantine/return expectations: {report.quarantine_records} record(s), {report.quarantine_scenarios} scenario(s), {report.quarantine_replays} replay(s), {report.quarantine_audit} audit descriptor(s), {report.quarantine_mutations} mutation(s)")
    print(f"Audit expectations: {report.audit_events} event(s), {report.audit_queries} query(ies), {report.audit_actor_pages} actor page(s), {report.audit_updates} updates scenario(s), {report.audit_mutations} mutation(s)")
    print("")
    print(report.format())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
