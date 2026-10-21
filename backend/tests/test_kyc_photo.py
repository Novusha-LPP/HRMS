"""The profile photo: a small cached thumbnail of the person's PHOTO document, for avatars."""

import io

import pytest
from PIL import Image

from hrms.modules.kyc.photo import THUMB_PIXELS, make_thumbnail
from tests.helpers import ok
from tests.test_kyc_privacy import _setup

pytestmark = pytest.mark.database


def picture(size=(800, 600), kind="PNG", mode="RGB", color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, kind)
    return out.getvalue()


async def upload(client, headers, data, kind="PHOTO", name="me.png", mime="image/png"):
    return await ok(
        client,
        "POST",
        "/v1/kyc/me/documents",
        headers=headers,
        files={"file": (name, data, mime)},
        data={"document_type": kind, "document_title": kind.title()},
    )


def test_thumbnail_is_a_small_square_jpeg():
    for data in (
        picture((3000, 2000)),
        picture((100, 400)),
        picture((64, 64), mode="RGBA", color=(0, 0, 0, 0)),
        picture((900, 600), kind="JPEG"),
    ):
        thumb = make_thumbnail(data)
        assert thumb is not None and len(thumb) < 25_000
        image = Image.open(io.BytesIO(thumb))
        assert image.format == "JPEG" and image.size == (THUMB_PIXELS, THUMB_PIXELS)


def test_thumbnail_refuses_what_it_cannot_decode_safely():
    assert make_thumbnail(b"not an image at all") is None
    assert make_thumbnail(b"") is None
    assert make_thumbnail(picture((10, 10))[:40]) is None  # truncated


