import { useId, useState } from "react";
import type { KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Award, Cake, X } from "../icons/ThemeIcons";
import { dashboardApi } from "../../api/dashboard";
import type { CelebrationPerson } from "../../api/dashboard";
import { useAuth } from "../../context/AuthContext";
import { acknowledgeCelebrations, celebrationStorageKey, celebrationsAcknowledged } from "../../lib/celebrations";
import { Avatar } from "../ui/Avatar";
import { Dialog } from "../ui/Overlay";

function keepFocusInside(event: KeyboardEvent<HTMLDivElement>) {
  if (event.key !== "Tab") return;
  const controls = [...event.currentTarget.querySelectorAll<HTMLElement>("button:not([disabled]), a[href], [tabindex='0']")];
  const first = controls[0], last = controls.at(-1);
  if (!first || !last) return;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function Celebrant({ person, detail }: { person: CelebrationPerson; detail: string }) {
  return <li className="flex items-center gap-3 py-3">
    <Avatar name={person.name} size="md" className="!text-fg" />
    <div className="min-w-0 flex-1">
      <p className="break-words text-[13px] font-medium text-fg">{person.name}
        {person.is_self && <span className="ml-2 text-xs font-normal text-fg-muted">(You)</span>}
      </p>
      <p className="mt-0.5 text-xs text-fg-muted">{detail}</p>
    </div>
  </li>;
}

/** A lightweight, nonblocking welcome for the current company's celebrations. */
export function LoginCelebration() {
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState("");
  const headingId = useId(), descriptionId = useId();
  const identity = user?.employmentId
    ? celebrationStorageKey(user.tenantId, user.id, user.employmentId) : "";
  const { data } = useQuery({
    queryKey: ["login-celebrations", user?.tenantId, user?.id, user?.employmentId],
    queryFn: dashboardApi.celebrations,
    enabled: !!identity,
    staleTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  });

  if (!user || !identity || !data) return null;
  const birthday = data.personal.birthday;
  const years = data.personal.anniversary_years;
  const anniversary = years !== null && years > 0;
  const hasCelebrations = birthday || anniversary || data.birthdays.length > 0 || data.anniversaries.length > 0;
  const occurrence = `${identity}:${data.date}`;
  const open = hasCelebrations && dismissed !== occurrence && !celebrationsAcknowledged(identity, data.date);
  const close = () => {
    acknowledgeCelebrations(identity, data.date);
    setDismissed(occurrence);
  };
  const title = birthday && anniversary ? `Two reasons to celebrate, ${user.name}!`
    : birthday ? `Happy birthday, ${user.name}!`
    : anniversary ? `Happy work anniversary, ${user.name}!`
    : "Celebrating today";
  const description = birthday && anniversary
    ? `Happy birthday and congratulations on ${years} ${years === 1 ? "year" : "years"} with us. Wishing you a wonderful day and many more milestones!`
    : birthday ? "Wishing you a wonderful birthday and a great year ahead!"
    : anniversary ? `Thank you for ${years} ${years === 1 ? "year" : "years"} of dedication. Here’s to your next milestone!`
    : "Join us in wishing your colleagues a wonderful day.";
  const Icon = anniversary && !birthday ? Award : Cake;

  return <Dialog open={open} onClose={close} labelledBy={headingId} describedBy={descriptionId}
    className="max-w-lg max-h-[calc(88dvh-2rem)]">
    <div className="flex max-h-[calc(88dvh-2rem)] flex-col" onKeyDown={keepFocusInside}>
      <div role="region" aria-label="Today's celebrations" tabIndex={0}
        className="min-h-0 overflow-y-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:-outline-offset-2">
        <header className="relative border-b border-line bg-muted/50 px-6 py-6">
          <button type="button" className="btn-icon absolute right-3 top-3" onClick={close} aria-label="Close celebrations"><X size={18} /></button>
          <div className="celebration-mark mb-4 grid h-12 w-12 place-items-center rounded-xl bg-brand-500/10 text-accent"><Icon size={26} aria-hidden /></div>
          <p className="mb-2 text-xs font-medium text-fg-muted">{format(parseISO(data.date), "EEEE, d MMMM")}</p>
          <h2 id={headingId} className="pr-2 text-xl font-semibold leading-snug tracking-tight text-fg">{title}</h2>
          <p id={descriptionId} className="mt-2 text-[13px] leading-relaxed text-fg-muted">{description}</p>
        </header>
        {(data.birthdays.length > 0 || data.anniversaries.length > 0) && <div className="space-y-5 px-6 py-4">
          {data.birthdays.length > 0 && <section aria-labelledby={`${headingId}-birthdays`}>
            <h3 id={`${headingId}-birthdays`} className="flex items-center gap-2 text-sm font-semibold text-fg"><Cake size={16} className="text-accent" aria-hidden />Birthdays today</h3>
            <ul className="mt-1 divide-y divide-line">{data.birthdays.map(person => <Celebrant key={person.id} person={person} detail="Happy birthday!" />)}</ul>
          </section>}
          {data.anniversaries.length > 0 && <section aria-labelledby={`${headingId}-anniversaries`}>
            <h3 id={`${headingId}-anniversaries`} className="flex items-center gap-2 text-sm font-semibold text-fg"><Award size={16} className="text-accent" aria-hidden />Work anniversaries today</h3>
            <ul className="mt-1 divide-y divide-line">{data.anniversaries.map(person => <Celebrant key={person.id} person={person}
              detail={`${person.years} ${person.years === 1 ? "year" : "years"} with ${person.company}`} />)}</ul>
          </section>}
        </div>}
      </div>
      <footer className="flex shrink-0 justify-end border-t border-line px-6 py-4">
        <button type="button" className="btn-secondary w-full sm:w-auto" onClick={close} data-autofocus>Continue to work</button>
      </footer>
    </div>
  </Dialog>;
}
