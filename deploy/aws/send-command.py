"""Upload is handled by Actions; dispatch a checksummed bundle and await SSM completion."""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path


def aws(*args):
    return subprocess.run(
        ["aws", *args, "--output", "json"], text=True, capture_output=True, check=False
    )


def remote_command(env: dict) -> str:
    sha = env["GITHUB_SHA"]
    run_id, attempt = env["GITHUB_RUN_ID"], env["GITHUB_RUN_ATTEMPT"]
    checksum = env["BUNDLE_SHA256"]
    bucket, key = env["DEPLOY_ARTIFACT_BUCKET"], env["BUNDLE_KEY"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError("Invalid run identity")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Invalid bundle checksum")
    target = f"/opt/hrms/testing/releases/{sha}-{run_id}-{attempt}"
    quote = shlex.quote
    return "\n".join(
        [
            "set -eu",
            "umask 077",
            f"mkdir -p {quote(target)}",
            f"cd {quote(target)}",
            f"aws s3 cp {quote('s3://' + bucket + '/' + key)} bundle.tar.gz --only-show-errors",
            f"printf '%s  bundle.tar.gz\\n' {quote(checksum)} | sha256sum --check --status",
            "tar -xzf bundle.tar.gz",
            f"bash ./deploy.sh {quote(target)}",
        ]
    )


def main() -> None:
    command = remote_command(dict(os.environ))
    response = aws(
        "ssm",
        "send-command",
        "--document-name",
        "AWS-RunShellScript",
        "--instance-ids",
        os.environ["EC2_INSTANCE_ID"],
        "--timeout-seconds",
        "300",
        "--parameters",
        json.dumps({"commands": [command], "executionTimeout": ["1500"]}),
        "--comment",
        f"HRMS testing {os.environ['GITHUB_SHA'][:12]}",
    )
    if response.returncode:
        raise RuntimeError(
            "SSM dispatch failed; verify the testing deployment role and instance configuration"
        )
    command_id = json.loads(response.stdout)["Command"]["CommandId"]
    print(f"SSM command: {command_id}", flush=True)
    deadline = time.monotonic() + 1560
    while time.monotonic() < deadline:
        response = aws(
            "ssm",
            "get-command-invocation",
            "--command-id",
            command_id,
            "--instance-id",
            os.environ["EC2_INSTANCE_ID"],
        )
        if response.returncode:
            if "InvocationDoesNotExist" not in response.stderr:
                raise RuntimeError(f"Cannot read SSM result for {command_id}")
        else:
            result = json.loads(response.stdout)
            status = result["Status"]
            if status == "Success":
                summary = os.environ.get("GITHUB_STEP_SUMMARY")
                if summary:
                    with Path(summary).open("a") as stream:
                        stream.write(
                            f"Testing deployed `{os.environ['GITHUB_SHA']}` to EC2.\n\n"
                            f"SSM command: `{command_id}`\n"
                        )
                print("Testing deployment passed migrations, readiness and commit verification")
                return
            if status not in ("Pending", "InProgress", "Delayed", "Cancelling"):
                # Container logs may contain sensitive values; inspect SSM output in AWS.
                raise RuntimeError(f"Deployment {status}; inspect SSM command {command_id} in AWS")
        time.sleep(10)
    aws("ssm", "cancel-command", "--command-id", command_id)
    raise RuntimeError(
        f"SSM result timed out; cancellation requested for {command_id}. Verify instance state"
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
