import { useEffect, useState } from "react";
import { brandingApi } from "../../api/branding";

/** The built-in branding when neither the company nor the group sets a value (as the API). */
export const DEFAULT_PRIMARY = "#0F766E";
export const DEFAULT_ACCENT = "#134E4A";
const WHITE = "#FFFFFF";

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The colour text prints in on white: as given if readable (4.5:1), else darkened (as the API). */
export function readableOnWhite(hex: string): string {
  let color = hex.toUpperCase();
  while (contrast(color, WHITE) < 4.5) {
    color = "#" + [1, 3, 5].map((i) => Math.floor(parseInt(color.slice(i, i + 2), 16) * 0.9).toString(16).padStart(2, "0").toUpperCase()).join("");
  }
  return color;
}

/** White or near-black, whichever reads better on this colour. */
export function textOn(hex: string): string {
  return contrast(hex, WHITE) >= contrast(hex, "#111827") ? WHITE : "#111827";
}

export const isHexColor = (value: string) => /^#[0-9A-Fa-f]{6}$/.test(value);

/** An uploaded logo or signature as an object URL, revoked when no longer shown. */
export function useBrandImage(assetId: string | null | undefined): string | null {
  const [loaded, setLoaded] = useState<{ id: string; url: string } | null>(null);
  useEffect(() => {
    if (!assetId) return;
    let objectUrl: string | null = null;
    let live = true;
    brandingApi.image(assetId)
      .then((blob) => { if (!live) return; objectUrl = URL.createObjectURL(blob); setLoaded({ id: assetId, url: objectUrl }); })
      .catch(() => undefined);  // no picture: the caller shows its placeholder
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [assetId]);
  return assetId && loaded?.id === assetId ? loaded.url : null;
}
