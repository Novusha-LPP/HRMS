"""Deployment boundary tests. No AWS calls or employee database connections."""

import base64
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


validate = module("deployment_validate", "validate.py")
dispatch = module("deployment_dispatch", "send-command.py")


def config():
    host = "example.ap-south-1.rds.amazonaws.com:5432/hrms_testing?ssl=verify-full"
    app_password, platform_password = "a" * 32, "b" * 32
    app_url = f"postgresql+asyncpg://hrms_app:{app_password}@{host}"
    runtime = {
        "HRMS_DATABASE_URL": app_url,
        "HRMS_APP_DATABASE_URL": app_url,
        "HRMS_PLATFORM_DATABASE_URL": f"postgresql+asyncpg://hrms_platform:{platform_password}@{host}",
        "HRMS_SECRET_KEY": "c" * 64,
        "HRMS_METRICS_TOKEN": "d" * 64,
        "HRMS_FIELD_ENCRYPTION_KEYS": "k1:" + base64.urlsafe_b64encode(b"e" * 32).decode(),
        "HRMS_PAYROLL_ENCRYPTION_KEYS": "p1:" + base64.urlsafe_b64encode(b"f" * 32).decode(),
        "HRMS_PAYROLL_PEPPER": "g" * 48,
        "HRMS_CORS_ORIGINS": "https://testing.example.com",
    }
    migrate = {
        "HRMS_DATABASE_URL": f"postgresql+asyncpg://Hrms:{'f' * 32}@{host}",
        "HRMS_APP_ROLE_PASSWORD": app_password,
        "HRMS_PLATFORM_ROLE_PASSWORD": platform_password,
    }
    return runtime, migrate, {"HRMS_WEB_API_URL": "https://api.example.com"}


class ConfigurationTests(unittest.TestCase):
    def test_valid_configuration(self):
        validate.validate_settings(*config())

    def test_s3_document_storage_configuration(self):
        runtime, migrate, deploy = config()
        runtime["HRMS_DOCUMENT_STORAGE"] = "s3"
        runtime["HRMS_DOCUMENT_S3_BUCKET"] = "hrms-testing-documents"
        validate.validate_settings(runtime, migrate, deploy)

        del runtime["HRMS_DOCUMENT_S3_BUCKET"]
        with self.assertRaises(ValueError):
            validate.validate_settings(runtime, migrate, deploy)

    def test_tls_and_admin_database_are_rejected(self):
        for old, new in (("verify-full", "require"), ("/hrms_testing?", "/postgres?")):
            with self.subTest(new=new):
                runtime, migrate, deploy = config()
                for key in ("HRMS_DATABASE_URL", "HRMS_APP_DATABASE_URL"):
                    runtime[key] = runtime[key].replace(old, new)
                with self.assertRaises(ValueError):
                    validate.validate_settings(runtime, migrate, deploy)

    def test_runtime_cannot_receive_owner_passwords(self):
        runtime, migrate, deploy = config()
        runtime["HRMS_APP_ROLE_PASSWORD"] = "a" * 32
        with self.assertRaises(ValueError):
            validate.validate_settings(runtime, migrate, deploy)

    def test_role_password_mismatch_is_rejected(self):
        runtime, migrate, deploy = config()
        migrate["HRMS_APP_ROLE_PASSWORD"] = "z" * 32
        with self.assertRaises(ValueError):
            validate.validate_settings(runtime, migrate, deploy)

    def test_different_databases_are_rejected(self):
        runtime, migrate, deploy = config()
        migrate["HRMS_DATABASE_URL"] = migrate["HRMS_DATABASE_URL"].replace(
            "/hrms_testing?", "/other?"
        )
        with self.assertRaises(ValueError):
            validate.validate_settings(runtime, migrate, deploy)

    def test_runtime_cannot_use_the_owner(self):
        runtime, migrate, deploy = config()
        runtime["HRMS_DATABASE_URL"] = runtime["HRMS_APP_DATABASE_URL"] = migrate[
            "HRMS_DATABASE_URL"
        ]
        with self.assertRaises(ValueError):
            validate.validate_settings(runtime, migrate, deploy)

    def test_env_values_are_literal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            path.write_text("TOKEN=a$literal#value\n")
            self.assertEqual(validate.load_env(path), {"TOKEN": "a$literal#value"})
            path.write_text("TOKEN=first\nTOKEN=second\n")
            with self.assertRaises(ValueError):
                validate.load_env(path)

    def test_images_must_be_digest_pinned(self):
        prefix = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/"
        data = {
            "commit": "a" * 40,
            "api": prefix + "api@sha256:" + "b" * 64,
            "web": prefix + "web@sha256:" + "c" * 64,
        }
        self.assertIn("HRMS_API_IMAGE=", validate.validate_images(data))
        data["api"] = prefix + "api:latest"
        with self.assertRaises(ValueError):
            validate.validate_images(data)


class DispatchTests(unittest.TestCase):
    def env(self):
        return {
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "BUNDLE_SHA256": "b" * 64,
            "DEPLOY_ARTIFACT_BUCKET": "testing-artifacts",
            "BUNDLE_KEY": "testing/releases/bundle.tar.gz",
            "EC2_INSTANCE_ID": "i-1234567890abcdef0",
        }

    def test_remote_script_checks_integrity_before_extracting(self):
        script = dispatch.remote_command(self.env())
        self.assertLess(script.index("sha256sum --check"), script.index("tar -xzf"))
        self.assertLess(script.index("tar -xzf"), script.index("bash ./deploy.sh"))
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)

    def test_invalid_run_identity_is_rejected(self):
        env = self.env()
        env["GITHUB_SHA"] = "$(touch /tmp/unsafe)"
        with self.assertRaises(ValueError):
            dispatch.remote_command(env)

    def test_waits_through_eventual_consistency_and_progress(self):
        responses = [
            subprocess.CompletedProcess([], 0, '{"Command":{"CommandId":"cmd-1"}}', ""),
            subprocess.CompletedProcess([], 1, "", "InvocationDoesNotExist"),
            subprocess.CompletedProcess([], 0, '{"Status":"InProgress"}', ""),
            subprocess.CompletedProcess([], 0, '{"Status":"Success"}', ""),
        ]
        with (
            patch.dict(dispatch.os.environ, self.env(), clear=True),
            patch.object(dispatch, "aws", side_effect=responses),
            patch.object(dispatch.time, "sleep") as sleep,
        ):
            dispatch.main()
            self.assertEqual(sleep.call_count, 2)

    def test_failed_migrations_fail_the_workflow(self):
        responses = [
            subprocess.CompletedProcess([], 0, '{"Command":{"CommandId":"cmd-1"}}', ""),
            subprocess.CompletedProcess(
                [], 0, '{"Status":"Failed","StandardErrorContent":"secret"}', ""
            ),
        ]
        with (
            patch.dict(dispatch.os.environ, self.env(), clear=True),
            patch.object(dispatch, "aws", side_effect=responses),
        ):
            with self.assertRaisesRegex(RuntimeError, "Deployment Failed") as error:
                dispatch.main()
            self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
