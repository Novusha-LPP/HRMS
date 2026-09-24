import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { peopleApi } from "../api/people";

const GENDER_OPTIONS = [
  { value: "", label: "Prefer not to say" },
  { value: "MALE", label: "Male" },
  { value: "FEMALE", label: "Female" },
  { value: "NON_BINARY", label: "Non-binary" },
];

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
  const qc = useQueryClient();
  const toast = useToast();
  const profile = useQuery({ queryKey: ["my-profile"], queryFn: () => peopleApi.getMyProfile() });
  const [form, setForm] = useState<FormState | null>(null);

  useEffect(() => {
    if (profile.data) setForm(toForm(profile.data));
  }, [profile.data]);

  const update = useMutation({
    mutationFn: (body: Parameters<typeof peopleApi.updateMyProfile>[0]) => peopleApi.updateMyProfile(body),
    onSuccess: (p) => {
      qc.setQueryData(["my-profile"], p);
      toast.success("Profile updated");
    },
    onError: (e) => toast.error("Couldn't update profile", errorMessage(e)),
  });

  if (profile.isPending || !form) {
    return (
      <>
        <PageHeader title="My profile" description="Update your personal details." />
        <div className="card max-w-xl space-y-4 p-6">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}
        </div>
      </>
    );
  }

  if (profile.isError || !profile.data) {
    return (
      <>
        <PageHeader title="My profile" description="Update your personal details." />
        <div className="card p-6 text-sm text-danger">Couldn't load your profile. Try refreshing.</div>
      </>
    );
  }

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
    <>
      <PageHeader title="My profile" description="Update your personal details." />

      <form onSubmit={submit} className="max-w-xl space-y-6">
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
    </>
  );
}
