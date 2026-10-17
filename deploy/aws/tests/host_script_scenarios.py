"""Run inside a disposable container, with fake AWS/Docker CLIs and synthetic secrets.

Exercises the real root deployment script without mounting a Docker socket or using AWS.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from test_deployment import ROOT, config


def executable(path: Path, code: str) -> None:
    path.write_text(f"#!{sys.executable}\n" + code)
    path.chmod(0o755)


def main() -> None:
    directory = Path("/etc/hrms")
    directory.mkdir(parents=True, exist_ok=True)
    for kind, values in zip(("runtime", "migrate", "deploy"), config(), strict=True):
        path = directory / f"testing.{kind}.env"
        path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        path.chmod(0o600)
    (directory / "rds-global-bundle.pem").write_text("synthetic certificate fixture")
    stub_dir = Path("/tmp/hrms-stubs")
    stub_dir.mkdir()
    executable(stub_dir / "aws", "print('synthetic-ecr-token')\n")
    executable(stub_dir / "flock", "raise SystemExit(0)\n")
    executable(
        stub_dir / "docker",
        """import json,os,sys
from pathlib import Path
args=sys.argv[1:]
if args and args[0]=='login':
    sys.stdin.read()
with Path('/tmp/cli-calls.jsonl').open('a') as stream:
    stream.write(json.dumps(args)+'\\n')
scenario=os.environ['HRMS_TEST_SCENARIO']
previous=any('/previous/' in arg for arg in args)
if 'run' in args:
    preflight='python' in args
    if ((preflight and scenario=='preflight_failure')
            or (not preflight and scenario=='migration_failure')):
        raise SystemExit(41)
if 'up' in args and not previous and scenario=='readiness_failure':
    raise SystemExit(42)
if 'exec' in args and scenario=='commit_failure':
    raise SystemExit(43)
""",
    )
    root = Path("/opt/hrms/testing")
    prefix = "891377284307.dkr.ecr.ap-south-1.amazonaws.com/"
    for name in ("previous", "new"):
        release = root / "releases" / name
        release.mkdir(parents=True)
        for filename in ("deploy.sh", "validate.py", "compose.yml"):
            shutil.copy(ROOT / filename, release / filename)
        manifest = {
            "commit": "a" * 40,
            "api": prefix + "api@sha256:" + "b" * 64,
            "web": prefix + "web@sha256:" + "c" * 64,
        }
        (release / "images.json").write_text(json.dumps(manifest))
        (release / "images.env").write_text("fixture for rollback CLI")
    current = root / "current"
    for scenario in (
        "success",
        "preflight_failure",
        "migration_failure",
        "readiness_failure",
        "commit_failure",
        "code_only",
    ):
        current.unlink(missing_ok=True)
        current.symlink_to(root / "releases/previous")
        log = Path("/tmp/cli-calls.jsonl")
        log.unlink(missing_ok=True)
        env = {
            **os.environ,
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
            "HRMS_TEST_SCENARIO": scenario,
        }
        command = ["bash", str(ROOT / "deploy.sh"), str(root / "releases/new")]
        if scenario == "code_only":
            command.append("--code-only")
        result = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        ups = [args for args in calls if "up" in args]
        runs = [args for args in calls if "run" in args]
        if scenario in ("success", "code_only"):
            assert result.returncode == 0, (scenario, result.stderr)
            assert current.resolve() == root / "releases/new"
            assert len(ups) == 1
            assert len(runs) == (0 if scenario == "code_only" else 2)
        else:
            assert result.returncode != 0, scenario
            assert current.resolve() == root / "releases/previous"
            if scenario in ("preflight_failure", "migration_failure"):
                assert not ups, scenario
            else:
                assert len(ups) == 2, scenario
                assert any("/previous/" in arg for arg in ups[-1]), scenario
        print(f"Host deployment scenario passed: {scenario}")


if __name__ == "__main__":
    main()
