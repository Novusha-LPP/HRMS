"""
Which branding applies to a company: its own value for each field, else the group default,
else the built-in default. Every resolved value carries where it came from, so the setup
screen can say "Inherited from the group".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlmodel import col, select

from hrms.core import document_store
from hrms.modules.branding.models import BrandAsset, BrandProfile
from hrms.modules.branding.schemas import CompanyDetails
from hrms.modules.kernel.models import Tenant
from hrms.modules.org.models import LegalEntity

Source = Literal["COMPANY", "GROUP", "DEFAULT"]

BRAND_FIELDS = (
    "logo_asset_id",
    "primary_color",
    "accent_color",
    "footer_text",
    "contact_email",
    "contact_phone",
    "website",
)
# Teal 700 and teal 900: the app's own brand, readable on white.
DEFAULTS: dict[str, str] = {"primary_color": "#0F766E", "accent_color": "#134E4A"}
WHITE = "#FFFFFF"
INK = "#111827"
MIN_CONTRAST = 4.5  # WCAG AA for normal text


@dataclass(frozen=True)
class ResolvedValue:
    value: object
    source: Source


async def profiles_for(
    session, tenant_id: UUID, legal_entity_id: UUID | None
) -> tuple[BrandProfile | None, BrandProfile | None]:
    """The group default row and (when legal_entity_id is set) the company's own row."""
    ids = [legal_entity_id] if legal_entity_id else []
    rows = await session.execute(
        select(BrandProfile)
        .where(BrandProfile.tenant_id == tenant_id)
        .where(
            col(BrandProfile.legal_entity_id).is_(None) | col(BrandProfile.legal_entity_id).in_(ids)
        )
    )
    group = company = None
    for row in rows.scalars():
        if row.legal_entity_id is None:
            group = row
        else:
            company = row
    return group, company


def merge(group: BrandProfile | None, company: BrandProfile | None) -> dict[str, ResolvedValue]:
    resolved: dict[str, ResolvedValue] = {}
    for name in BRAND_FIELDS:
        if company is not None and getattr(company, name) is not None:
            resolved[name] = ResolvedValue(getattr(company, name), "COMPANY")
        elif group is not None and getattr(group, name) is not None:
            resolved[name] = ResolvedValue(getattr(group, name), "GROUP")
        else:
            resolved[name] = ResolvedValue(DEFAULTS.get(name), "DEFAULT")
    return resolved


@dataclass(frozen=True)
class BrandContext:
    """Everything a document needs to look like it comes from this company."""

    legal_entity_id: UUID | None
    company: CompanyDetails
    fields: dict[str, ResolvedValue]
    logo: BrandAsset | None

    def value(self, name: str) -> str | None:
        v = self.fields[name].value
        return None if v is None else str(v)


async def company_details(session, tenant_id: UUID, legal_entity_id: UUID | None):
    """The company's printed details; for the group default, just the tenant's name."""
    if legal_entity_id is None:
        tenant = await session.get(Tenant, tenant_id)
        return CompanyDetails(name=tenant.display_name if tenant else "Your company")
    entity = (
        await session.execute(
            select(LegalEntity)
            .where(LegalEntity.tenant_id == tenant_id)
            .where(LegalEntity.id == legal_entity_id)
        )
    ).scalar_one()
    return CompanyDetails.model_validate(entity, from_attributes=True)


async def context(session, tenant_id: UUID, legal_entity_id: UUID | None) -> BrandContext:
    fields = merge(*await profiles_for(session, tenant_id, legal_entity_id))
    logo = None
    if isinstance(logo_id := fields["logo_asset_id"].value, UUID):
        logo = (
            await session.execute(
                select(BrandAsset)
                .where(BrandAsset.tenant_id == tenant_id)
                .where(BrandAsset.id == logo_id)
            )
        ).scalar_one_or_none()
    return BrandContext(
        legal_entity_id=legal_entity_id,
        company=await company_details(session, tenant_id, legal_entity_id),
        fields=fields,
        logo=logo,
    )


def load_png(asset: BrandAsset) -> bytes:
    """The stored image (decrypted). Blocking: call through run_in_threadpool."""
    return document_store.load(asset.storage_ref)


# ─── Colour contrast ─────────────────────────────────────────────────────────


def _luminance(hex_color: str) -> float:
    def channel(i: int) -> float:
        c = int(hex_color[i : i + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on_white(hex_color: str) -> str:
    """The colour itself if text in it is readable on white, else the nearest darker shade."""
    color = hex_color.upper()
    while contrast(color, WHITE) < MIN_CONTRAST:
        color = "#" + "".join(f"{int(int(color[i : i + 2], 16) * 0.9):02X}" for i in (1, 3, 5))
    return color


def text_on(hex_color: str) -> str:
    """White or near-black, whichever reads better on a background of this colour."""
    return WHITE if contrast(hex_color, WHITE) >= contrast(hex_color, INK) else INK


def mix(hex_color: str, other: str, weight: float) -> str:
    """`weight` of `other` blended into the colour: mix(c, WHITE, 0.9) is a pale tint of c."""

    def channel(i: int) -> int:
        mine, theirs = int(hex_color[i : i + 2], 16), int(other[i : i + 2], 16)
        return round(mine * (1 - weight) + theirs * weight)

    return "#" + "".join(f"{channel(i):02X}" for i in (1, 3, 5))
