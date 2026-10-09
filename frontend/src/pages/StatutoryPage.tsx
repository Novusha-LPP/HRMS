import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Landmark, ShieldPlus } from "lucide-react";
import { kycApi } from "../api/kyc";
import { PageHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Feedback";
import { useAuth } from "../context/AuthContext";
import { EMPLOYEE_LINKS, EMPLOYER_LINKS, LINKS_SOURCE, linkHost } from "../lib/statutoryLinks";
import type { StatutoryGroup } from "../lib/statutoryLinks";

/** The employer side is for the people who file PF and ESIC: HR and Accounts (dashboard.hr), not line managers. */
const EMPLOYER_PERMISSIONS = ["*", "dashboard.hr"];

export function StatutoryPage() {
  const { user } = useAuth();
  const showEmployer = !!user?.permissions.some((p) => EMPLOYER_PERMISSIONS.includes(p));
  const hasEmployment = !!user?.employmentId;

  return (
    <>
      <PageHeader
        title="PF & ESIC"
        description="Official government portals for Provident Fund and Employees' State Insurance. They open on the government site in a new tab; this app never asks for your portal password."
      />
      <div className="space-y-8">
        {hasEmployment && <MyNumbers />}
        <LinkSection
          title="For employees"
          description="Check your PF balance, activate your UAN, and see your ESI benefits."
          groups={EMPLOYEE_LINKS}
        />
        {showEmployer && (
          <LinkSection
            title="For employer and HR"
            description="Where HR and Accounts file returns, pay challans and register employees. Sign in with the establishment's own login."
            groups={EMPLOYER_LINKS}
          />
        )}
        <p className="text-xs text-fg-subtle">
          Links as listed in the {LINKS_SOURCE}. Government sites change their addresses from time to time; tell HR if one stops working.
        </p>
      </div>
    </>
  );
}

function MyNumbers() {
  const kyc = useQuery({ queryKey: ["kyc", "me"], queryFn: () => kycApi.getMyKyc(), retry: false });
  if (kyc.isPending) return <Skeleton className="h-24 rounded-xl" />;
  if (kyc.isError) return null;
  const rows: [string, string | null][] = [
    ["UAN", kyc.data.uan_number],
    ["PF number", kyc.data.pf_number],
    ["ESI (IP) number", kyc.data.esi_number],
  ];
  const missing = rows.filter(([, v]) => !v).length;

  return (
    <section>
      <p className="eyebrow mb-2">Your numbers</p>
      <div className="card p-4">
        <dl className="grid gap-3 sm:grid-cols-3">
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs text-fg-subtle">{label}</dt>
              <dd className={`mt-0.5 font-mono text-sm ${value ? "font-medium text-fg" : "text-fg-subtle"}`}>{value ?? "Not on file"}</dd>
            </div>
          ))}
        </dl>
        {missing > 0 && (
          <p className="mt-3 text-xs text-fg-muted">
            Missing numbers can be added in <Link to="/profile?tab=kyc" className="font-medium text-accent hover:underline">Profile → KYC</Link>, or ask HR.
          </p>
        )}
      </div>
    </section>
  );
}

function LinkSection({ title, description, groups }: { title: string; description: string; groups: StatutoryGroup[] }) {
  return (
    <section>
      <h2 className="text-[15px] font-semibold text-fg">{title}</h2>
      <p className="mb-3 text-sm text-fg-muted">{description}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map((g) => {
          const Icon = g.scheme === "EPFO" ? Landmark : ShieldPlus;
          return (
            <div key={g.scheme} className="card overflow-hidden">
              <div className="flex items-center gap-2 border-b border-line px-4 py-3">
                <Icon size={16} className="text-accent" />
                <p className="text-sm font-semibold text-fg">{g.heading}</p>
              </div>
              <ul className="divide-y divide-line">
                {g.links.map((l) => (
                  <li key={l.url}>
                    <a href={l.url} target="_blank" rel="noopener noreferrer"
                      className="group flex items-start gap-3 px-4 py-3 transition-colors hover:bg-muted/50">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-fg group-hover:text-accent">{l.title}</p>
                        <p className="text-xs text-fg-muted">{l.purpose}</p>
                        <p className="mt-0.5 truncate font-mono text-[11px] text-fg-subtle">{linkHost(l.url)}</p>
                      </div>
                      <ExternalLink size={14} className="mt-0.5 shrink-0 text-fg-subtle group-hover:text-accent" />
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}
