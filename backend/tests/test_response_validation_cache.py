from copy import deepcopy

import pytest

from test_search import ROOT, item, request
from wiseway.contract import Contract
from wiseway.search import search


def test_repeated_response_validation_still_rejects_changed_nested_data():
    contract = Contract()
    operation = next(
        operation
        for path in contract.spec["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and operation.get("operationId") == "searchFiles"
    )
    result = search(ROOT, [item("file-1", "Archive/Atlas/Orion_2031/Reports/report.pdf")], request("report"))
    for _ in range(3):
        contract.response(operation, 200, result)
    for mutate in (
        lambda row: row.update(size_bytes=-1),
        lambda row: row["location"].update(relative_path="../secret"),
        lambda row: row.update(unexpected="field"),
        lambda row: row.update(structure_status="UNRECOGNIZED"),
    ):
        changed = deepcopy(result)
        mutate(changed["items"][0])
        with pytest.raises(RuntimeError):
            contract.response(operation, 200, changed)
    result["returned_count"] = "invalid"
    with pytest.raises(RuntimeError):
        contract.response(operation, 200, result)
