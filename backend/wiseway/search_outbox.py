"""Commit local archive moves with business state; deliver them after commit."""

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .common import utc
from .indexer import _index_lock


def enqueue_move(tx, event_key, item_id, location, fingerprint):
    root = tx.get("root", location["root_id"], {})
    if root.get("_index_storage") != "opensearch":
        return
    record = {
        "op": "upsert",
        "item_id": item_id,
        "relative_path": location["relative_path"],
        "size_bytes": fingerprint["size"],
        "modified_at": utc(fingerprint["mtime_ns"] / 1e9),
    }
    tx.connection.execute(
        "INSERT INTO search_outbox(event_key,root_id,body) VALUES (?,?,?) ON CONFLICT(event_key) DO NOTHING",
        (event_key, location["root_id"], json.dumps(record, ensure_ascii=False)),
    )


def _manifest(directory, batch):
    directory.mkdir(mode=0o700, exist_ok=True)
    content = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in batch["records"]
    ).encode()
    path = directory / (hashlib.sha256(content).hexdigest() + ".ndjson")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != content:
            raise RuntimeError("Outbox manifest changed")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix="pending-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def drain(importer):
    """One bounded batch per root; a saved base makes crash replay deterministic."""
    ctx = importer.ctx
    with _index_lock(ctx, "archive-indexer.lock") as held:
        if not held:
            return 0
        with ctx.store.transaction(write=False) as tx:
            roots = [row[0] for row in tx.connection.execute("SELECT DISTINCT root_id FROM search_outbox")]
        delivered = 0
        for root_id in roots:
            with ctx.store.transaction() as tx:
                current = tx.get("index", root_id, {})
                if current.get("_storage") != "opensearch":
                    continue
                batch = tx.get("search_outbox_batch", root_id)
                if batch is None:
                    cursor = tx.connection.execute(
                        "SELECT seq,body FROM search_outbox WHERE root_id=? ORDER BY seq LIMIT 25000",
                        (root_id,),
                    )
                    rows, payload_bytes = [], 0
                    for record in cursor:
                        if rows and payload_bytes + len(record[1].encode()) > 4 * 1024 * 1024:
                            break
                        rows.append(record)
                        payload_bytes += len(record[1].encode())
                    if not rows:
                        continue
                    batch = {
                        "base": current["root"]["index_generation"],
                        "first": rows[0][0],
                        "last": rows[-1][0],
                        "records": [json.loads(row[1]) for row in rows],
                    }
                    tx.put("search_outbox_batch", root_id, batch)
            path = _manifest(ctx.settings.data_dir / "archive-events", batch)
            importer.run(root_id, path, mode="delta", base_generation=batch["base"], _lock_held=True)
            # A crash before this acknowledgement repeats the identical completed
            # import and never advances its external revisions a second time.
            with ctx.store.transaction() as tx:
                tx.connection.execute(
                    "DELETE FROM search_outbox WHERE root_id=? AND seq BETWEEN ? AND ?",
                    (root_id, batch["first"], batch["last"]),
                )
                tx.delete("search_outbox_batch", root_id)
            path.unlink(missing_ok=True)
            delivered += len(batch["records"])
        return delivered
