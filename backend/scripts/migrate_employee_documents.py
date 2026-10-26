"""Import employee documents and profile photos from the old systems' S3 buckets.

Sources: the EXIM users export (photo, Aadhaar front/back, PAN, licence, address proof, resume,
NDA) and the Sharanga profiles (avatar, ID proof, education, experience, other documents).

Each file is downloaded from its old address, checked the way an upload is (PDF, PNG or JPEG by
its first bytes, within the upload limit), encrypted and stored through HRMS's own document
store, and recorded as an employee KYC document. Run it ON THE TARGET ENVIRONMENT so the files
are encrypted with that environment's keys and never sit unencrypted elsewhere.

Safe to repeat: every document has a deterministic id and an existing one is skipped before
anything is downloaded. Dry-run by default (no downloads, no writes). A file that is gone from
the old bucket, forbidden, or of an unsupported type is reported (employee code and field, for HR
to request again) and skipped; nothing else is affected.

Run from backend:
  .venv/bin/python scripts/migrate_employee_documents.py --tenant suraj-group --source exim
  .venv/bin/python scripts/migrate_employee_documents.py --tenant <rabs> --source sharanga
  .venv/bin/python scripts/migrate_employee_documents.py --tenant <rabs> --source exim-rabs \
      --decisions rabs_decisions.json
Add --apply to import; --limit N takes only the first N files (for a trial).

--repair: for documents already recorded whose stored file cannot be opened here (saved under a
key this environment does not have, or missing from the store), download the file again from its
old address and save it under the SAME reference with this environment's key. The database row
is kept (size and type refreshed), and the photo's cached thumbnails are dropped so they are
made again. A file that is gone from the old bucket is reported and left alone.
"""

import argparse
import asyncio
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from migrate_legacy_attendance import source_uuid, unwrap
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hrms import model_registry  # noqa: F401  (load tenant-aware model metadata for standalone CLI)
from hrms.core import document_store
from hrms.core.config import settings
from hrms.modules.kyc import photo
from hrms.modules.kyc.models import DocumentStatus, DocumentType, EmployeeKycDocument

ROOT = Path(__file__).resolve().parents[2]
SHARANGA_BASE = "https://sharanga-prod.s3.ap-south-1.amazonaws.com/"
EXIM_FIELDS = {
    "employee_photo": (DocumentType.PHOTO, "Profile photo"),
    "aadhar_photo_front": (DocumentType.AADHAAR_FRONT, "Aadhaar (front)"),
    "aadhar_photo_back": (DocumentType.AADHAAR_BACK, "Aadhaar (back)"),
    "pan_photo": (DocumentType.PAN_CARD, "PAN card"),
    "license_front": (DocumentType.OTHER, "Driving licence (front)"),
    "license_back": (DocumentType.OTHER, "Driving licence (back)"),
    "address_proof": (DocumentType.ADDRESS_PROOF, "Address proof"),
    "resume": (DocumentType.OTHER, "Resume"),
    "nda": (DocumentType.OTHER, "NDA"),
}
SHARANGA_FIELDS = {
    "avatar": (DocumentType.PHOTO, "Profile photo"),
    "id_proof": (DocumentType.OTHER, "ID proof"),
    "education_certificates": (DocumentType.EDUCATION_CERT, "Education certificate"),
    "experience_letters": (DocumentType.EXPERIENCE_LETTER, "Experience letter"),
    "other_documents": (DocumentType.OTHER, "Other document"),
}


def is_rabs(user):
    return (user.get("company") or "").strip().casefold() == "rabs industries india private limited"


def clean_filename(name):
    return re.sub(r"[^\w\.-]", "_", name)[:100]


def encoded(url):
    parts = urllib.parse.urlsplit(url.strip())
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def fetch(url):
    """(bytes | None, reason). Retries transient failures; a missing file is final."""
    last = "download failed"
    for attempt in range(3):
        try:
            request = urllib.request.Request(encoded(url))
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                data = response.read(settings.max_upload_bytes + 1)
            if len(data) > settings.max_upload_bytes:
                return None, "larger than the upload limit"
            return data, ""
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None, "no longer in the old bucket" if exc.code == 404 else "forbidden"
            last = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - reported, then the next file is tried
            last = type(exc).__name__
        time.sleep(1.5 * (attempt + 1))
    return None, last


def mime_of(data):
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def verified_at(value):
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=UTC)
    except ValueError:
        return None


