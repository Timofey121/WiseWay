"""Lightweight check reporting for the WiseWay contract verifier.

The reporter is intentionally dependency-free so that it can be reused by
future contract leaves (for example LT-02.2 semantic invariants and WP-03
fixture validation) without pulling in a test framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Failure:
    """A single failed assertion inside one named check."""

    message: str
    location: str = ""

    def render(self) -> str:
        if self.location:
            return f"{self.location}: {self.message}"
        return self.message


@dataclass
class CheckResult:
    """Outcome of one named check (a group of related assertions)."""

    check_id: str
    description: str
    failures: List[Failure] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def add(self, message: str, location: str = "") -> None:
        self.failures.append(Failure(message=message, location=location))


@dataclass
class Report:
    """Aggregated result of a full verification run."""

    checks: List[CheckResult] = field(default_factory=list)
    examples_validated: int = 0
    semantics_checked: int = 0
    fixtures_validated: int = 0
    corpus_files: int = 0
    lifecycle_fixtures: int = 0
    search_scenarios: int = 0
    facet_scenarios: int = 0
    error_scenarios: int = 0
    race_scenarios: int = 0
    format_samples: int = 0
    rule_scenarios: int = 0
    target_scenarios: int = 0
    invalid_rule_cases: int = 0

    def check(self, check_id: str, description: str) -> CheckResult:
        result = CheckResult(check_id=check_id, description=description)
        self.checks.append(result)
        return result

    @property
    def failures(self) -> List[Failure]:
        out: List[Failure] = []
        for check in self.checks:
            out.extend(check.failures)
        return out

    @property
    def failed_check_ids(self) -> List[str]:
        return [c.check_id for c in self.checks if not c.passed]

    @property
    def total_assertions(self) -> int:
        return len(self.checks)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    def format(self) -> str:
        lines: List[str] = []
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(f"[{status}] {check.check_id} - {check.description}")
            for failure in check.failures:
                lines.append(f"        - {failure.render()}")
        lines.append("")
        if self.ok:
            lines.append(f"RESULT: PASS ({len(self.checks)} checks, 0 failures)")
        else:
            lines.append(
                "RESULT: FAIL "
                f"({len(self.checks)} checks, {len(self.failures)} failures in "
                f"{len(self.failed_check_ids)} checks)"
            )
        return "\n".join(lines)
