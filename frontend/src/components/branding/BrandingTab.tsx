import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, ImageUp, Palette, PenLine, Plus, RotateCcw, Trash2, Pencil, Signature as SignatureIcon } from "lucide-react";
import { brandingApi } from "../../api/branding";
import type { AssetKind, BrandAsset, BrandProfile, BrandProfileInput, ResolvedBranding, Signatory } from "../../api/branding";
import { orgApi } from "../../api/org";
import type { LegalEntity } from "../../api/org";
import { Sheet, ConfirmDialog } from "../ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { DEFAULT_ACCENT, DEFAULT_PRIMARY, isHexColor, readableOnWhite, textOn, useBrandImage } from "./brand";
import { PayslipTemplateEditor } from "./PayslipTemplateEditor";

/** A payslip-style header: how a company's documents will open. */
export function BrandBand({ name, address, logoUrl, primary, compact = false }: {
  name: string; address?: string | null; logoUrl: string | null; primary: string; compact?: boolean;
}) {
  return (
    <div className={`flex min-w-0 items-center gap-3 rounded-lg ${compact ? "px-3 py-2" : "px-4 py-3"}`} style={{ background: primary, color: textOn(primary) }}>
      {logoUrl ? (
        <span className={`grid shrink-0 place-items-center rounded-md bg-white ${compact ? "h-8 px-1.5" : "h-11 px-2"}`}>
          <img src={logoUrl} alt="" className={compact ? "max-h-6 max-w-[72px]" : "max-h-8 max-w-[110px]"} />
        </span>
      ) : (
        <span className={`grid shrink-0 place-items-center rounded-md bg-white/20 ${compact ? "h-8 w-8" : "h-11 w-11"}`}><Building2 size={compact ? 15 : 18} /></span>
      )}
      <div className="min-w-0">
        <p className={`truncate font-semibold ${compact ? "text-sm" : "text-[15px]"}`}>{name}</p>
        {!compact && <p className="truncate text-xs opacity-85">{address || "Registered address not set"}</p>}
      </div>
      {!compact && <p className="ml-auto shrink-0 text-right text-xs font-semibold">Payslip<br /><span className="font-normal opacity-85">Sample month</span></p>}
    </div>
  );
}

function addressOf(company: ResolvedBranding["company"] | LegalEntity | undefined): string | null {
  if (!company) return null;
  const place = [company.state_code, company.pincode].filter(Boolean).join(" ");
  return [company.address_line1, company.address_line2, company.city, place].filter(Boolean).join(", ") || null;
}

/**
 * Organization → Branding: how payslips (and later letters) look. The group sets it once;
 * a company overrides only what differs. The payslip layout is set up underneath.
 */