def exim_files(users, rabs):
    for user in users:
        if is_rabs(user) != rabs:
            continue
        approved = str(user.get("kyc_approval")).lower() == "approved"
        for field, (kind, title) in EXIM_FIELDS.items():
            url = user.get(field)
            if isinstance(url, str) and url.startswith("http"):
                yield {
                    "owner": unwrap(user["_id"]),
                    "code": user.get("username") or "",
                    "field": field,
                    "index": 0,
                    "url": url,
                    "type": kind,
                    "title": title,
                    "source": "EXIM",
                    "verified": verified_at(user.get("kyc_date")) if approved else None,
                }


def sharanga_files(profiles):
    for profile in profiles:
        documents = (profile.get("user_info") or {}).get("user_documents") or {}
        for field, (kind, title) in SHARANGA_FIELDS.items():
            value = documents.get(field)
            for index, item in enumerate(value if isinstance(value, list) else [value]):
                if isinstance(item, str) and item.strip():
                    url = item if item.startswith("http") else SHARANGA_BASE + item.lstrip("/")
                    yield {
                        "owner": str(profile["emp_id"]),
                        "code": str(profile["emp_id"]),
                        "field": field,
                        "index": index,
                        "url": url,
                        "type": kind,
                        "title": title,
                        "source": "SHARANGA",
                        "verified": None,
                    }


