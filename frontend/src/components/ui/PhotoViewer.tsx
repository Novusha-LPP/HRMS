import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { kycApi } from "../../api/kyc";
import { Dialog } from "./Overlay";

/** The whole profile picture, larger. Fetched only when opened, released when closed. */
export function PhotoViewer({ open, onClose, employmentId, name }: {
  open: boolean;
  onClose: () => void;
  employmentId: string;
  name: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    let live = true;
    let made: string | null = null;
    setUrl(null);
    setFailed(false);
    kycApi.profilePhoto(employmentId, "large")
      .then((blob) => {
        if (!live) return;
        if (!blob) { setFailed(true); return; }
        made = URL.createObjectURL(blob);
        setUrl(made);
      })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [open, employmentId]);

  return (
    <Dialog open={open} onClose={onClose} className="max-w-xl" ariaLabel={`Photo of ${name}`}>
      <div className="relative flex min-h-48 items-center justify-center bg-muted/40 p-3">
        <button
          type="button"
          data-autofocus
          onClick={onClose}
          aria-label="Close photo"
          className="btn-ghost btn-sm absolute right-2 top-2 z-10 bg-surface/80"
        >
          <X size={16} />
        </button>
        {url ? (
          <img src={url} alt={`Photo of ${name}`} className="max-h-[70dvh] w-auto max-w-full rounded-lg object-contain" />
        ) : failed ? (
          <p className="p-8 text-sm text-fg-muted">This photo is not available.</p>
        ) : (
          <div className="skeleton h-48 w-48 rounded-lg" aria-label="Loading photo" />
        )}
      </div>
    </Dialog>
  );
}
