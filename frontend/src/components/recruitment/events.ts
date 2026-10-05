import {
  ArrowRight, CheckCircle2, FilePlus2, FileText, MessageSquare, Pencil, PlayCircle, Send, Star, Undo2, UserPlus, UserRoundCheck, XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { RecruitmentEvent } from "../../api/recruitment";
import { OPENING_STATUS } from "./meta";

const s = (v: unknown) => (typeof v === "string" ? v : v === null || v === undefined ? "" : String(v));

export function describeEvent(e: RecruitmentEvent): { icon: LucideIcon; tone: string; text: string; body?: string } {
  const d = e.details ?? {};
  const who = e.candidate_name ? ` ${e.candidate_name}` : "";
  const statusLabel = (v: unknown) => OPENING_STATUS[s(v) as keyof typeof OPENING_STATUS]?.label ?? s(v);
  switch (e.action) {
    case "CREATED": return { icon: FilePlus2, tone: "text-fg-muted", text: `created the opening ${s(d.code)}` };
    case "UPDATED": return { icon: Pencil, tone: "text-fg-muted", text: "edited the opening" };
    case "SUBMITTED": return {
      icon: Send, tone: "text-info",
      text: d.mode === "FLOW" ? `submitted it for approval (${(d.stages as string[] | undefined)?.join(" → ") ?? "approval flow"})` : "submitted it for HR approval",
    };
    case "APPROVAL_STEP": return { icon: CheckCircle2, tone: "text-success", text: `approved at ${s(d.stage) || "a stage"}`, body: s(d.comments) || undefined };
    case "APPROVED": return {
      icon: CheckCircle2, tone: "text-success",
      text: d.mode === "AUTO" ? "published the opening" : `approved the opening${d.stage ? ` (${s(d.stage)})` : ""}`,
      body: s(d.comments) || undefined,
    };
    case "REJECTED": return { icon: XCircle, tone: "text-danger", text: `rejected the opening${d.stage ? ` at ${s(d.stage)}` : ""}`, body: s(d.comments) || undefined };
    case "WITHDRAWN": return { icon: Undo2, tone: "text-fg-muted", text: "withdrew it from approval" };
    case "STATUS_CHANGED": return {
      icon: PlayCircle, tone: "text-fg-muted",
      text: `changed the status from ${statusLabel(d.from)} to ${statusLabel(d.to)}`, body: s(d.reason) || undefined,
    };
    case "APPLICATION_ADDED": return { icon: UserPlus, tone: "text-accent", text: `added${who || " a candidate"} at ${s(d.stage)}` };
    case "STAGE_CHANGED": return {
      icon: ArrowRight, tone: d.category === "REJECTED" || d.category === "WITHDRAWN" ? "text-danger" : d.category === "HIRED" ? "text-success" : "text-accent",
      text: `moved${who} from ${s(d.from)} to ${s(d.to)}`, body: s(d.reason) || undefined,
    };
    case "NOTE": return { icon: MessageSquare, tone: "text-fg-muted", text: `left feedback${who ? ` on${who}` : ""}`, body: s(d.body) };
    case "RATED": return { icon: Star, tone: "text-warning", text: d.rating ? `rated${who} ${s(d.rating)}/5` : `cleared${who}’s rating` };
    case "HIRED": return { icon: UserRoundCheck, tone: "text-success", text: `created the employee record for${who || " the candidate"}` };
    case "RESUME_UPLOADED": return { icon: FileText, tone: "text-fg-muted", text: `uploaded a resume${who ? ` for${who}` : ""}`, body: s(d.file_name) || undefined };
    case "RESUME_REMOVED": return { icon: FileText, tone: "text-fg-muted", text: `removed${who}’s resume` };
    case "CANDIDATE_UPDATED": return { icon: Pencil, tone: "text-fg-muted", text: `updated${who}’s profile` };
    default: return { icon: FileText, tone: "text-fg-muted", text: e.action.toLowerCase().replace(/_/g, " ") };
  }
}

