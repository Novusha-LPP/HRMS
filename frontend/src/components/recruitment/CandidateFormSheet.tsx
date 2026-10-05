import { useRef, useState } from "react";
import type { DragEvent, FormEvent, ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Plus, Search, Trash2, UserRoundCheck, X } from "lucide-react";
import { Sheet } from "../ui/Overlay";
import { Segmented } from "../ui/Tabs";
import { useToast, errorMessage } from "../ui/Toast";
import { recruitmentApi } from "../../api/recruitment";
import type { Candidate, CandidateInput, CandidateLink, CandidateSource, LinkType, Stage } from "../../api/recruitment";
import { LINK_TYPES, SOURCES } from "./meta";
import { TagInput } from "./TagInput";
import { LinkIcon } from "./LinkIcon";

const MAX_RESUME_MB = 10;
const RESUME_ACCEPT = ".pdf,.doc,.docx";

type Form = {
  firstName: string; lastName: string; email: string; phone: string; location: string;
  company: string; title: string; experience: string; notice: string;
  currentCtc: string; expectedCtc: string; source: CandidateSource; sourceDetail: string;
  links: CandidateLink[]; skills: string[]; summary: string;
};

function fromCandidate(c: Candidate | null): Form {
  return {
    firstName: c?.first_name ?? "", lastName: c?.last_name ?? "", email: c?.email ?? "", phone: c?.phone ?? "",
    location: c?.location ?? "", company: c?.current_company ?? "", title: c?.current_title ?? "",
    experience: c?.total_experience_years ? String(Number(c.total_experience_years)) : "",
    notice: c?.notice_period_days !== null && c?.notice_period_days !== undefined ? String(c.notice_period_days) : "",
    currentCtc: c?.current_ctc ? String(Number(c.current_ctc)) : "",
    expectedCtc: c?.expected_ctc ? String(Number(c.expected_ctc)) : "",
    source: c?.source ?? "LINKEDIN", sourceDetail: c?.source_detail ?? "",
    links: c?.links?.length ? c.links : [{ type: "LINKEDIN", url: "" }],
    skills: c?.skills ?? [], summary: c?.summary ?? "",
  };
}

const num = (v: string) => (v.trim() === "" ? null : Number(v));

/** Guess the link type from the address, so pasting a URL is enough. */
function guessType(url: string, current: LinkType): LinkType {
  const u = url.toLowerCase();
  if (u.includes("linkedin.com")) return "LINKEDIN";
  if (u.includes("github.com")) return "GITHUB";
  if (/behance|dribbble|notion\.site|portfolio/.test(u)) return "PORTFOLIO";
  return current;
}

function validUrl(url: string) {
  const v = url.trim();
  if (!v) return true;
  try {
    const parsed = new URL(v.includes("://") ? v : `https://${v}`);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname.includes(".");
  } catch {
    return false;
  }
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-[13px] font-semibold text-fg">{title}</h3>
      {children}
    </section>
  );
}

/**
 * Add a candidate to an opening (new, or picked from the talent pool), or edit one.
 * The resume is uploaded right after the candidate is saved.
 */
