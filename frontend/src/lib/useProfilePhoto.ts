import { useEffect, useState } from "react";
import { getAuthToken } from "../api/client";
import { kycApi } from "../api/kyc";
import { createPhotoCache } from "./photoCache";

// People whose photo just changed: their next request must not be answered from the browser cache.
const fresh = new Set<string>();

const cache = createPhotoCache({
  load: (id) => kycApi.profilePhoto(id, "small", fresh.delete(id)),
  createUrl: (blob) => URL.createObjectURL(blob),
  revokeUrl: (url) => URL.revokeObjectURL(url),
});

// A new sign-in must never be shown the previous person's cached photos.
let session = getAuthToken();
function photos() {
  const token = getAuthToken();
  if (token !== session) {
    cache.clear();
    session = token;
  }
  return cache;
}

const listeners = new Set<(id: string) => void>();

/** After a photo is set or removed: forget the old one and refresh every avatar showing them. */
export function profilePhotoChanged(employmentId: string) {
  fresh.add(employmentId);
  photos().invalidate(employmentId);
  listeners.forEach((listener) => listener(employmentId));
}

/** The address of a person's profile photo, or null (show initials) until/unless there is one. */
export function useProfilePhoto(employmentId?: string | null): string | null {
  const [url, setUrl] = useState<string | null>(() => (employmentId ? photos().peek(employmentId) : null));
  useEffect(() => {
    if (!employmentId) { setUrl(null); return; }
    let live = true;
    const known = photos().peek(employmentId);
    if (known) setUrl(known);
    const load = () => photos().get(employmentId).then((next) => { if (live) setUrl(next); });
    load();
    const refresh = (changed: string) => { if (changed === employmentId) { setUrl(null); load(); } };
    listeners.add(refresh);
    return () => { live = false; listeners.delete(refresh); };
  }, [employmentId]);
  return employmentId ? url : null;
}
