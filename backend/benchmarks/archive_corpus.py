"""Deterministic synthetic metadata corpora for capacity runs.

This module is intentionally independent from the product search code.  Its
closed-form paths and distributions are the source of benchmark expectations,
not a second implementation of production query parsing or ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
import concurrent.futures
import heapq
import hashlib
import itertools
import re
import time
from typing import Callable

from million import item_path


DIVERSE_SCHEMA_VERSION = "capacity-diverse-v1"
COMPANIES = tuple(f"Company{number:02d}" for number in range(64))
PROJECTS = tuple(f"Project{number:03d}" for number in range(128))
CATEGORIES = tuple(f"Category{number}" for number in range(8))
# Alphabetic tokens keep a family query independent of the numeric item ID.
BASENAME_FAMILIES = tuple(f"Family{first}{second}" for first in "ab" for second in "abcdefghijklmnop")


def baseline_row(number: int) -> dict:
    return {
        "op": "upsert",
        "item_id": f"million-{number:07d}",
        "relative_path": item_path(number),
        "size_bytes": 900_000 + number % 200_001,
        "modified_at": "2026-01-01T00:00:00Z",
    }


def diverse_schema() -> dict:
    """JSON-storable schema: 64 companies, 128 projects and 8 categories."""
    return {
        "schema_set_version": DIVERSE_SCHEMA_VERSION,
        "root_levels": [
            ["level-section", "Раздел", ["Archive"], False],
            ["level-company", "Компания", list(COMPANIES), False],
            ["level-project", "Проект", list(PROJECTS), False],
            ["level-category", "Категория", list(CATEGORIES), False],
        ],
        "tail_by_company": {},
    }


def diverse_components(number: int) -> tuple[str, str, str, str]:
    """Cycle every company/project pair before advancing the category."""
    if number < 0:
        raise ValueError("record number must be non-negative")
    company = COMPANIES[number % len(COMPANIES)]
    project = PROJECTS[(number // len(COMPANIES)) % len(PROJECTS)]
    category = CATEGORIES[(number // (len(COMPANIES) * len(PROJECTS))) % len(CATEGORIES)]
    family = BASENAME_FAMILIES[number % len(BASENAME_FAMILIES)]
    return company, project, category, family


def diverse_row(number: int) -> dict:
    company, project, category, family = diverse_components(number)
    extension = ("pdf", "xlsx", "docx", "csv")[number % 4]
    return {
        "op": "upsert",
        "item_id": f"diverse-{number:09d}",
        "relative_path": f"Archive/{company}/{project}/{category}/{family}-{number:09d}.{extension}",
        "size_bytes": 450_000 + (number * 104_729) % 8_000_000,
        "modified_at": (f"2026-{(number % 12) + 1:02d}-{(number % 28) + 1:02d}T{number % 24:02d}:00:00Z"),
    }


def count_residue(records: int, modulus: int, residue: int) -> int:
    """Count non-negative values below records congruent to residue."""
    if records <= residue:
        return 0
    return (records - 1 - residue) // modulus + 1


def diverse_marker_id(level_id: str, raw_value: str, parents: tuple[str, ...]) -> str:
    """Public marker identity formula, derived from the fixed corpus config."""
    joined = "\x1f".join(
        (ROOT_ID, DIVERSE_SCHEMA_VERSION, level_id, "\x1e".join(parents), raw_value, "value")
    )
    return "marker-" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20]


ROOT_ID = "archive-root"
_NATURAL = re.compile(r"(\d+)")


def _natural(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdecimal() else (1, part.casefold()) for part in _NATURAL.split(value) if part
    )


def _family_numbers(records: int, company: int | None = None):
    if company is None:
        return range(0, records, len(BASENAME_FAMILIES))
    if company != 0:
        raise ValueError("only Company00 is selected by the benchmark oracle")
    return range(0, records, len(COMPANIES))


def _path_ascending_family_numbers(records: int, company: int | None, limit: int):
    companies = (company,) if company is not None else (0, 32)
    emitted = 0
    for company_number in companies:
        for project in range(len(PROJECTS)):
            for category in range(len(CATEGORIES)):
                first = company_number + len(COMPANIES) * project + len(COMPANIES) * len(PROJECTS) * category
                for number in range(first, records, len(COMPANIES) * len(PROJECTS) * len(CATEGORIES)):
                    yield number
                    emitted += 1
                    if emitted == limit:
                        return


def expected_family_ids(
    records: int, field: str, direction: str, limit: int = 100, *, company: int | None = None
) -> list[str]:
    """Independent top-id oracle for the common ``Familyaa`` workload."""
    numbers = _family_numbers(records, company)
    if field == "RELEVANCE" or field == "PATH" and direction == "ASC":
        # Relevance ties always use ascending path, regardless of its DESC API
        # direction.  PATH ASC has the same order for this equal-score corpus.
        ordered = _path_ascending_family_numbers(records, company, limit)
    elif field == "PATH":
        ordered = heapq.nlargest(limit, numbers, key=lambda n: _natural(diverse_row(n)["relative_path"]))
    elif field == "NAME":
        ordered = numbers if direction == "ASC" else range(((records - 1) // 32) * 32, -1, -32)
    else:
        raise ValueError("unsupported sort field")
    return [f"diverse-{number:09d}" for number in itertools.islice(ordered, limit)]


def expected_broad_ids(records: int, limit: int = 100) -> list[str]:
    """Path-tie oracle for the broad alphabetic family-prefix query."""
    values = []
    for company in range(len(COMPANIES)):
        for project in range(len(PROJECTS)):
            for category in range(len(CATEGORIES)):
                first = company + len(COMPANIES) * project + len(COMPANIES) * len(PROJECTS) * category
                for number in range(first, records, len(COMPANIES) * len(PROJECTS) * len(CATEGORIES)):
                    values.append(f"diverse-{number:09d}")
                    if len(values) == limit:
                        return values
    return values


def expected_company_facets(records: int) -> dict[str, int]:
    return {
        COMPANIES[number]: count_residue(records, len(COMPANIES), number)
        for number in range(len(COMPANIES))
        if count_residue(records, len(COMPANIES), number)
    }


def diverse_request(
    query_text: str, *, sort: dict, selected: list[str] | None = None, state: str = "diverse"
) -> dict:
    return {
        "request_state_id": state,
        "root_id": ROOT_ID,
        "schema_set_version": DIVERSE_SCHEMA_VERSION,
        "selected_marker_ids": selected or [],
        "query_text": query_text,
        "sort": sort,
        "facet_prefix": "",
    }


def query_diverse(settings, records: int, repeats: int = 5, clients: int = 50, requests: int = 250) -> dict:
    """Exercise the public route with a corpus-derived correctness/SLA oracle."""
    from fastapi.testclient import TestClient

    from million import PASSWORD, percentile
    from wiseway.app import create_app

    section = diverse_marker_id("level-section", "Archive", ())
    company = diverse_marker_id("level-company", "Company00", ("Archive",))
    common_total = count_residue(records, 32, 0)
    selected_total = count_residue(records, 64, 0)
    rare = records - 1
    cases = [
        ("rare", f"{rare:09d}", {"field": "RELEVANCE", "direction": "DESC"}, [], 1, [f"diverse-{rare:09d}"]),
        ("absent", "no-such-diverse-token", {"field": "RELEVANCE", "direction": "DESC"}, [], 0, []),
        (
            "common_relevance",
            "Familyaa",
            {"field": "RELEVANCE", "direction": "DESC"},
            [],
            common_total,
            expected_family_ids(records, "RELEVANCE", "DESC"),
        ),
        (
            "common_path",
            "Familyaa",
            {"field": "PATH", "direction": "ASC"},
            [],
            common_total,
            expected_family_ids(records, "PATH", "ASC"),
        ),
        (
            "common_name_desc",
            "Familyaa",
            {"field": "NAME", "direction": "DESC"},
            [],
            common_total,
            expected_family_ids(records, "NAME", "DESC"),
        ),
        ("common_path_desc", "Familyaa", {"field": "PATH", "direction": "DESC"}, [], common_total, None),
        (
            "common_modified_desc",
            "Familyaa",
            {"field": "MODIFIED_AT", "direction": "DESC"},
            [],
            common_total,
            None,
        ),
        ("common_size_desc", "Familyaa", {"field": "SIZE", "direction": "DESC"}, [], common_total, None),
        (
            "broad",
            "Family",
            {"field": "RELEVANCE", "direction": "DESC"},
            [],
            records,
            expected_broad_ids(records),
        ),
        (
            "selected_company",
            "Familyaa",
            {"field": "PATH", "direction": "ASC"},
            [section, company],
            selected_total,
            expected_family_ids(records, "PATH", "ASC", company=0),
        ),
    ]
    timings: dict[str, dict[str, float]] = {}
    failures: list[dict] = []
    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:8000"},
            json={"login": "worker-atlas", "password": PASSWORD},
        )
        if login.status_code != 200:
            raise RuntimeError(f"diverse benchmark login failed: {login.status_code}")
        token = client.cookies.get("wiseway_session")
        for name, text, sort, selected, total, ids in cases:
            samples = []
            for attempt in range(repeats):
                started = time.perf_counter()
                response = client.post(
                    "/api/v1/search",
                    json=diverse_request(
                        text, sort=sort, selected=selected, state=f"{name.replace('_', '-')}-{attempt}"
                    ),
                    cookies={"wiseway_session": token},
                )
                samples.append((time.perf_counter() - started) * 1000)
                payload = (
                    response.json()
                    if response.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                actual = [item["item_id"] for item in payload.get("items", [])]
                if (
                    response.status_code != 200
                    or payload.get("total") != total
                    or (ids is not None and actual != ids[: min(100, total)])
                ):
                    failures.append(
                        {"case": name, "status": response.status_code, "total": payload.get("total")}
                    )
            timings[name] = {"p50_ms": percentile(samples, 0.5), "p95_ms": percentile(samples, 0.95)}
        facet_body = diverse_request(
            "", sort={"field": "PATH", "direction": "ASC"}, selected=[section], state="facet"
        )
        facet_body.pop("sort")
        facet = client.post(
            "/api/v1/search/facet",
            json=facet_body,
            cookies={"wiseway_session": token},
        )
        options = facet.json().get("facet", {}).get("options", []) if facet.status_code == 200 else []
        expected_facets = expected_company_facets(records)
        actual_facets = {option.get("display_value"): option.get("count") for option in options}
        if actual_facets != expected_facets:
            failures.append({"case": "company_facet", "status": facet.status_code})

        def burst(number: int):
            rare_case = number % 2 == 0
            body = diverse_request(
                f"{rare:09d}" if rare_case else "Family",
                sort={"field": "RELEVANCE", "direction": "DESC"},
                state=f"burst-{number}",
            )
            started = time.perf_counter()
            response = client.post("/api/v1/search", json=body, cookies={"wiseway_session": token})
            elapsed = (time.perf_counter() - started) * 1000
            return (
                ("typical" if rare_case else "broad"),
                elapsed,
                response.status_code,
                response.json().get("total"),
            )

        samples = {"typical": [], "broad": []}
        with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
            for name, elapsed, status, total in pool.map(burst, range(requests)):
                samples[name].append(elapsed)
                expected = 1 if name == "typical" else records
                if status != 200 or total != expected:
                    failures.append({"case": f"burst_{name}", "status": status, "total": total})
    burst_p95 = {name: percentile(values, 0.95) for name, values in samples.items()}
    sla = {
        "typical_p95_ms": burst_p95["typical"],
        "broad_p95_ms": burst_p95["broad"],
        "typical_limit_ms": 2000,
        "broad_limit_ms": 5000,
    }
    return {
        "records": records,
        "correctness_passed": not failures,
        "failures": failures[:20],
        "timing_ms": timings,
        "total_only_sort_checks": ["PATH DESC", "MODIFIED_AT DESC", "SIZE DESC"],
        "burst": {"clients": clients, "requests": requests, "p95_ms": burst_p95},
        "sla": {**sla, "passed": burst_p95["typical"] <= 2000 and burst_p95["broad"] <= 5000},
        "passed": not failures and burst_p95["typical"] <= 2000 and burst_p95["broad"] <= 5000,
    }


@dataclass(frozen=True)
class Corpus:
    name: str
    row: Callable[[int], dict]
    schema: dict | None


CORPORA = {
    "baseline": Corpus("baseline", baseline_row, None),
    "diverse": Corpus("diverse", diverse_row, diverse_schema()),
}


def get_corpus(name: str) -> Corpus:
    try:
        return CORPORA[name]
    except KeyError as error:
        raise ValueError("corpus must be baseline or diverse") from error
