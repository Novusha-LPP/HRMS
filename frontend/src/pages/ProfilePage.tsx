import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { PageHeader } from "../components/ui/PageHeader";
import { NoEmployeeRecord, Skeleton } from "../components/ui/Feedback";
import { Avatar } from "../components/ui/Avatar";
import { humanize } from "../components/ui/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { Tabs } from "../components/ui/Tabs";
import { useToast, errorMessage } from "../components/ui/Toast";
import { peopleApi } from "../api/people";
import { KycSection } from "../components/kyc/KycSection";

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

function EmployeeProfile() {
  const qc = useQueryClient();
  const toast = useToast();
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
  const [form, setForm] = useState<FormState | null>(null);
  const [prevProfileData, setPrevProfileData] = useState(profile.data);

  if (profile.data && profile.data !== prevProfileData && !form) {
    setPrevProfileData(profile.data);
    setForm(toForm(profile.data));
  }

  const update = useMutation({
    mutationFn: (body: Parameters<typeof peopleApi.updateMyProfile>[0]) => peopleApi.updateMyProfile(body),
    onSuccess: (p) => {
      qc.setQueryData(["my-profile"], p);
      toast.success("Profile updated");
    },
    onError: (e) => toast.error("Couldn't update profile", errorMessage(e)),
  });

  if (profile.isError) {
    return (
      <>
        <PageHeader title="My profile" description="Update your personal details and statutory KYC documents." />
        <div className="card p-6 text-sm text-danger">Couldn't load your profile. Try refreshing.</div>
      </>
    );
  }

  if (profile.isPending || !form) {
    return (
      <>
        <PageHeader title="My profile" description="Update your personal details and statutory KYC documents." />
        <div className="card max-w-xl space-y-4 p-6">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}
        </div>
      </>
    );
  }

  if (!profile.data) return null;

  const p = profile.data;
  const dirty = form.preferredName !== (p.preferred_name ?? "")
    || form.dateOfBirth !== (p.date_of_birth ?? "")
    || form.gender !== (p.gender ?? "")
    || form.nationality !== (p.nationality ?? "")
    || form.mobile !== (p.mobile ?? "");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!dirty) return;
    update.mutate({
      preferred_name: form.preferredName.trim() || null,
      date_of_birth: form.dateOfBirth || null,
      gender: form.gender || null,
      nationality: form.nationality.trim().toUpperCase() || null,
      mobile: form.mobile.trim() || null,
    });
  };

  return (
    <div className="max-w-4xl">
      <PageHeader title="My profile" description="Update your personal details and statutory KYC documents." actions={<ChangePasswordLink />} />

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
        <form onSubmit={submit} className="space-y-6 max-w-2xl">
          <div className="card p-6">
          <p className="eyebrow">Legal identity</p>
          <p className="mt-1 text-xs text-fg-subtle">
            Your legal name and email are managed by HR — contact them if these need to change.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <label className="label">Legal first name</label>
              <input className="input" value={p.legal_first_name} disabled />
            </div>
            <div>
              <label className="label">Legal last name</label>
              <input className="input" value={p.legal_last_name} disabled />
            </div>
          </div>
          <div className="mt-3">
            <label className="label">Email</label>
            <input className="input" value={p.email ?? "—"} disabled />
          </div>
        </div>

        <div className="card p-6">
          <p className="eyebrow">Personal details</p>
          <div className="mt-4 space-y-3.5">
            <div>
              <label className="label" htmlFor="pf-preferred">Preferred name</label>
              <input
                id="pf-preferred" className="input" placeholder="What should we call you?"
                value={form.preferredName} onChange={(e) => setForm((f) => f && ({ ...f, preferredName: e.target.value }))}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="pf-dob">Date of birth</label>
                <input
                  id="pf-dob" type="date" className="input"
                  value={form.dateOfBirth} onChange={(e) => setForm((f) => f && ({ ...f, dateOfBirth: e.target.value }))}
                />
              </div>
              <div>
                <label className="label" htmlFor="pf-gender">Gender</label>
                <select
                  id="pf-gender" className="input" value={form.gender}
                  onChange={(e) => setForm((f) => f && ({ ...f, gender: e.target.value }))}
                >
                  {GENDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="pf-nationality">Nationality <span className="font-normal text-fg-subtle">(2-letter code)</span></label>
                <input
                  id="pf-nationality" className="input" maxLength={2} placeholder="IN"
                  value={form.nationality} onChange={(e) => setForm((f) => f && ({ ...f, nationality: e.target.value.toUpperCase() }))}
                />
              </div>
              <div>
                <label className="label" htmlFor="pf-mobile">Mobile</label>
                <input
                  id="pf-mobile" type="tel" className="input" placeholder="+91 98765 43210"
                  value={form.mobile} onChange={(e) => setForm((f) => f && ({ ...f, mobile: e.target.value }))}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button type="submit" className="btn-primary" disabled={!dirty || update.isPending}>
            {update.isPending ? "Saving…" : "Save changes"}
          </button>
          {dirty && !update.isPending && (
            <button type="button" className="btn-ghost" onClick={() => setForm(toForm(p))}>Discard changes</button>
          )}
        </div>
      </form>
      )}
    </div>
  );
}
