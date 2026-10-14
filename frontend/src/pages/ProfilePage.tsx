import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Building2, ChevronRight, IdCard, KeyRound, Lock, Mail, Phone, ShieldCheck, UserRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { PageHeader } from "../components/ui/PageHeader";
import { NoEmployeeRecord, Skeleton } from "../components/ui/Feedback";
import { Avatar } from "../components/ui/Avatar";
import { StatusBadge, humanize } from "../components/ui/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { Tabs } from "../components/ui/Tabs";
import { useToast, errorMessage } from "../components/ui/Toast";
import { peopleApi } from "../api/people";
import { KycSection } from "../components/kyc/KycSection";
import { kycApi, type KycStatus } from "../api/kyc";
import { DetailGrid, DetailItem, EditableSection, EmptyValue, FieldGrid } from "../components/ui/EditableSection";
import { LockedNote } from "../components/integrations/ManagedFields";
import { useFieldControl } from "../components/integrations/fieldControl";

const GENDER_OPTIONS = [
  { value: "", label: "Prefer not to say" },
  { value: "MALE", label: "Male" },
  { value: "FEMALE", label: "Female" },
  { value: "NON_BINARY", label: "Non-binary" },
];

type ProfileTab = "personal" | "kyc";

type FormState = {
  preferredName: string;
  dateOfBirth: string;
  gender: string;
  nationality: string;
  mobile: string;
};

function toForm(p: { preferred_name: string | null; date_of_birth: string | null; gender: string | null; nationality: string | null; mobile: string | null }): FormState {
  return {
    preferredName: p.preferred_name ?? "",
    dateOfBirth: p.date_of_birth ?? "",
    gender: p.gender ?? "",
    nationality: p.nationality ?? "",
    mobile: p.mobile ?? "",
  };
}

export function ProfilePage() {
  const { user } = useAuth();
  // An administrator login created with the company has no person/employment
  // behind it, so there is no personal profile to load — show the account instead.
  if (user && !user.employmentId) return <AccountOnlyProfile user={user} />;
  return <EmployeeProfile />;
}

function ChangePasswordLink() {
  return (
    <Link to="/change-password" className="btn-secondary">
      <KeyRound size={15} /> Change password
    </Link>
  );
}

