import { useState } from "react";
import { CircleHelp } from "lucide-react";
import { Sheet } from "./Overlay";
import { usageHelp } from "../../lib/usageHelp";
import type { UsageHelpTopic } from "../../lib/usageHelp";

export function UsageHelpButton({ topic }: { topic: UsageHelpTopic }) {
  const [open, setOpen] = useState(false);
  const help = usageHelp[topic];
  return <>
    <button type="button" className="btn-secondary btn-sm" title={help.title}
      aria-label={`Help: ${help.title}`} aria-haspopup="dialog" onClick={() => setOpen(true)}>
      <CircleHelp size={16} /> Help
    </button>
    <Sheet open={open} onClose={() => setOpen(false)} title={help.title} description={help.introduction}
      className="max-w-lg" footer={<button type="button" className="btn-primary" onClick={() => setOpen(false)}>Got it</button>}>
      <ol className="space-y-5">
        {help.steps.map((step, index) => <li className="flex gap-3" key={step.title}>
          <span aria-hidden="true" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-500/10 text-sm font-semibold text-accent">{index + 1}</span>
          <div><h3 className="font-semibold text-sm">{step.title}</h3><p className="mt-1 text-sm text-fg-muted">{step.description}</p></div>
        </li>)}
      </ol>
      <p className="mt-6 rounded-xl border border-line bg-surface-raised p-4 text-sm text-fg-muted">{help.note}</p>
    </Sheet>
  </>;
}
