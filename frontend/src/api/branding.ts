import { api, API_BASE_URL, type Versioned } from "./client";
import type { CompanyDetails } from "./org";

export type AssetKind = "LOGO" | "SIGNATURE";
/** Where a resolved value comes from: the company's own, the group default, or built in. */
export type BrandSource = "COMPANY" | "GROUP" | "DEFAULT";

export interface BrandAsset {
  id: string;
  kind: AssetKind;
  file_name: string;
  width: number;
  height: number;
  byte_size: number;
  uploaded_at: string;
}

/** Every field: a value, or null to inherit (from the group, or the built-in default). */
export interface BrandProfileInput {
  logo_asset_id: string | null;
  primary_color: string | null;
  accent_color: string | null;
  footer_text: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  website: string | null;
}

export interface BrandProfile extends Omit<BrandProfileInput, "logo_asset_id"> {
  id: string;
  /** null: the group default. */
  legal_entity_id: string | null;
  logo: BrandAsset | null;
  version: number;
  recorded_at: string;
}

export interface ResolvedBranding {
  legal_entity_id: string | null;
  company: CompanyDetails & { name: string };
  fields: Record<keyof BrandProfileInput, { value: string | null; source: BrandSource }>;
  logo: BrandAsset | null;
  color_check: { text_color: string; adjusted: boolean; contrast: number };
}

export interface Signatory {
  id: string;
  /** null: may sign for any company. */
  legal_entity_id: string | null;
  name: string;
  designation: string | null;
  signature: BrandAsset | null;
  version: number;
}

export interface SignatoryInput {
  legal_entity_id: string | null;
  name: string;
  designation: string | null;
  signature_asset_id: string | null;
}

export const brandingApi = {
  profiles: () => api.get<BrandProfile[]>("/v1/branding/profiles"),
  saveGroup: (body: BrandProfileInput & Versioned) => api.put<BrandProfile>("/v1/branding/profiles/group", body),
  saveCompany: (companyId: string, body: BrandProfileInput & Versioned) =>
    api.put<BrandProfile>(`/v1/branding/profiles/companies/${companyId}`, body),
  resetCompany: (companyId: string) => api.delete(`/v1/branding/profiles/companies/${companyId}`),
  resolved: (companyId?: string | null) =>
    api.get<ResolvedBranding>(`/v1/branding/resolved${companyId ? `?legal_entity_id=${encodeURIComponent(companyId)}` : ""}`),

  upload: (kind: AssetKind, file: File) => {
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", file);
    return api.postForm<BrandAsset>("/v1/branding/assets", form);
  },
  /** The image as a blob (the API needs the session cookie, so an <img src> can't load it directly). */
  async image(assetId: string): Promise<Blob> {
    const res = await fetch(`${API_BASE_URL}/v1/branding/assets/${encodeURIComponent(assetId)}/image`, {
      headers: { "X-HRMS-Session": "cookie" }, credentials: "include", signal: AbortSignal.timeout(20_000),
    });
    if (!res.ok) throw new Error("Couldn’t load the image");
    return res.blob();
  },

  signatories: () => api.get<Signatory[]>("/v1/branding/signatories"),
  createSignatory: (body: SignatoryInput) => api.post<Signatory>("/v1/branding/signatories", body),
  updateSignatory: (id: string, body: SignatoryInput & Versioned) => api.patch<Signatory>(`/v1/branding/signatories/${id}`, body),
  archiveSignatory: (id: string) => api.post<void>(`/v1/branding/signatories/${id}/archive`, {}),
};
