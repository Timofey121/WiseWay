"""Root discovery must not deserialize every file in a published archive."""

from wiseway.app import dispatch
from wiseway.services import Context
from wiseway.storage import UnitOfWork


def test_list_roots_reads_only_public_root_metadata(configured, monkeypatch):
    ctx = Context(configured)
    try:
        with ctx.store.transaction(write=False) as tx:
            expected = [index["root"] for index in tx.list("index")]
        original = UnitOfWork.list

        def bounded_list(self, kind):
            if kind == "index":
                raise AssertionError("Root discovery decoded all archive file records")
            return original(self, kind)

        monkeypatch.setattr(UnitOfWork, "list", bounded_list)
        with ctx.store.transaction(write=False) as tx:
            status, response = dispatch(ctx, tx, "listRoots", {}, {}, {}, "root-scale")
        assert status == 200
        assert response == {"items": expected}
    finally:
        ctx.close()