function AccountOnlyProfile({ user }: { user: NonNullable<ReturnType<typeof useAuth>["user"]> }) {
  const rows: [string, string][] = [
    ["Email", user.email ?? "—"],
    ["Access", user.roles.length ? user.roles.map(humanize).join(", ") : "—"],
    ["Organisation", user.tenantName],
    ["Companies", user.legalEntities.length ? user.legalEntities.map((e) => e.name).join(", ") : "—"],
  ];
  return (
    <div className="max-w-4xl">
      <PageHeader title="My profile" description="The account you’re signed in with." actions={<ChangePasswordLink />} />
      <div className="card mb-6 max-w-2xl p-6">
        <div className="flex items-center gap-4">
          <Avatar name={user.name} size="xl" />
          <div className="min-w-0">
            <p className="truncate text-base font-semibold text-fg">{user.name}</p>
            <p className="text-[13px] text-fg-subtle">Administrator account</p>
          </div>
        </div>
        <dl className="mt-5 divide-y divide-line rounded-xl border border-line text-[13px]">
          {rows.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-6 px-4 py-2.5">
              <dt className="shrink-0 text-fg-subtle">{k}</dt>
              <dd className="text-right font-medium text-fg">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="max-w-2xl"><NoEmployeeRecord feature="personal profile or KYC documents" /></div>
    </div>
  );
}

function regionName(code: string) {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

const KYC_LABEL: Record<KycStatus, string> = {
  VERIFIED: "KYC verified",
  SUBMITTED: "KYC under review",
  REJECTED: "KYC needs changes",
  ACTION_REQUIRED: "KYC needs changes",
  DRAFT: "KYC in progress",
  NOT_SUBMITTED: "KYC not started",
};

function EmployeeProfile() {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const activeTab: ProfileTab = params.get("tab") === "kyc" ? "kyc" : "personal";

  const handleTabChange = (tab: ProfileTab) => {
    const next = new URLSearchParams(params);
    if (tab === "personal") {
      next.delete("tab");
    } else {
      next.set("tab", tab);
    }
    setParams(next, { replace: true });
  };

  const profile = useQuery({ queryKey: ["my-profile"], queryFn: () => peopleApi.getMyProfile() });
  // Same key as KycSection, so switching tabs reuses the cached record.
  const kyc = useQuery({ queryKey: ["my-kyc"], queryFn: () => kycApi.getMyKyc() });
  const [form, setForm] = useState<FormState | null>(null);
  const [editingVersion, setEditingVersion] = useState<number>();
  // Fields a connected app (e.g. the company's ERP) manages: shown read-only here.
  const control = useFieldControl(user?.employmentId);
  const lockOf = (field: string) => control.data?.find((f) => f.field === field && f.locked);

  const update = useMutation({
    mutationFn: (body: Parameters<typeof peopleApi.updateMyProfile>[0]) =>
      peopleApi.updateMyProfile({ ...body, version: editingVersion }),
    onSuccess: (p) => {
      qc.setQueryData(["my-profile"], p);
      setForm(null);
      toast.success("Profile updated");
    },
    onError: (e) => toast.error("Couldn't update profile", errorMessage(e)),
  });

  const header = (
    <PageHeader
      title="My profile"
      description="Your personal details and statutory KYC documents."
      actions={<ChangePasswordLink />}
    />
  );

  if (profile.isError) {
    return (
      <div>
        {header}
        <div className="card p-6 text-center">
          <p className="text-sm font-medium text-fg">Couldn’t load your profile</p>
          <p className="mt-1 text-xs text-fg-subtle">{errorMessage(profile.error)}</p>
          <button type="button" className="btn-secondary btn-sm mt-4" onClick={() => profile.refetch()}>Try again</button>
        </div>
      </div>
    );
  }

  if (profile.isPending) {
    return (
      <div>
        {header}
        <Skeleton className="mb-6 h-24 rounded-xl" />
        <div className="card space-y-4 p-6">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}
        </div>
      </div>
    );
  }

  const p = profile.data;
  const legalName = `${p.legal_first_name} ${p.legal_last_name}`.trim();
  const displayName = p.preferred_name?.trim() || legalName;
  const editing = form !== null;
  const dirty = !!form && (
    form.preferredName !== (p.preferred_name ?? "")
    || form.dateOfBirth !== (p.date_of_birth ?? "")
    || form.gender !== (p.gender ?? "")
    || form.nationality !== (p.nationality ?? "")
    || form.mobile !== (p.mobile ?? "")
  );

  const save = () => {
    if (!form) return;
    if (!dirty) {
      setForm(null);
      return;
    }
    update.mutate({
      preferred_name: form.preferredName.trim() || null,
      date_of_birth: form.dateOfBirth || null,
      gender: form.gender || null,
      nationality: form.nationality.trim().toUpperCase() || null,
      mobile: form.mobile.trim() || null,
    });
  };

  const set = (key: keyof FormState) => (value: string) => setForm((f) => f && ({ ...f, [key]: value }));

  return (
    <div>
      {header}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px] xl:items-start">
      {/* ── Summary rail: on top below xl, a sticky right column on wide screens.
           xl:mt-16 matches the tab bar (h-10 + mb-6) so the first cards line up. ── */}
      <aside className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] xl:sticky xl:top-6 xl:order-2 xl:mt-16 xl:grid-cols-1">
        <section className="card p-5">
          <div className="flex items-center gap-4 xl:flex-col xl:text-center">
            <Avatar name={displayName} size="xl" />
            <div className="min-w-0">
              <p className="truncate text-base font-semibold text-fg">{displayName}</p>
              {displayName !== legalName && <p className="truncate text-xs text-fg-subtle">Legal name: {legalName}</p>}
              {user?.roles.length ? (
                <div className="mt-1.5 flex flex-wrap gap-1 xl:justify-center">
                  {user.roles.map((r) => <span key={r} className="badge badge-brand">{humanize(r)}</span>)}
                </div>
              ) : null}
            </div>
          </div>
          <dl className="mt-4 grid gap-3 border-t border-line pt-4 text-[13px] sm:grid-cols-3 xl:grid-cols-1">
            <RailRow icon={Mail} label="Email" value={p.email} />
            <RailRow icon={Phone} label="Mobile" value={p.mobile} />
            <RailRow icon={Building2} label="Organisation" value={user?.tenantName} />
          </dl>
        </section>

        {kyc.data && (
          <section className="card p-5">
            <div className="flex items-center justify-between gap-2">
              <p className="flex items-center gap-2 text-[13px] font-semibold text-fg">
                <ShieldCheck size={15} className={kyc.data.status === "VERIFIED" ? "text-success" : "text-fg-subtle"} />
                KYC
              </p>
              <StatusBadge status={kyc.data.status} />
            </div>
            <p className="mt-2 text-xs text-fg-subtle">{KYC_LABEL[kyc.data.status] ?? "KYC"}</p>
            <div className="mt-3 flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full ${kyc.data.completion_percentage === 100 ? "bg-success" : "bg-brand-500"}`}
                  style={{ width: `${kyc.data.completion_percentage}%` }}
                />
              </div>
              <span className="text-xs font-semibold tabular-nums text-fg">{kyc.data.completion_percentage}%</span>
            </div>
            <p className="mt-2 text-xs text-fg-subtle">
              {kyc.data.documents.length} document{kyc.data.documents.length === 1 ? "" : "s"} uploaded
              {kyc.data.documents.length > 0 && ` · ${kyc.data.documents.filter((d) => d.status === "VERIFIED").length} verified`}
            </p>
            {activeTab !== "kyc" && (
              <button type="button" className="btn-secondary btn-sm mt-4 w-full" onClick={() => handleTabChange("kyc")}>
                {kyc.data.status === "VERIFIED" ? "View KYC & documents" : "Continue KYC"} <ChevronRight size={13} />
              </button>
            )}
          </section>
        )}
      </aside>

      <div className="min-w-0 xl:order-1">
      <Tabs<ProfileTab>
        className="mb-6"
        value={activeTab}
        onChange={handleTabChange}
        items={[
          { value: "personal", label: "Personal details" },
          { value: "kyc", label: "KYC & Documents" },
        ]}
      />

      {activeTab === "kyc" ? (
        <KycSection isSelf={true} />
      ) : (
        <div className="space-y-5">
          <EditableSection
            icon={UserRound}
            title="Personal information"
            description="How you’d like to be addressed and how we can reach you"
            editing={editing}
            canEdit={true}
            onEdit={() => { setEditingVersion(p.version); setForm(toForm(p)); }}
            onCancel={() => setForm(null)}
            onSubmit={save}
            saving={update.isPending}
            saveDisabled={!dirty}
          >
            {form ? (
              <FieldGrid min={220}>
                <div>
                  <label className="label" htmlFor="pf-preferred">Preferred name</label>
                  <input
                    id="pf-preferred" className="input" placeholder="What should we call you?" maxLength={100} autoFocus
                    disabled={!!lockOf("preferred_name")}
                    value={form.preferredName} onChange={(e) => set("preferredName")(e.target.value)}
                  />
                  <LockedNote field={lockOf("preferred_name")} />
                </div>
                <div>
                  <label className="label" htmlFor="pf-dob">Date of birth</label>
                  <input
                    id="pf-dob" type="date" className="input" max={new Date().toISOString().slice(0, 10)}
                    disabled={!!lockOf("date_of_birth")}
                    value={form.dateOfBirth} onChange={(e) => set("dateOfBirth")(e.target.value)}
                  />
                  <LockedNote field={lockOf("date_of_birth")} />
                </div>
                <div>
                  <label className="label" htmlFor="pf-gender">Gender</label>
                  <select id="pf-gender" className="input" value={form.gender} disabled={!!lockOf("gender")} onChange={(e) => set("gender")(e.target.value)}>
                    {GENDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                  <LockedNote field={lockOf("gender")} />
                </div>
                <div>
                  <label className="label" htmlFor="pf-nationality">Nationality</label>
                  <input
                    id="pf-nationality" className="input font-mono uppercase" maxLength={2} placeholder="IN"
                    value={form.nationality} onChange={(e) => set("nationality")(e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))}
                  />
                  <p className="mt-1 text-[11px] text-fg-subtle">
                    {form.nationality.length === 2 ? regionName(form.nationality) : "Two-letter country code, e.g. IN"}
                  </p>
                </div>
                <div>
                  <label className="label" htmlFor="pf-mobile">Mobile</label>
                  <input
                    id="pf-mobile" type="tel" className="input" placeholder="+91 98765 43210" maxLength={20}
                    disabled={!!lockOf("mobile")}
                    value={form.mobile} onChange={(e) => set("mobile")(e.target.value)}
                  />
                  <LockedNote field={lockOf("mobile")} />
                </div>
              </FieldGrid>
            ) : (
              <DetailGrid min={220}>
                <DetailItem label="Preferred name">{p.preferred_name || <EmptyValue />}</DetailItem>
                <DetailItem label="Date of birth">
                  {p.date_of_birth ? format(parseISO(p.date_of_birth), "d MMMM yyyy") : <EmptyValue />}
                </DetailItem>
                <DetailItem label="Gender">
                  {p.gender ? (GENDER_OPTIONS.find((o) => o.value === p.gender)?.label ?? humanize(p.gender)) : <EmptyValue />}
                </DetailItem>
                <DetailItem label="Nationality">
                  {p.nationality ? `${regionName(p.nationality)} (${p.nationality})` : <EmptyValue />}
                </DetailItem>
                <DetailItem label="Mobile">{p.mobile || <EmptyValue />}</DetailItem>
              </DetailGrid>
            )}
          </EditableSection>

          <EditableSection
            icon={IdCard}
            title="Legal identity"
            description="Managed by HR. Contact HR if any of these need to change."
            editing={false}
            canEdit={false}
            onEdit={() => {}}
            onCancel={() => {}}
            onSubmit={() => {}}
            headerExtra={<span className="badge badge-neutral"><Lock size={11} /> Read-only</span>}
          >
            <DetailGrid min={220}>
              <DetailItem label="Legal first name">{p.legal_first_name || <EmptyValue />}</DetailItem>
              <DetailItem label="Legal last name">{p.legal_last_name || <EmptyValue />}</DetailItem>
              <DetailItem label="Work email">{p.email || <EmptyValue />}</DetailItem>
            </DetailGrid>
          </EditableSection>
        </div>
      )}
      </div>
      </div>
    </div>
  );
}

function RailRow({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value?: string | null }) {
  return (
    <div className="flex items-start gap-2.5">
      <Icon size={14} className="mt-0.5 shrink-0 text-fg-subtle" />
      <div className="min-w-0">
        <dt className="text-[11px] text-fg-subtle">{label}</dt>
        <dd className="truncate font-medium text-fg" title={value ?? undefined}>{value || "—"}</dd>
      </div>
    </div>
  );
}
