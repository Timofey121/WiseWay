"""Creation of the explicitly marked synthetic Wise Way demo sandbox."""

from __future__ import annotations

import json

from .auth import HASHER
from .common import Settings, utc
from .search import DEMO_SCHEMAS
from .storage import Store


def _root(root_id: str, label: str, prefix: str, base: str, **internal: object) -> dict:
    return {
        "root_id": root_id,
        "label": label,
        "display_prefix": prefix,
        "schema_set_version": "schema-demo-1",
        "index_generation": "generation-pending",
        "indexed_at": utc(0),
        "_base": base,
        **internal,
    }


def _stored_schema() -> dict:
    source = DEMO_SCHEMAS["schema-demo-1"]

    def convert(entries):
        return [[level_id, name, sorted(values), optional] for level_id, name, values, optional in entries]

    return {
        "schema_set_version": source["schema_set_version"],
        "root_levels": convert(source["root_levels"]),
        "tail_by_company": {key: convert(value) for key, value in source["tail_by_company"].items()},
    }


def initialize(settings: Settings, password: str) -> None:
    """Create a new sandbox or reject an unmarked non-empty directory."""
    sandbox = settings.sandbox_dir
    marker = sandbox / ".wiseway-sandbox.json"
    if sandbox.exists() and any(sandbox.iterdir()) and not marker.is_file():
        raise RuntimeError("Refusing to write into a non-empty unmarked sandbox")
    sandbox.mkdir(parents=True, exist_ok=True)
    if marker.exists():
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if payload.get("product") != "Wise Way" or payload.get("synthetic") is not True:
            raise RuntimeError("Sandbox marker does not describe Wise Way synthetic data")
        if payload.get("bootstrap_complete") is True:
            from .services import Context

            context = Context(settings)
            context.close()
            return
    else:
        marker.write_text(
            json.dumps(
                {"product": "Wise Way", "synthetic": True, "bootstrap_complete": False}, ensure_ascii=False
            ),
            encoding="utf-8",
        )

    store = Store(settings.database)
    with store.transaction(write=False) as tx:
        bootstrapped = tx.get("bootstrap", "seed-v1") is not None
    if bootstrapped:
        from .indexer import Indexer
        from .services import Context

        context = Context(settings)
        try:
            Indexer(context).scan()
        finally:
            context.close()
        marker.write_text(
            json.dumps(
                {"product": "Wise Way", "synthetic": True, "bootstrap_complete": True}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        return

    directories = (
        "Archive/Atlas/Orion_2031/Reports",
        "Archive/Atlas/Orion_2031/Data/Text",
        "Archive/Nova/Polaris_2030/North/Data",
        "Archive/Nova/Polaris_2030/South/Reports",
        "Reference/Archive/Nova/Polaris_2030/North/Data",
        "Incoming/Atlas",
        "Incoming/Nova",
        "ManualReview/Atlas",
        "ManualReview/Nova",
        "Quarantine/Atlas",
        "Quarantine/Nova",
    )
    for directory in directories:
        (sandbox / directory).mkdir(parents=True, exist_ok=True)
    for relative, content in {
        "Archive/Atlas/Orion_2031/Reports/Atlas-Main.pdf": b"atlas main",
        "Archive/Atlas/Orion_2031/Data/Text/report.v2.PDF": b"report",
        "Archive/Atlas/UnknownProject/lost.docx": b"unrecognised",
        "Archive/Nova/Polaris_2030/North/Data/Nova 10.xlsx": b"nova",
        "Archive/Nova/Polaris_2030/South/Reports/Readme": b"",
        "Reference/Archive/Nova/Polaris_2030/North/Data/reference.png": b"png",
        "Incoming/Atlas/invoice-1001.pdf": b"invoice",
        "Incoming/Nova/shipment-2.xlsx": b"shipment",
    }.items():
        path = sandbox / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)

    roots = (
        _root(
            "archive-root",
            "Archive",
            "DEMO:/SandboxRoot",
            "",
            _searchable=True,
            _schema=_stored_schema(),
            _scan_prefixes=["Archive"],
        ),
        _root(
            "reference-root",
            "Reference",
            "DEMO:/SandboxRoot/Reference",
            "Reference",
            _searchable=True,
            _schema=_stored_schema(),
            _scan_prefixes=["Archive/Nova"],
        ),
        _root(
            "incoming-atlas",
            "Incoming Atlas",
            "DEMO:/SandboxRoot/Incoming/Atlas",
            "Incoming/Atlas",
            _searchable=False,
            _incoming_company="company-atlas",
        ),
        _root(
            "incoming-nova",
            "Incoming Nova",
            "DEMO:/SandboxRoot/Incoming/Nova",
            "Incoming/Nova",
            _searchable=False,
            _incoming_company="company-nova",
        ),
        _root(
            "manual-root",
            "Manual review",
            "DEMO:/SandboxRoot/ManualReview",
            "ManualReview",
            _searchable=False,
        ),
        _root(
            "quarantine-root", "Quarantine", "DEMO:/SandboxRoot/Quarantine", "Quarantine", _searchable=False
        ),
    )
    companies = (
        {
            "company_id": "company-atlas",
            "name": "Atlas",
            "incoming_source_ids": ["incoming-atlas"],
            "_folder": "Atlas",
            "_targets": [
                {"root_id": "archive-root", "relative_directory": "Archive/Atlas/Orion_2031/Reports"}
            ],
        },
        {
            "company_id": "company-nova",
            "name": "Nova",
            "incoming_source_ids": ["incoming-nova"],
            "_folder": "Nova",
            "_targets": [
                {"root_id": "archive-root", "relative_directory": "Archive/Nova/Polaris_2030/North/Data"}
            ],
        },
    )
    users = (
        ("user-worker-atlas", "worker-atlas", "Atlas worker", "WORKER"),
        ("user-worker-nova", "worker-nova", "Nova worker", "WORKER"),
        ("user-admin", "admin", "Administrator", "ADMIN"),
    )
    with store.transaction() as tx:
        for root in roots:
            tx.put("root", root["root_id"], root)
        for company in companies:
            tx.put("company", company["company_id"], company)
        for user_id, login, display_name, role in users:
            tx.put(
                "user",
                user_id,
                {
                    "actor": {"user_id": user_id, "login": login, "display_name": display_name, "role": role},
                    "password_hash": HASHER.hash(password),
                    "blocked": False,
                },
            )
        tx.put("bootstrap", "seed-v1", {"complete": True})

    # Import only after roots and the marker exist; Context validates both.
    from .indexer import Indexer
    from .services import Context

    context = Context(settings)
    try:
        Indexer(context).scan()
    finally:
        context.close()
    marker.write_text(
        json.dumps(
            {"product": "Wise Way", "synthetic": True, "bootstrap_complete": True}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
