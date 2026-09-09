import re
from wiseway.contract import Contract


def test_path_parameters_exactly_match_url_templates():
    contract = Contract()
    for path, path_item in contract.spec["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put"}:
                continue
            parameters = [
                contract.resolve(p) for p in path_item.get("parameters", []) + operation.get("parameters", [])
            ]
            declared = {p["name"] for p in parameters if p["in"] == "path"}
            assert declared == set(re.findall(r"\{([^}]+)\}", path)), (method, path, declared)


def test_official_openapi_validation():
    from openapi_spec_validator import validate

    validate(Contract().spec)
