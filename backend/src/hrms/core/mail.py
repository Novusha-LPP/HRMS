"""Transactional reset outbox. SES delivery is at least once; reset links remain one use."""

import asyncio
import json
import logging

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from hrms.core import database
from hrms.core.config import settings
from hrms.core.datetime_utils import now_utc
from hrms.core.field_crypto import cipher

logger = logging.getLogger(__name__)
AAD = "platform-reset-mail"


def reset_payload(email: str, token: str) -> str:
    assert settings.platform_reset_base_url is not None
    url = settings.platform_reset_base_url.rstrip("/") + "/platform/reset-password?token=" + token
    return cipher().encrypt(json.dumps({"to": email, "url": url}), AAD)


def _send(payload: dict) -> None:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "ses",
        region_name=settings.mail_region,
        config=Config(
            connect_timeout=3,
            read_timeout=10,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )
    client.send_email(
        Source=settings.mail_from,
        Destination={"ToAddresses": [payload["to"]]},
        Message={
            "Subject": {"Data": "Reset your HRMS password"},
            "Body": {
                "Text": {"Data": "Use this one-time link before it expires: " + payload["url"]}
            },
        },
    )


async def deliver_pending() -> bool:
    if settings.mail_backend != "ses":
        return True
    failed = False
    # Bounded batch; SKIP LOCKED permits multiple workers without duplicate concurrent sends.
    async with database.PlatformSessionLocal() as session, session.begin():
        await session.execute(
            text("""UPDATE platform_password_reset_tokens
            SET delivery_payload=NULL WHERE delivery_payload IS NOT NULL
            AND (used_at IS NOT NULL OR expires_at <= now())""")
        )
    for _ in range(50):
        async with database.PlatformSessionLocal() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text("""SELECT id, delivery_payload, delivery_attempts
                FROM platform_password_reset_tokens WHERE delivery_payload IS NOT NULL
                AND used_at IS NULL AND expires_at > now()
                AND (delivery_next_at IS NULL OR delivery_next_at <= now())
                ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED""")
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                break
            try:
                payload = json.loads(cipher().decrypt(row["delivery_payload"], AAD))
                await run_in_threadpool(_send, payload)
            except Exception as exc:
                failed = True
                # Provider errors may contain recipient/token details: log the class only.
                logger.error("Reset mail delivery failed (%s)", type(exc).__name__)
                await session.execute(
                    text("""UPDATE platform_password_reset_tokens
                    SET delivery_attempts=delivery_attempts+1,
                    delivery_next_at=now()+make_interval(secs=>:delay) WHERE id=:id"""),
                    {
                        "id": row["id"],
                        "delay": min(300, 30 * 2 ** min(row["delivery_attempts"], 4)),
                    },
                )
            else:
                await session.execute(
                    text("""UPDATE platform_password_reset_tokens
                    SET delivery_payload=NULL, delivered_at=now(),
                    delivery_attempts=delivery_attempts+1 WHERE id=:id"""),
                    {"id": row["id"]},
                )
    async with database.PlatformSessionLocal() as session, session.begin():
        await session.execute(
            text("""INSERT INTO job_runs
            (id, job, status, started_at, finished_at, tenants_ok, tenants_failed)
            VALUES (gen_random_uuid(),'mail-delivery',:status,:now,:now,0,:failed)"""),
            {
                "status": "FAILED" if failed else "SUCCEEDED",
                "now": now_utc(),
                "failed": int(failed),
            },
        )
    return not failed


async def schedule_delivery() -> None:
    while True:
        try:
            await deliver_pending()
        except Exception as exc:
            logger.error("Reset mail worker failed (%s)", type(exc).__name__)
        await asyncio.sleep(60)
