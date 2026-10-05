import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";
import { Dialog } from "../ui/Overlay";
import { Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { recruitmentApi } from "../../api/recruitment";
import type { Candidate } from "../../api/recruitment";
import { downloadResume } from "./resume";

/** PDF resumes open inline; Word documents can only be downloaded. */
export function ResumeViewer({ candidate, onClose }: { candidate: Candidate; onClose: () => void }) {
  const toast = useToast();
  const [state, setState] = useState<{ url?: string; error?: string }>({});
  const isPdf = candidate.resume?.mime_type === "application/pdf";

  useEffect(() => {
    if (!isPdf) return;
    let active = true;
    let objectUrl: string | undefined;
    recruitmentApi.fetchResume(candidate.id, true).then(({ blob, url }) => {
      URL.revokeObjectURL(url);
      if (blob.type !== "application/pdf") throw new Error("Not a PDF");
      objectUrl = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
      if (active) setState({ url: objectUrl });
      else URL.revokeObjectURL(objectUrl);
    }).catch(() => { if (active) setState({ error: "Couldn’t load the resume." }); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [candidate.id, isPdf]);

  const download = () => downloadResume(candidate).catch((e) => toast.error("Download failed", errorMessage(e)));

  return (
    <Dialog open onClose={onClose} className="max-w-4xl">
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <h3 className="truncate text-[15px] font-semibold text-fg">{candidate.full_name} — resume</h3>
          <p className="truncate text-xs text-fg-subtle">{candidate.resume?.file_name}</p>
        </div>
        <button type="button" className="btn-icon shrink-0" aria-label="Close" onClick={onClose}><X size={16} /></button>
      </div>
      <div className="grid h-[70vh] place-items-center bg-canvas p-3">
        {!isPdf ? (
          <div className="max-w-sm text-center text-[13px] text-fg-muted">
            Word documents can’t be previewed in the browser.
            <div className="mt-3"><button type="button" className="btn-primary btn-sm" onClick={download}><Download size={13} /> Download</button></div>
          </div>
        ) : state.error ? (
          <p className="text-[13px] text-danger" role="alert">{state.error}</p>
        ) : !state.url ? (
          <Skeleton className="h-full w-full rounded-lg" />
        ) : (
          <object data={state.url} type="application/pdf" aria-label="Resume" className="h-full w-full rounded-lg bg-surface">
            <div className="grid h-full place-items-center p-6 text-center text-[13px] text-fg-muted">
              This browser can’t show PDFs inline. Use Download.
            </div>
          </object>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-line bg-panel px-5 py-3">
        <button type="button" className="btn-secondary btn-sm" onClick={download}><Download size={13} /> Download</button>
        <button type="button" className="btn-ghost btn-sm" onClick={onClose}>Close</button>
      </div>
    </Dialog>
  );
}