async def migrate(session, args):
    tenant = (
        (
            await session.execute(
                text("SELECT id,slug FROM tenants WHERE slug = :ref OR id::text = :ref"),
                {"ref": args.tenant},
            )
        )
        .mappings()
        .one()
    )
    tid = tenant["id"]
    stats = {
        "tenant": tenant["slug"],
        "source": args.source,
        "planned": 0,
        "already_imported": 0,
        "imported": Counter(),
        "bytes": 0,
        "skipped": Counter(),
        "unreadable": Counter(),
        "repaired": Counter(),
        "follow_up": [],
    }
    accounts = (
        (
            await session.execute(
                text("""
        SELECT ua.erp_system, ua.erp_user_id, lower(ua.employee_code) AS code, ua.employment_id
        FROM user_accounts ua JOIN employments e
          ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
        WHERE ua.tenant_id = :tid
    """),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    by_exim = {r["erp_user_id"]: r["employment_id"] for r in accounts if r["erp_system"] == "EXIM"}
    by_code = {r["code"]: r["employment_id"] for r in accounts if r["code"]}
    decisions = {}
    if args.decisions:
        decisions = json.loads(args.decisions.read_text()).get("same", {})

    if args.source == "sharanga":
        files = list(
            sharanga_files(
                json.loads(
                    (args.data_dir / "Sharanga_Production.employee_profiles.json").read_text()
                )
            )
        )
        resolve = lambda f: by_code.get(f["owner"].lower())  # noqa: E731
    else:
        users = json.loads((args.data_dir / "exim.users.json").read_text())
        files = list(exim_files(users, rabs=args.source == "exim-rabs"))

        def resolve(f):
            found = by_exim.get(f["owner"])
            if found is None and f["owner"] in decisions:
                found = by_code.get(str(decisions[f["owner"]]).lower())
            return found

    if args.limit:
        files = files[: args.limit]
    stats["planned"] = len(files)
    known_rows = {
        r[0]: (r[1], r[2])
        for r in (
            await session.execute(
                text(
                    "SELECT id, storage_path, document_type FROM employee_kyc_documents "
                    "WHERE tenant_id = :tid"
                ),
                {"tid": tid},
            )
        ).all()
    }
    known = set(known_rows)
    has_photo = {
        r[0]
        for r in (
            await session.execute(
                text(
                    "SELECT employment_id FROM employee_kyc_documents "
                    "WHERE tenant_id = :tid AND document_type = 'PHOTO'"
                ),
                {"tid": tid},
            )
        ).all()
    }
    per_employee = {}
    for f in files:
        employment = resolve(f)
        if employment is None:
            stats["skipped"]["employee not in HRMS"] += 1
            continue
        path = urllib.parse.urlsplit(f["url"]).path
        key = f"{f['source']}:{f['owner']}:{f['field']}:{f['index']}:{path}"
        f["id"] = source_uuid(tid, "employee-document", key)
        if f["id"] in known:
            if args.repair:
                path_ref, doc_type = known_rows[f["id"]]
                try:
                    document_store.load(path_ref)
                except Exception as exc:  # noqa: BLE001 - any failure to open means "repair it"
                    stats["unreadable"][type(exc).__name__] += 1
                    f["repair"] = (path_ref, doc_type)
                    per_employee.setdefault(employment, []).append(f)
                    continue
            stats["already_imported"] += 1
            continue
        if f["type"] == DocumentType.PHOTO and employment in has_photo:
            stats["skipped"]["employee already has a profile photo"] += 1
            continue
        per_employee.setdefault(employment, []).append(f)
    stats["employees"] = len(per_employee)
    return tid, per_employee, stats


async def repair_one(session, tid, f, stats):
    path_ref, doc_type = f["repair"]
    data, reason = fetch(f["url"])
    if data is None:
        stats["skipped"][f"cannot repair: {reason}"] += 1
        stats["follow_up"].append({"code": f["code"], "field": f["field"], "reason": reason})
        return
    mime = mime_of(data)
    if mime is None:
        stats["skipped"]["cannot repair: unsupported file type"] += 1
        stats["follow_up"].append(
            {"code": f["code"], "field": f["field"], "reason": "unsupported file type"}
        )
        return
    document_store.save(path_ref[len(document_store.REF_PREFIX) :], data)
    await session.execute(
        text(
            "UPDATE employee_kyc_documents SET file_size = :n, mime_type = :m "
            "WHERE tenant_id = :tid AND id = :id"
        ),
        {"n": len(data), "m": mime, "tid": tid, "id": f["id"]},
    )
    if doc_type == "PHOTO":
        # Thumbnails kept under an old key cannot be opened either; they are made again on demand.
        for ref in (photo.thumbnail_ref(tid, f["id"]), photo.large_ref(tid, f["id"])):
            try:
                document_store.remove(ref)
            except Exception:  # noqa: BLE001 - a stale thumbnail is replaced when next unreadable
                stats["skipped"]["old thumbnail not removed"] += 1
    stats["repaired"][doc_type] += 1
    stats["bytes"] += len(data)


async def import_employee(session, tid, employment, files, stats):
    saved = []
    try:
        for f in files:
            if f.get("repair"):
                await repair_one(session, tid, f, stats)
                continue
            data, reason = fetch(f["url"])
            if data is None:
                stats["skipped"][reason] += 1
                stats["follow_up"].append(
                    {"code": f["code"], "field": f["field"], "reason": reason}
                )
                continue
            mime = mime_of(data)
            if mime is None:
                stats["skipped"]["unsupported file type (not PDF, PNG or JPEG)"] += 1
                stats["follow_up"].append(
                    {"code": f["code"], "field": f["field"], "reason": "unsupported file type"}
                )
                continue
            name = clean_filename(
                Path(urllib.parse.unquote(urllib.parse.urlsplit(f["url"]).path)).name
            )
            ref = document_store.save(f"kyc/{tid}/{f['id']}_{name}", data)
            saved.append(ref)
            session.add(
                EmployeeKycDocument(
                    tenant_id=tid,
                    id=f["id"],
                    employment_id=employment,
                    document_type=f["type"].value,
                    document_title=f["title"],
                    file_name=name,
                    file_size=len(data),
                    mime_type=mime,
                    storage_path=ref,
                    status=DocumentStatus.VERIFIED if f["verified"] else DocumentStatus.PENDING,
                    comments=f"Imported from the old system ({f['source']})",
                    uploaded_at=datetime.now(UTC),
                    verified_at=f["verified"],
                )
            )
            stats["imported"][f["type"].value] += 1
            stats["bytes"] += len(data)
        await session.flush()
    except Exception:
        for ref in saved:
            document_store.remove(ref)
        raise


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--source", choices=["exim", "exim-rabs", "sharanga"], required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument(
        "--decisions", type=Path, help="JSON with {'same': {exim id: employee code}}"
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--repair", action="store_true", help="re-save documents whose stored file cannot be opened"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("/tmp/hrms-documents.json"))
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                tid, per_employee, stats = await migrate(session, args)
            stats["mode"] = "APPLIED" if args.apply else "DRY_RUN"
            if args.apply:
                for employment, files in sorted(per_employee.items(), key=lambda kv: str(kv[0])):
                    try:
                        async with session.begin():
                            await import_employee(session, tid, employment, files, stats)
                    except Exception as exc:  # noqa: BLE001 - one person never stops the run
                        stats["skipped"][f"error: {type(exc).__name__}"] += len(files)
            else:
                stats["to_download"] = sum(len(v) for v in per_employee.values())
            args.report.write_text(json.dumps(stats, indent=2, default=str) + "\n")
            args.report.chmod(0o600)
            printable = {k: v for k, v in stats.items() if k != "follow_up"}
            printable["follow_up_count"] = len(stats["follow_up"])
            print(json.dumps(printable, indent=2, default=str))
            print(f"Report (with the follow-up list): {args.report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