export function BrandingTab({ canEditGroup, canEdit }: { canEditGroup: boolean; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const companies = useQuery({ queryKey: ["legal-entities"], queryFn: () => orgApi.listLegalEntities() });
  const profiles = useQuery({ queryKey: ["branding", "profiles"], queryFn: () => brandingApi.profiles() });
  const group = useQuery({ queryKey: ["branding", "resolved", null], queryFn: () => brandingApi.resolved(null) });
  const [editing, setEditing] = useState<{ company: LegalEntity | null } | null>(null);
  const [resetting, setResetting] = useState<LegalEntity | null>(null);
  const groupLogo = useBrandImage(group.data?.logo?.id);

  const reset = useMutation({
    mutationFn: (company: LegalEntity) => brandingApi.resetCompany(company.id),
    onSuccess: (_, company) => { qc.invalidateQueries({ queryKey: ["branding"] }); toast.success("Uses the group’s branding again", company.name); setResetting(null); },
    onError: (e) => toast.error("Couldn’t reset the branding", errorMessage(e)),
  });

  if (profiles.isError || group.isError) return <Notice title="Couldn’t load branding">The branding API isn’t responding.</Notice>;
  if (profiles.isPending || group.isPending || companies.isPending) return <Skeleton className="h-72 rounded-xl" />;

  const own = new Map((profiles.data ?? []).filter((p) => p.legal_entity_id).map((p) => [p.legal_entity_id!, p]));
  const groupRow = (profiles.data ?? []).find((p) => p.legal_entity_id === null);
  const groupPrimary = group.data.fields.primary_color.value ?? DEFAULT_PRIMARY;

  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-sm text-fg-muted">
        How payslips look. Set the logo, colours and footer once for the group; a company with a different look overrides only what differs. Company addresses and registration numbers come from each company’s details.
      </p>

      <section className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-semibold text-fg">Group default</h2>
            <p className="text-sm text-fg-muted">Every company uses this unless it sets its own.</p>
          </div>
          <button className="btn-secondary" onClick={() => setEditing({ company: null })} disabled={!canEditGroup}
            title={canEditGroup ? undefined : "Only a group-level administrator can change the group’s branding"}>
            <Palette size={15} /> Edit group branding
          </button>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="min-w-0"><BrandBand name={group.data.company.name} address="Each company prints its own address" logoUrl={groupLogo} primary={groupPrimary} /></div>
          <dl className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            <dt className="text-fg-subtle">Logo</dt><dd className="text-fg">{group.data.logo ? group.data.logo.file_name : "None"}</dd>
            <dt className="text-fg-subtle">Colours</dt>
            <dd className="flex items-center gap-2 text-fg">
              <Swatch color={groupPrimary} /><Swatch color={group.data.fields.accent_color.value ?? DEFAULT_ACCENT} />
              {!groupRow?.primary_color && <span className="text-xs text-fg-subtle">built-in</span>}
            </dd>
            <dt className="text-fg-subtle">Footer</dt><dd className="truncate text-fg">{group.data.fields.footer_text.value ?? "—"}</dd>
            <dt className="text-fg-subtle">Contact</dt><dd className="truncate text-fg">{[group.data.fields.contact_email.value, group.data.fields.contact_phone.value].filter(Boolean).join(" · ") || "—"}</dd>
          </dl>
        </div>
        {group.data.color_check.adjusted && (
          <p className="mt-3 text-xs text-fg-muted">The brand colour is light, so payslip text uses a darker shade of it (<Swatch color={group.data.color_check.text_color} inline /> {group.data.color_check.text_color}) to stay readable.</p>
        )}
      </section>

      <section className="card p-5">
        <h2 className="text-[15px] font-semibold text-fg">Companies</h2>
        <p className="text-sm text-fg-muted">A company with its own branding overrides the group field by field.</p>
        {!companies.data?.length ? (
          <EmptyState icon={Building2} title="No companies yet" description="Add a company first." />
        ) : (
          <ul className="mt-3 divide-y divide-line">
            {companies.data.map((c) => (
              <CompanyRow key={c.id} company={c} profile={own.get(c.id)} group={group.data} groupLogo={groupLogo} canEdit={canEdit}
                onEdit={() => setEditing({ company: c })} onReset={() => setResetting(c)} />
            ))}
          </ul>
        )}
      </section>

      {canEdit && <SignatoriesSection companies={companies.data ?? []} canEditGroup={canEditGroup} />}

      <section className="card p-5">
        <h2 className="text-[15px] font-semibold text-fg">Payslip layout</h2>
        <p className="mb-4 text-sm text-fg-muted">What a payslip shows and how it is laid out. The preview uses made-up figures, so no one’s pay is shown.</p>
        <PayslipTemplateEditor canEditGroup={canEditGroup} canEdit={canEdit} />
      </section>

      {editing && (
        <BrandProfileSheet
          key={editing.company?.id ?? "group"}
          company={editing.company}
          profile={editing.company ? own.get(editing.company.id) : groupRow}
          group={group.data}
          onClose={() => setEditing(null)}
        />
      )}
      <ConfirmDialog
        open={resetting !== null}
        onClose={() => setResetting(null)}
        onConfirm={() => resetting && reset.mutate(resetting)}
        title="Use the group’s branding?"
        description={resetting ? `${resetting.name}’s own logo, colours and footer are removed, and its payslips use the group’s again.` : ""}
        confirmLabel="Use group branding"
        loading={reset.isPending}
      />
    </div>
  );
}

