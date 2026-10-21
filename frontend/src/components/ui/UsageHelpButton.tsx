import { useState } from "react";
import { CircleHelp } from "lucide-react";
import { Sheet } from "./Overlay";
import { usageHelp } from "../../lib/usageHelp";
import type { UsageHelpTopic } from "../../lib/usageHelp";

export function UsageHelpButton({ topic, iconOnly = false, label = "Help" }: { topic: UsageHelpTopic; iconOnly?: boolean; label?: string }) {
  const [open, setOpen] = useState(false);
  const help = usageHelp[topic];
  return <>
    <button type="button" className={iconOnly ? "btn-icon shrink-0" : "btn-secondary btn-sm"} title={help.title}
      aria-label={`Help: ${help.title}`} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
      <CircleHelp size={16} aria-hidden="true" />{!iconOnly && ` ${label}`}
    </button>
    <Sheet open={open} onClose={() => setOpen(false)} title={help.title} description={help.introduction}
      className="max-w-lg" footer={<button type="button" className="btn-primary" onClick={() => setOpen(false)}>Got it</button>}>
      <ol className="space-y-5">
        {help.steps.map((step, index) => <li className="flex gap-3" key={step.title}>
          <span aria-hidden="true" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-500/10 text-sm font-semibold text-accent">{index + 1}</span>
          <div><h3 className="font-semibold text-sm">{step.title}</h3><p className="mt-1 text-sm text-fg-muted">{step.description}</p></div>
        </li>)}
      </ol>
      {help.calculation && <section className="mt-7" aria-label={help.calculation.title}>
        <h3 className="text-sm font-semibold">{help.calculation.title}</h3>
        <dl className="mt-3 space-y-3">
          {help.calculation.items.map((item) => <div key={item.name}>
            <dt className="text-[13px] font-semibold">{item.name}</dt>
            <dd className="mt-0.5 text-sm text-fg-muted">{item.text}</dd>
          </div>)}
        </dl>
      </section>}
      {help.examples?.map((example) => <section key={example.title} className="mt-7" aria-label={example.title}>
        <h3 className="text-sm font-semibold">{example.title}</h3>
        <p className="mt-1 text-sm text-fg-muted">{example.intro}</p>
        <table className="mt-3 w-full overflow-hidden rounded-xl border border-line text-sm">
          <tbody className="divide-y divide-line">
            {example.rows.map(([name, value]) => <tr key={name}>
              <td className="px-3 py-2 text-fg-muted">{name}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums">{value}</td>
            </tr>)}
          </tbody>
        </table>
      </section>)}
      <p className="mt-6 rounded-xl border border-line bg-surface-raised p-4 text-sm text-fg-muted">{help.note}</p>
    </Sheet>
  </>;
}
