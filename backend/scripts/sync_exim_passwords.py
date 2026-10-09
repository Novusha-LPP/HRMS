"""Sync exported bcrypt passwords by EXIM source ID; dry run unless --apply."""

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core.config import settings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads(args.source.read_text())
    source = {}
    for record in records:
        raw = record.get("_id")
        sid = raw.get("$oid") if isinstance(raw, dict) else raw
        if not sid or str(sid) in source:
            raise ValueError("Missing or duplicate source ID")
        source[str(sid)] = record
    report = dict(applied=args.apply, source_records=len(source), matched=0,
                  changed=0, unchanged=0, invalid_password_source_ids=[], changed_source_ids=[])
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            tx = await conn.begin()
            tid = (await conn.execute(text("SELECT id FROM tenants WHERE slug=:slug"),
                                      {"slug": args.tenant})).scalar_one()
            rows = (await conn.execute(text("""
                SELECT id, erp_user_id, password_hash FROM user_accounts
                WHERE tenant_id=:tid AND erp_system='EXIM' FOR UPDATE
            """), {"tid": tid})).mappings().all()
            seen = set()
            for row in rows:
                sid = row["erp_user_id"]
                if sid not in source:
                    continue
                if sid in seen:
                    raise ValueError("Ambiguous database source ID")
                seen.add(sid)
                report["matched"] += 1
                hashed = source[sid].get("password")
                valid = isinstance(hashed, str) and re.fullmatch(
                    r"\$2[aby]\$(0[4-9]|[12][0-9]|3[01])\$[./A-Za-z0-9]{53}", hashed)
                if valid:
                    try:
                        bcrypt.checkpw(b"hash-format-check", hashed.encode("ascii"))
                    except ValueError:
                        valid = False
                if not valid:
                    report["invalid_password_source_ids"].append(sid)
                    continue
                if hashed == row["password_hash"]:
                    report["unchanged"] += 1
                    continue
                report["changed"] += 1
                report["changed_source_ids"].append(sid)
                if args.apply:
                    await conn.execute(text("""
                        UPDATE user_accounts SET password_hash=:hashed,
                            must_change_password=false, password_changed_at=:now,
                            token_epoch=token_epoch+1, version=version+1
                        WHERE tenant_id=:tid AND id=:uid
                    """), dict(hashed=hashed, now=datetime.now(UTC), tid=tid, uid=row["id"]))
            report["unmatched_source_records"] = len(source) - len(seen)
            if args.apply:
                await tx.commit()
            else:
                await tx.rollback()
    finally:
        await engine.dispose()
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    args.report.chmod(0o600)
    print(json.dumps({k: v for k, v in report.items() if not k.endswith("source_ids")}))


if __name__ == "__main__":
    asyncio.run(main())
