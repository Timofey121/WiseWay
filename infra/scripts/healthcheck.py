"""Container probe: local HTTP liveness plus database/filesystem/worker readiness."""

import json
import os
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"api", "worker"}:
        return 2
    try:
        if sys.argv[1] == "api":
            hostname = urlsplit(os.environ["WISEWAY_ORIGINS"].split(",")[0]).netloc
            request = Request("http://127.0.0.1:8000/api/v1/health", headers={"Host": hostname})
            with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
                if response.status != 200 or json.load(response) != {"status": "ok"}:
                    return 1
        result = subprocess.run(["wiseway", "doctor"], capture_output=True, timeout=5, check=False)
        return 0 if result.returncode == 0 and json.loads(result.stdout)["ready"] is True else 1
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
