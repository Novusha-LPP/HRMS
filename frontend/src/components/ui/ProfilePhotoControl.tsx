import { useRef, useState } from "react";
import { kycApi } from "../../api/kyc";
import { profilePhotoChanged, useProfilePhoto } from "../../lib/useProfilePhoto";
import { errorMessage, useToast } from "./Toast";

const MAX_BYTES = 8 * 1024 * 1024;
const TYPES = ["image/png", "image/jpeg"];

/** Change or remove someone's profile photo. The server decides who may; this only asks. */
export function ProfilePhotoControl({ employmentId, className = "" }: {
  employmentId: string;
  className?: string;
}) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const hasPhoto = !!useProfilePhoto(employmentId);

  async function run(action: () => Promise<unknown>, done: string, failed: string) {
    setBusy(true);
    try {
      await action();
      profilePhotoChanged(employmentId);
      toast.success(done);
    } catch (error) {
      toast.error(failed, errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function choose(file: File | undefined) {
    if (input.current) input.current.value = "";
    if (!file) return;
    if (!TYPES.includes(file.type)) { toast.error("Couldn't use that file", "Choose a PNG or JPEG image."); return; }
    if (file.size > MAX_BYTES) { toast.error("That photo is too large", "Choose an image under 8 MB."); return; }
    void run(() => kycApi.setProfilePhoto(employmentId, file), "Photo updated", "Couldn't update the photo");
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg"
        className="sr-only"
        aria-label="Choose a profile photo"
        onChange={(event) => choose(event.target.files?.[0])}
      />
      <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => input.current?.click()}>
        {hasPhoto ? "Change photo" : "Add photo"}
      </button>
      {hasPhoto && (
        <button
          type="button"
          className="btn-ghost btn-sm text-danger"
          disabled={busy}
          onClick={() => void run(() => kycApi.removeProfilePhoto(employmentId), "Photo removed", "Couldn't remove the photo")}
        >
          Remove
        </button>
      )}
    </div>
  );
}