export function CandidateFormSheet({ open, onClose, openingId, stages, candidate, showPay = true }: {
  open: boolean;
  onClose: () => void;
  /** Adding to this opening. Leave out when editing an existing candidate. */
  openingId?: string;
  stages?: Stage[];
  candidate?: Candidate | null;
  showPay?: boolean;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!candidate;
  const fileRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<"new" | "existing">("new");
  const [form, setForm] = useState<Form>(() => fromCandidate(candidate ?? null));
  const [resume, setResume] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [stageId, setStageId] = useState("");
  const [note, setNote] = useState("");
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Candidate | null>(null);

  const key = `${open}-${candidate?.id ?? "new"}-${candidate?.version ?? 0}`;
  const [lastKey, setLastKey] = useState(key);
  if (key !== lastKey) {
    setLastKey(key);
    setForm(fromCandidate(candidate ?? null));
    setResume(null); setFileError(null); setStageId(""); setNote(""); setMode("new"); setSearch(""); setPicked(null);
  }

  const pool = useQuery({
    queryKey: ["recruitment-candidates", "picker", search.trim()],
    queryFn: () => recruitmentApi.candidates({ q: search.trim(), limit: 8 }),
    enabled: open && !editing && mode === "existing",
  });

  const set = <K extends keyof Form>(k: K) => (v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const setLink = (i: number, patch: Partial<CandidateLink>) =>
    setForm((f) => ({ ...f, links: f.links.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));

  const pickFile = (file: File | undefined) => {
    if (!file) return;
    if (!/\.(pdf|docx?)$/i.test(file.name)) { setFileError("Upload a PDF or Word document."); return; }
    if (file.size > MAX_RESUME_MB * 1024 * 1024) { setFileError(`The limit is ${MAX_RESUME_MB} MB.`); return; }
    setFileError(null);
    setResume(file);
  };

  const body = (): CandidateInput => ({
    first_name: form.firstName.trim(), last_name: form.lastName.trim(),
    email: form.email.trim() || null, phone: form.phone.trim() || null, location: form.location.trim() || null,
    current_company: form.company.trim() || null, current_title: form.title.trim() || null,
    total_experience_years: num(form.experience), notice_period_days: num(form.notice),
    current_ctc: showPay ? num(form.currentCtc) : (candidate?.current_ctc ? Number(candidate.current_ctc) : null),
    expected_ctc: showPay ? num(form.expectedCtc) : (candidate?.expected_ctc ? Number(candidate.expected_ctc) : null),
    source: form.source, source_detail: form.sourceDetail.trim() || null,
    links: form.links.filter((l) => l.url.trim()).map((l) => ({ type: l.type, label: l.label?.trim() || null, url: l.url.trim() })),
    skills: form.skills, summary: form.summary.trim() || null,
  });

  const save = useMutation({
    mutationFn: async () => {
      if (editing) {
        let saved = await recruitmentApi.updateCandidate(candidate!.id, { ...body(), version: candidate!.version });
        if (resume) saved = await recruitmentApi.uploadResume(saved.id, resume);
        return { candidate: saved, matched: false };
      }
      const application = await recruitmentApi.addApplication(openingId!, {
        ...(mode === "existing" && picked ? { candidate_id: picked.id } : { candidate: body() }),
        stage_id: stageId || null,
        note: note.trim() || null,
      });
      if (resume && !application.matched_existing && mode === "new") {
        try {
          await recruitmentApi.uploadResume(application.candidate.id, resume);
        } catch (e) {
          toast.error("Candidate added, but the resume didn’t upload", errorMessage(e));
        }
      }
      return { candidate: application.candidate, matched: !!application.matched_existing };
    },
    onSuccess: ({ candidate: saved, matched }) => {
      qc.invalidateQueries({ queryKey: ["recruitment-applications"] });
      qc.invalidateQueries({ queryKey: ["recruitment-application"] });
      qc.invalidateQueries({ queryKey: ["recruitment-openings"] });
      qc.invalidateQueries({ queryKey: ["recruitment-opening"] });
      qc.invalidateQueries({ queryKey: ["recruitment-candidates"] });
      if (editing) toast.success("Candidate updated");
      else if (matched) toast.info(`${saved.full_name} was already in the talent pool`, "Added with their existing profile — edit it to update details or the resume.");
      else toast.success(`${saved.full_name} added to the pipeline`);
      onClose();
    },
    onError: (e) => toast.error(editing ? "Couldn’t update the candidate" : "Couldn’t add the candidate", errorMessage(e)),
  });

  const badLinks = form.links.some((l) => !validUrl(l.url));
  const emailOk = !form.email.trim() || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim());
  const validNew = form.firstName.trim() && form.lastName.trim() && emailOk && !badLinks;
  const valid = mode === "existing" && !editing ? !!picked : !!validNew;
  const entryStages = (stages ?? []).filter((s) => s.is_active && s.category === "ACTIVE");

  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      className="max-w-2xl"
      title={editing ? `Edit ${candidate!.full_name}` : "Add candidate"}
      description={editing ? "Changes apply to every opening this candidate is in." : "Add their details and resume, then move them through the pipeline."}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" form="candidate-form" className="btn-primary" disabled={!valid || save.isPending}>
            {save.isPending ? "Saving…" : editing ? "Save changes" : "Add to pipeline"}
          </button>
        </>
      }
    >
      <form id="candidate-form" onSubmit={submit} className="space-y-7">
        {!editing && (
          <Segmented<"new" | "existing">
            value={mode}
            onChange={setMode}
            items={[{ value: "new", label: "New candidate", icon: Plus }, { value: "existing", label: "From talent pool", icon: UserRoundCheck }]}
          />
        )}

        {!editing && mode === "existing" ? (
          <Group title="Find a candidate">
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
              <input className="input pl-8" autoFocus placeholder="Name, email, company or skill" value={search}
                onChange={(e) => { setSearch(e.target.value); setPicked(null); }} />
            </div>
            <ul className="max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line">
              {pool.isPending && <li className="px-3 py-3 text-xs text-fg-subtle">Searching…</li>}
              {pool.isError && <li className="px-3 py-3 text-xs text-danger">{errorMessage(pool.error)}</li>}
              {pool.data?.items.length === 0 && <li className="px-3 py-3 text-xs text-fg-subtle">No matching candidates.</li>}
              {pool.data?.items.map(({ candidate: c, applications }) => (
                <li key={c.id}>
                  <button type="button" onClick={() => setPicked(c)}
                    className={`flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted ${picked?.id === c.id ? "bg-brand-500/[0.06]" : ""}`}>
                    <span className={`mt-0.5 h-3.5 w-3.5 shrink-0 rounded-full border ${picked?.id === c.id ? "border-[5px] border-brand-600" : "border-line-strong"}`} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium text-fg">{c.full_name}</span>
                      <span className="block truncate text-xs text-fg-subtle">
                        {[c.current_title, c.current_company, c.email].filter(Boolean).join(" · ") || "No details"}
                      </span>
                      {applications.length > 0 && (
                        <span className="block truncate text-[11px] text-fg-subtle">In: {applications.map((a) => `${a.opening_code} (${a.stage_name})`).join(", ")}</span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Group>
        ) : (
          <>
            <Group title="Personal details">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="cf-first">First name</label>
                  <input id="cf-first" className="input" maxLength={100} autoFocus value={form.firstName} onChange={(e) => set("firstName")(e.target.value)} />
                </div>
                <div>
                  <label className="label" htmlFor="cf-last">Last name</label>
                  <input id="cf-last" className="input" maxLength={100} value={form.lastName} onChange={(e) => set("lastName")(e.target.value)} />
                </div>
                <div>
                  <label className="label" htmlFor="cf-email">Email</label>
                  <input id="cf-email" type="email" className="input" maxLength={320} placeholder="name@example.com" value={form.email} onChange={(e) => set("email")(e.target.value)} />
                  {!emailOk && <p className="hint text-danger">Enter a valid email address.</p>}
                </div>
                <div>
                  <label className="label" htmlFor="cf-phone">Phone</label>
                  <input id="cf-phone" type="tel" className="input" maxLength={30} placeholder="+91 98765 43210" value={form.phone} onChange={(e) => set("phone")(e.target.value)} />
                </div>
                <div className="sm:col-span-2">
                  <label className="label" htmlFor="cf-loc">Current location</label>
                  <input id="cf-loc" className="input" maxLength={120} placeholder="City" value={form.location} onChange={(e) => set("location")(e.target.value)} />
                </div>
              </div>
            </Group>

            <Group title="Experience">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="cf-company">Current company</label>
                  <input id="cf-company" className="input" maxLength={150} value={form.company} onChange={(e) => set("company")(e.target.value)} />
                </div>
                <div>
                  <label className="label" htmlFor="cf-title">Current title</label>
                  <input id="cf-title" className="input" maxLength={150} value={form.title} onChange={(e) => set("title")(e.target.value)} />
                </div>
                <div>
                  <label className="label" htmlFor="cf-exp">Total experience (years)</label>
                  <input id="cf-exp" type="number" min={0} max={60} step={0.5} className="input" value={form.experience} onChange={(e) => set("experience")(e.target.value)} />
                </div>
                <div>
                  <label className="label" htmlFor="cf-notice">Notice period (days)</label>
                  <input id="cf-notice" type="number" min={0} max={365} className="input" value={form.notice} onChange={(e) => set("notice")(e.target.value)} />
                </div>
                {showPay && (
                  <>
                    <div>
                      <label className="label" htmlFor="cf-cctc">Current CTC (annual)</label>
                      <input id="cf-cctc" type="number" min={0} step={1000} className="input" value={form.currentCtc} onChange={(e) => set("currentCtc")(e.target.value)} />
                    </div>
                    <div>
                      <label className="label" htmlFor="cf-ectc">Expected CTC (annual)</label>
                      <input id="cf-ectc" type="number" min={0} step={1000} className="input" value={form.expectedCtc} onChange={(e) => set("expectedCtc")(e.target.value)} />
                    </div>
                  </>
                )}
                <div>
                  <label className="label" htmlFor="cf-source">Source</label>
                  <select id="cf-source" className="input" value={form.source} onChange={(e) => set("source")(e.target.value as CandidateSource)}>
                    {Object.entries(SOURCES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor="cf-srcd">
                    {form.source === "REFERRAL" ? "Referred by" : form.source === "AGENCY" ? "Agency" : "Source detail"}
                    <span className="font-normal text-fg-subtle"> (optional)</span>
                  </label>
                  <input id="cf-srcd" className="input" maxLength={150} value={form.sourceDetail} onChange={(e) => set("sourceDetail")(e.target.value)} />
                </div>
              </div>
              <div>
                <label className="label" htmlFor="cf-skills">Skills</label>
                <TagInput id="cf-skills" value={form.skills} onChange={set("skills")} placeholder="Type a skill and press Enter" />
              </div>
            </Group>

            <Group title="Profiles & links">
              <div className="space-y-2">
                {form.links.map((link, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-panel text-fg-muted">
                      <LinkIcon type={link.type} size={15} />
                    </div>
                    <select aria-label="Link type" className="input w-36 shrink-0" value={link.type} onChange={(e) => setLink(i, { type: e.target.value as LinkType })}>
                      {Object.entries(LINK_TYPES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                    <div className="min-w-0 flex-1">
                      <input aria-label="Link address" className={`input ${!validUrl(link.url) ? "border-danger" : ""}`} placeholder="https://"
                        maxLength={500} value={link.url}
                        onChange={(e) => setLink(i, { url: e.target.value, type: guessType(e.target.value, link.type) })} />
                      {!validUrl(link.url) && <p className="hint text-danger">Enter a valid web address.</p>}
                    </div>
                    <button type="button" className="btn-icon h-9 w-9 shrink-0" aria-label="Remove link"
                      onClick={() => setForm((f) => ({ ...f, links: f.links.filter((_, j) => j !== i) }))}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
                {form.links.length < 15 && (
                  <button type="button" className="btn-ghost btn-sm"
                    onClick={() => setForm((f) => ({ ...f, links: [...f.links, { type: f.links.some((l) => l.type === "GITHUB") ? "PORTFOLIO" : "GITHUB", url: "" }] }))}>
                    <Plus size={13} /> Add link
                  </button>
                )}
              </div>
            </Group>

            <Group title="Resume">
              <input ref={fileRef} type="file" accept={RESUME_ACCEPT} className="hidden" onChange={(e) => pickFile(e.target.files?.[0])} />
              <button type="button" onClick={() => fileRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e: DragEvent) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0]); }}
                className={`block w-full rounded-xl border-2 border-dashed p-5 text-center transition-colors ${dragging || resume ? "border-brand-500 bg-brand-500/[0.04]" : "border-line bg-canvas hover:border-brand-500/50"}`}>
                <FileUp className="mx-auto mb-1.5 h-6 w-6 text-accent" />
                {resume ? (
                  <span className="block text-[13px]">
                    <span className="block truncate font-medium text-fg">{resume.name}</span>
                    <span className="block text-xs text-fg-subtle">{Math.max(1, Math.round(resume.size / 1024))} KB · click to choose another</span>
                  </span>
                ) : (
                  <span className="block text-[13px] text-fg-subtle">
                    {editing && candidate?.resume ? <>Current: <span className="font-medium text-fg">{candidate.resume.file_name}</span>. Drop a file to replace it.</> : <><span className="font-medium text-accent">Choose a file</span> or drag it here · PDF or Word, up to {MAX_RESUME_MB} MB</>}
                  </span>
                )}
              </button>
              {resume && (
                <button type="button" className="btn-ghost btn-sm" onClick={() => setResume(null)}><X size={13} /> Remove file</button>
              )}
              {fileError && <p className="text-xs font-medium text-danger" role="alert">{fileError}</p>}
            </Group>

            <Group title="Summary">
              <textarea className="input" rows={3} maxLength={10000} aria-label="Summary"
                placeholder="Highlights, interview context, anything the hiring team should know."
                value={form.summary} onChange={(e) => set("summary")(e.target.value)} />
            </Group>
          </>
        )}

        {!editing && (
          <Group title="Pipeline">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="cf-stage">Starting stage</label>
                <select id="cf-stage" className="input" value={stageId} onChange={(e) => setStageId(e.target.value)}>
                  <option value="">{entryStages[0]?.name ?? "First stage"} (default)</option>
                  {entryStages.slice(1).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="label" htmlFor="cf-note">Note for the hiring team <span className="font-normal text-fg-subtle">(optional)</span></label>
              <textarea id="cf-note" className="input" rows={2} maxLength={5000} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
          </Group>
        )}
      </form>
    </Sheet>
  );
}