function Swatch({ color, inline = false }: { color: string; inline?: boolean }) {
  return <span className={`${inline ? "inline-block align-[-2px]" : "inline-block"} h-3.5 w-3.5 rounded-full border border-line`} style={{ background: color }} aria-label={color} />;
}

function CompanyRow({ company, profile, group, groupLogo, canEdit, onEdit, onReset }: {
  company: LegalEntity; profile?: BrandProfile; group: ResolvedBranding; groupLogo: string | null;
  canEdit: boolean; onEdit: () => void; onReset: () => void;
}) {
  const ownLogo = useBrandImage(profile?.logo?.id);
  const primary = profile?.primary_color ?? group.fields.primary_color.value ?? DEFAULT_PRIMARY;
  const missingDetails = !company.address_line1 || !(company.registered_name || company.name);
  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <div className="w-full sm:w-56 sm:shrink-0"><BrandBand compact name={company.short_name || company.name} logoUrl={ownLogo ?? groupLogo} primary={primary} /></div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-fg">{company.registered_name || company.name}</p>
        <p className="truncate text-xs text-fg-subtle">{addressOf(company) ?? "Registered address not set — add it in the company’s details"}</p>
      </div>
      {profile ? <span className="badge badge-brand">Own branding</span> : <span className="badge badge-neutral">Uses group</span>}
      {missingDetails && <span className="badge badge-warning">Address missing</span>}
      <div className="flex gap-1">
        <button className="btn-secondary btn-sm" onClick={onEdit} disabled={!canEdit}><Pencil size={13} /> {profile ? "Edit" : "Customize"}</button>
        {profile && <button className="btn-icon" onClick={onReset} disabled={!canEdit} aria-label={`Use the group’s branding for ${company.name}`} title="Use the group’s branding"><RotateCcw size={14} /></button>}
      </div>
    </li>
  );
}

// ─── Editing a profile ─────────────────────────────────────────────────────

type Form = { [K in keyof BrandProfileInput]: string };

function toForm(profile?: BrandProfile): Form {
  return {
    logo_asset_id: profile?.logo?.id ?? "",
    primary_color: profile?.primary_color ?? "",
    accent_color: profile?.accent_color ?? "",
    footer_text: profile?.footer_text ?? "",
    contact_email: profile?.contact_email ?? "",
    contact_phone: profile?.contact_phone ?? "",
    website: profile?.website ?? "",
  };
}

