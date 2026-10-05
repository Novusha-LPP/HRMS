import { recruitmentApi } from "../../api/recruitment";
import type { Candidate } from "../../api/recruitment";

export async function downloadResume(candidate: Candidate) {
  const { url } = await recruitmentApi.fetchResume(candidate.id, false);
  const link = document.createElement("a");
  link.href = url;
  link.download = candidate.resume?.file_name ?? "resume";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