async def test_the_owner_and_people_with_scope_see_the_photo_others_do_not(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    assert (await client.get(url, headers=tokens["self"])).status_code == 204  # none yet

    big = picture((3000, 2000))
    await upload(client, tokens["self"], big)
    for who in ("self", "manager", "accountant"):
        r = await client.get(url, headers=tokens[who])
        assert r.status_code == 200, who
        assert r.headers["content-type"] == "image/jpeg"
        assert len(r.content) < len(big) / 20 and len(r.content) < 25_000
        assert r.headers["cache-control"] == "private, max-age=300"
        assert r.headers["x-content-type-options"] == "nosniff"
    assert (await client.get(url)).status_code == 200  # the company admin


async def test_conditional_requests_return_304_while_the_photo_is_unchanged(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    await upload(client, tokens["self"], picture())
    first = await client.get(url, headers=tokens["self"])
    tag = {"If-None-Match": first.headers["etag"]}
    again = await client.get(url, headers={**tokens["self"], **tag})
    assert again.status_code == 304 and again.content == b""
    await upload(client, tokens["self"], picture(color=(10, 10, 200)))
    changed = await client.get(url, headers={**tokens["self"], **tag})
    assert changed.status_code == 200 and changed.headers["etag"] != first.headers["etag"]


async def test_only_the_photo_type_is_served_never_the_identity_scans(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    # Every other document type, even a valid image, is not a profile photo.
    await upload(client, tokens["self"], picture(), kind="AADHAAR_FRONT")
    await upload(client, tokens["self"], picture(), kind="PAN_CARD")
    assert (await client.get(url, headers=tokens["manager"])).status_code == 204
    assert (await client.get(url)).status_code == 204


async def test_a_rejected_photo_is_not_shown_and_an_unreadable_one_is_not_a_photo(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    doc = await upload(client, tokens["self"], picture())
    assert (await client.get(url, headers=tokens["manager"])).status_code == 200
    await ok(
        client,
        "PATCH",
        f"/v1/kyc/documents/{doc['id']}/verify",
        json={"status": "REJECTED", "rejection_reason": "Face not visible"},
    )
    assert (await client.get(url, headers=tokens["manager"])).status_code == 204

    # A PDF uploaded as the photo cannot be thumbnailed: no photo (204), not an error page.
    await upload(client, tokens["self"], b"%PDF-1.4 a scan", name="x.pdf", mime="application/pdf")
    assert (await client.get(url, headers=tokens["manager"])).status_code == 204


async def test_deleting_the_photo_removes_it_and_its_thumbnail(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    doc = await upload(client, tokens["self"], picture())
    assert (await client.get(url, headers=tokens["self"])).status_code == 200  # makes the thumbnail
    deleted = await client.delete(f"/v1/kyc/documents/{doc['id']}", headers=tokens["self"])
    assert deleted.status_code == 204
    assert (await client.get(url, headers=tokens["self"])).status_code == 204


async def put_photo(client, headers, subject_id, data, name="new.png", mime="image/png"):
    return await client.put(
        f"/v1/kyc/employees/{subject_id}/photo",
        headers=headers,
        files={"file": (name, data, mime)},
    )


async def test_you_can_replace_and_remove_your_own_photo(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    assert (await put_photo(client, tokens["self"], subject["id"], picture())).status_code == 204
    first = await client.get(url, headers=tokens["self"])
    assert first.status_code == 200

    # A new photo replaces the old one: one photo document, a different picture tag.
    assert (
        await put_photo(client, tokens["self"], subject["id"], picture(color=(10, 10, 200)))
    ).status_code == 204
    second = await client.get(url, headers=tokens["self"])
    assert second.status_code == 200 and second.headers["etag"] != first.headers["etag"]
    docs = await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"])
    assert [d["document_type"] for d in docs["documents"]].count("PHOTO") == 1

    assert (await client.delete(url, headers=tokens["self"])).status_code == 204
    assert (await client.get(url, headers=tokens["self"])).status_code == 204  # initials again
    assert (
        await client.delete(url, headers=tokens["self"])
    ).status_code == 204  # nothing left: fine


async def test_only_you_or_hr_can_change_a_photo(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    # A manager can see the photo but not change it; an accountant neither.
    for who in ("manager", "accountant"):
        assert (await put_photo(client, tokens[who], subject["id"], picture())).status_code == 403
        assert (await client.delete(url, headers=tokens[who])).status_code == 403
    # The company administrator (HR) can.
    assert (await put_photo(client, {}, subject["id"], picture())).status_code == 204
    assert (await client.get(url, headers=tokens["manager"])).status_code == 200
    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url, headers=tokens["manager"])).status_code == 204


async def test_a_profile_photo_must_be_a_readable_png_or_jpeg(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    pdf = await put_photo(
        client, tokens["self"], subject["id"], b"%PDF-1.4 x", "x.pdf", "application/pdf"
    )
    assert pdf.status_code == 415
    assert (await put_photo(client, tokens["self"], subject["id"], b"just text")).status_code == 415
    broken = await put_photo(client, tokens["self"], subject["id"], picture()[:60])
    assert broken.status_code == 422
    assert (await client.get(url, headers=tokens["self"])).status_code == 204  # nothing was stored


async def test_changing_a_photo_does_not_reset_kyc_verification(api):
    client, _ = api
    subject, tokens = await _setup(client)
    before = await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"])
    await put_photo(client, tokens["self"], subject["id"], picture())
    after = await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"])
    assert after["status"] == before["status"]


async def test_the_large_view_is_the_whole_picture_not_a_crop(api):
    client, _ = api
    subject, tokens = await _setup(client)
    url = f"/v1/kyc/employees/{subject['id']}/photo"
    await put_photo(client, tokens["self"], subject["id"], picture((2000, 1000)))
    small = await client.get(url, headers=tokens["self"])
    large = await client.get(url + "?size=large", headers=tokens["manager"])
    assert large.status_code == 200 and large.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(small.content)).size == (192, 192)  # cropped square
    assert Image.open(io.BytesIO(large.content)).size == (640, 320)  # whole picture, scaled
    assert small.headers["etag"] != large.headers["etag"]
    # The large view follows the same access rules, and never enlarges a small picture.
    assert (await client.get(url + "?size=large")).status_code == 200
    await put_photo(client, tokens["self"], subject["id"], picture((100, 80)))
    tiny = await client.get(url + "?size=large", headers=tokens["self"])
    assert Image.open(io.BytesIO(tiny.content)).size == (100, 80)
    assert (await client.get(url + "?size=huge", headers=tokens["self"])).status_code == 422
    await client.delete(url, headers=tokens["self"])
    assert (await client.get(url + "?size=large", headers=tokens["self"])).status_code == 204
