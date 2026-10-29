"""Endpoint docs: Branding (how payslips and letters look)."""

_INHERIT = """
Every field is a value or `null`. On a company, `null` means "use the group's value"; on the
group, it means "use the built-in default" (teal colours, no logo). Send the `version` you
loaded: if someone saved in between, the change is refused with `409 STALE_VERSION`.
"""

DOCS: dict[str, tuple[str, str]] = {
    "list_brand_profiles": (
        "List saved branding",
        "The group's branding (`legal_entity_id: null`) and each company's own, for the "
        "companies you can see. A company with no row uses the group's branding as it is.",
    ),
    "put_group_brand_profile": (
        "Set the group's default branding",
        "Logo, colours, footer and contact details every company uses unless it sets its own. "
        "Needs a group-level administrator (`org.write` with `ALL` scope).\n" + _INHERIT,
    ),
    "put_company_brand_profile": (
        "Set a company's own branding",
        "Overrides the group's branding for one company, field by field. Needs `org.write` "
        "covering that company.\n" + _INHERIT,
    ),
    "delete_company_brand_profile": (
        "Use the group's branding again",
        "Removes a company's own branding, so every field comes from the group again.",
    ),
    "resolved_branding": (
        "The branding that applies to a company",
        """
What a document for this company prints, field by field, with where each value comes from:
`COMPANY` (its own), `GROUP` (the group default) or `DEFAULT` (built in). Also the company's
printed details and `color_check`: when the primary colour is too light to read on white, the
darker shade documents use for text, and its contrast ratio (at least 4.5). Omit
`legal_entity_id` for the group default.
""",
    ),
    "upload_brand_asset": (
        "Upload a logo or signature image",
        """
Multipart form: `kind` (`LOGO` or `SIGNATURE`) and `file`. PNG, JPEG or WebP up to 2 MB; SVG is
refused. The longer side must be at least 200 pixels for a logo, 150 for a signature. The image
is re-encoded as PNG (metadata dropped), scaled down to at most 1200 / 800 pixels, and stored
encrypted. Images are never changed or deleted, so a document issued with one can be
reproduced; uploading the same picture again returns the existing image.
""",
    ),
    "brand_asset_image": (
        "A logo or signature image",
        "The stored PNG. Logos need `org.read` or `payroll.write`. Signature images are shown "
        "only to `org.write`, and are never cached.",
    ),
    "list_signatories": (
        "List signatories",
        "People who sign documents: for one company, or (`legal_entity_id: null`) for any. "
        "Needs `org.write` or `payroll.write`.",
    ),
    "create_signatory": (
        "Add a signatory",
        "A name, optional designation and optional signature image (upload it first). A "
        "signatory for every company needs a group-level administrator.",
    ),
    "update_signatory": (
        "Change a signatory",
        "Replaces the signatory's details. Send the `version` you loaded.",
    ),
    "archive_signatory": (
        "Retire a signatory",
        "Removes the signatory from the list. Refused (`409`) while a payslip template signs "
        "with them.",
    ),
}