function BrandProfileSheet({ company, profile, group, onClose }: {
  company: LegalEntity | null; profile?: BrandProfile; group: ResolvedBranding; onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<Form>(() => toForm(profile));
  const [logo, setLogo] = useState<BrandAsset | null>(profile?.logo ?? null);
  const set = (key: keyof Form) => (value: string) => setForm((f) => ({ ...f, [key]: value }));
  const isCompany = company !== null;
  // What an empty field falls back to: the group's value for a company, the built-in default for the group.
  const fallback = (key: keyof BrandProfileInput): string | null => {
    if (isCompany) return group.fields[key].value;
    return key === "primary_color" ? DEFAULT_PRIMARY : key === "accent_color" ? DEFAULT_ACCENT : null;
  };
  const ownLogoUrl = useBrandImage(form.logo_asset_id || null);
  const inheritedLogoUrl = useBrandImage(isCompany && !form.logo_asset_id ? group.logo?.id : null);
  const primary = form.primary_color && isHexColor(form.primary_color) ? form.primary_color.toUpperCase() : fallback("primary_color") ?? DEFAULT_PRIMARY;
  const printed = readableOnWhite(primary);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        logo_asset_id: form.logo_asset_id || null,
        primary_color: form.primary_color || null,
        accent_color: form.accent_color || null,
        footer_text: form.footer_text.trim() || null,
        contact_email: form.contact_email.trim() || null,
        contact_phone: form.contact_phone.trim() || null,
        website: form.website.trim() || null,
        version: profile?.version,
      };
      return company ? brandingApi.saveCompany(company.id, body) : brandingApi.saveGroup(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["branding"] });
      qc.invalidateQueries({ queryKey: ["payslip-preview"] });
      toast.success("Branding saved", company?.name ?? "Group default");
      onClose();
    },
    onError: (e) => toast.error("Couldn’t save the branding", errorMessage(e)),
  });

  const colorsValid = [form.primary_color, form.accent_color].every((c) => !c || isHexColor(c));
  const submit = (e: FormEvent) => { e.preventDefault(); if (colorsValid) save.mutate(); };

  return (
    <Sheet open onClose={onClose} className="max-w-lg"
      title={company ? `Branding — ${company.name}` : "Group branding"}
      description={company ? "Leave a field empty to use the group’s value, shown in grey." : "Every company uses these unless it sets its own."}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="brand-form" disabled={!colorsValid || save.isPending}>{save.isPending ? "Saving…" : "Save branding"}</button>
      </>}
    >
      <form id="brand-form" onSubmit={submit} className="space-y-5">
        <BrandBand name={company ? company.registered_name || company.name : group.company.name} address={company ? addressOf(company) : "Each company prints its own address"}
          logoUrl={ownLogoUrl ?? inheritedLogoUrl} primary={primary} />

        <div>
          <p className="label">Logo</p>
          <div className="flex flex-wrap items-center gap-2">
            <AssetUpload kind="LOGO" label={form.logo_asset_id ? "Replace logo" : "Upload logo"} onUploaded={(a) => { setLogo(a); set("logo_asset_id")(a.id); }} />
            {form.logo_asset_id && (
              <button type="button" className="btn-secondary btn-sm" onClick={() => { setLogo(null); set("logo_asset_id")(""); }}>
                <Trash2 size={13} /> {isCompany ? "Use the group’s logo" : "Remove logo"}
              </button>
            )}
          </div>
          <p className="mt-1 text-xs text-fg-subtle">
            {form.logo_asset_id ? `${logo?.file_name ?? "Logo"}${logo ? ` · ${logo.width}×${logo.height}` : ""}. ` : isCompany ? "Uses the group’s logo. " : ""}
            PNG, JPEG or WebP, up to 2 MB, at least 200 pixels wide. A transparent or white background prints best.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <ColorField id="brand-primary" label="Brand colour" value={form.primary_color} placeholder={fallback("primary_color")} onChange={set("primary_color")} />
          <ColorField id="brand-accent" label="Accent colour" value={form.accent_color} placeholder={fallback("accent_color")} onChange={set("accent_color")} />
        </div>
        {printed !== primary && (
          <Notice tone="info" title="This colour is light">Payslip text uses a darker shade, {printed}, so it stays readable on white. The header band keeps your colour.</Notice>
        )}

        <div>
          <label className="label" htmlFor="brand-footer">Footer</label>
          <textarea id="brand-footer" className="input min-h-[68px]" maxLength={500} placeholder={fallback("footer_text") ?? "e.g. Registered office: Plot 12, MIDC, Andheri East, Mumbai 400093"}
            value={form.footer_text} onChange={(e) => set("footer_text")(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="brand-email">Contact email</label>
            <input id="brand-email" type="email" className="input" placeholder={fallback("contact_email") ?? "payroll@company.com"} value={form.contact_email} onChange={(e) => set("contact_email")(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="brand-phone">Contact phone</label>
            <input id="brand-phone" className="input" maxLength={30} placeholder={fallback("contact_phone") ?? "+91 22 4000 0000"} value={form.contact_phone} onChange={(e) => set("contact_phone")(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="brand-website">Website</label>
          <input id="brand-website" className="input" placeholder={fallback("website") ?? "www.company.com"} value={form.website} onChange={(e) => set("website")(e.target.value)} />
        </div>
      </form>
    </Sheet>
  );
}

function ColorField({ id, label, value, placeholder, onChange }: {
  id: string; label: string; value: string; placeholder: string | null; onChange: (v: string) => void;
}) {
  const shown = value && isHexColor(value) ? value : placeholder ?? DEFAULT_PRIMARY;
  return (
    <div>
      <label className="label" htmlFor={id}>{label}</label>
      <div className="flex items-center gap-2">
        <input type="color" aria-label={`${label} picker`} className="h-9 w-10 shrink-0 cursor-pointer rounded-md border border-line bg-transparent p-0.5" value={shown} onChange={(e) => onChange(e.target.value.toUpperCase())} />
        <input id={id} className="input font-mono" maxLength={7} placeholder={placeholder ?? ""} value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} />
      </div>
      {value && !isHexColor(value) && <p className="mt-1 text-xs text-danger">Use a hex colour such as #0F766E.</p>}
      {value && placeholder && <button type="button" className="mt-1 text-xs text-accent hover:underline" onClick={() => onChange("")}>Use {placeholder}</button>}
    </div>
  );
}

function AssetUpload({ kind, label, onUploaded }: { kind: AssetKind; label: string; onUploaded: (asset: BrandAsset) => void }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => brandingApi.upload(kind, file),
    onSuccess: onUploaded,
    onError: (e) => toast.error("Couldn’t use that image", errorMessage(e)),
  });
  return (
    <>
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
        onChange={(e) => { const file = e.target.files?.[0]; if (file) upload.mutate(file); e.target.value = ""; }} />
      <button type="button" className="btn-secondary btn-sm" onClick={() => input.current?.click()} disabled={upload.isPending}>
        <ImageUp size={13} /> {upload.isPending ? "Uploading…" : label}
      </button>
    </>
  );
}

// ─── Signatories ───────────────────────────────────────────────────────────

function SignatoriesSection({ companies, canEditGroup }: { companies: LegalEntity[]; canEditGroup: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const signatories = useQuery({ queryKey: ["branding", "signatories"], queryFn: () => brandingApi.signatories() });
  const [editing, setEditing] = useState<Signatory | "new" | null>(null);
  const [retiring, setRetiring] = useState<Signatory | null>(null);
  const names = new Map(companies.map((c) => [c.id, c.name]));
  const retire = useMutation({
    mutationFn: (s: Signatory) => brandingApi.archiveSignatory(s.id),
    onSuccess: (_, s) => { qc.invalidateQueries({ queryKey: ["branding", "signatories"] }); toast.success("Signatory retired", s.name); setRetiring(null); },
    onError: (e) => toast.error("Couldn’t retire the signatory", errorMessage(e)),
  });

  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold text-fg">Signatories</h2>
          <p className="text-sm text-fg-muted">Who signs payslips, when a layout is set to be signed. The signature image is shown only to people who manage branding.</p>
        </div>
        <button className="btn-secondary" onClick={() => setEditing("new")}><Plus size={15} /> Add signatory</button>
      </div>
      {signatories.isPending ? <Skeleton className="mt-3 h-16 rounded-lg" /> : !signatories.data?.length ? (
        <EmptyState icon={PenLine} title="No signatories yet" description="Payslips print “computer-generated, needs no signature” until a layout chooses someone who signs." />
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {signatories.data.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 py-3">
              <SignaturePreview assetId={s.signature?.id} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-fg">{s.name}</p>
                <p className="text-xs text-fg-subtle">{[s.designation, s.legal_entity_id ? names.get(s.legal_entity_id) ?? "One company" : "Every company"].filter(Boolean).join(" · ")}</p>
              </div>
              <button className="btn-icon" onClick={() => setEditing(s)} aria-label={`Edit ${s.name}`}><Pencil size={14} /></button>
              <button className="btn-icon" onClick={() => setRetiring(s)} aria-label={`Retire ${s.name}`}><Trash2 size={14} /></button>
            </li>
          ))}
        </ul>
      )}
      {editing && <SignatorySheet key={editing === "new" ? "new" : editing.id} initial={editing === "new" ? undefined : editing} companies={companies} canEditGroup={canEditGroup} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={retiring !== null}
        onClose={() => setRetiring(null)}
        onConfirm={() => retiring && retire.mutate(retiring)}
        title="Retire this signatory?"
        description={retiring ? `${retiring.name} is removed from the list. Payslips already issued keep their signature.` : ""}
        confirmLabel="Retire"
        loading={retire.isPending}
      />
    </section>
  );
}

function SignaturePreview({ assetId }: { assetId?: string | null }) {
  const url = useBrandImage(assetId);
  return (
    <span className="grid h-10 w-24 shrink-0 place-items-center rounded-md border border-line bg-white">
      {url ? <img src={url} alt="Signature" className="max-h-8 max-w-[88px]" /> : <SignatureIcon size={16} className="text-zinc-400" />}
    </span>
  );
}

function SignatorySheet({ initial, companies, canEditGroup, onClose }: {
  initial?: Signatory; companies: LegalEntity[]; canEditGroup: boolean; onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({
    name: initial?.name ?? "",
    designation: initial?.designation ?? "",
    company: initial ? initial.legal_entity_id ?? "" : canEditGroup ? "" : companies[0]?.id ?? "",
    signature: initial?.signature?.id ?? "",
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { name: form.name.trim(), designation: form.designation.trim() || null, legal_entity_id: form.company || null, signature_asset_id: form.signature || null };
      return initial ? brandingApi.updateSignatory(initial.id, { ...body, version: initial.version }) : brandingApi.createSignatory(body);
    },
    onSuccess: (s) => { qc.invalidateQueries({ queryKey: ["branding", "signatories"] }); qc.invalidateQueries({ queryKey: ["payslip-preview"] }); toast.success("Signatory saved", s.name); onClose(); },
    onError: (e) => toast.error("Couldn’t save the signatory", errorMessage(e)),
  });
  const valid = form.name.trim().length > 0;
  return (
    <Sheet open onClose={onClose} title={initial ? "Edit signatory" : "Add signatory"} description="The name and designation print under the signature."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="signatory-form" disabled={!valid || save.isPending}>{save.isPending ? "Saving…" : "Save signatory"}</button>
      </>}
    >
      <form id="signatory-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid) save.mutate(); }}>
        <div>
          <label className="label" htmlFor="sig-name">Name</label>
          <input id="sig-name" className="input" maxLength={120} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="sig-designation">Designation</label>
          <input id="sig-designation" className="input" maxLength={120} placeholder="e.g. Head of HR" value={form.designation} onChange={(e) => setForm((f) => ({ ...f, designation: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="sig-company">Signs for</label>
          <select id="sig-company" className="input" value={form.company} onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}>
            {canEditGroup && <option value="">Every company</option>}
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <p className="label">Signature image <span className="font-normal text-fg-subtle">(optional)</span></p>
          <div className="flex flex-wrap items-center gap-2">
            <SignaturePreview assetId={form.signature || null} />
            <AssetUpload kind="SIGNATURE" label={form.signature ? "Replace" : "Upload signature"} onUploaded={(a) => setForm((f) => ({ ...f, signature: a.id }))} />
            {form.signature && <button type="button" className="btn-secondary btn-sm" onClick={() => setForm((f) => ({ ...f, signature: "" }))}><Trash2 size={13} /> Remove</button>}
          </div>
          <p className="mt-1 text-xs text-fg-subtle">A scan on a white or transparent background, at least 150 pixels wide.</p>
        </div>
      </form>
    </Sheet>
  );
}
