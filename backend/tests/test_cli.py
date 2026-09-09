import os
import subprocess
import sys


def test_clean_init_status_tick_and_safe_repeat(tmp_path):
    env = {
        **os.environ,
        "WISEWAY_DATA_DIR": str(tmp_path / "state"),
        "WISEWAY_SANDBOX_DIR": str(tmp_path / "sandbox"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "wiseway", "init-demo", "--password-stdin"],
        env=env,
        input="synthetic-cli-password\n",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "synthetic-cli-password" not in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "wiseway", "status"], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "COMPLETE" in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "wiseway", "tick"], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
