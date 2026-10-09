/**
 * Official PF and ESIC destinations from the requirements document (v2.0, §20 and §44),
 * split into what employees use and what the employer / HR team uses.
 *
 * Government portals move. These become pack data with a "last verified" date that HR can
 * edit in Settings (enterprise plan M14); until then they live here.
 */

export interface StatutoryLink {
  title: string;
  purpose: string;
  url: string;
}

export interface StatutoryGroup {
  scheme: "EPFO" | "ESIC";
  heading: string;
  links: StatutoryLink[];
}

export const LINKS_SOURCE = "Requirements document v2.0, 17 Sep 2026";

export const EMPLOYEE_LINKS: StatutoryGroup[] = [
  {
    scheme: "EPFO",
    heading: "Provident Fund (EPFO)",
    links: [
      {
        title: "Member portal (UAN)",
        purpose: "Activate your UAN, update KYC and nominee, transfer or withdraw PF.",
        url: "https://unifiedportal-mem.epfindia.gov.in/memberinterface/",
      },
      {
        title: "Member passbook",
        purpose: "See your PF contributions and balance.",
        url: "https://passbook.epfindia.gov.in/MemberPassBook/login",
      },
      {
        title: "Employee services",
        purpose: "EPFO's guides and services for members.",
        url: "https://www.epfindia.gov.in/site_en/For_Employees.php",
      },
    ],
  },
  {
    scheme: "ESIC",
    heading: "Employees' State Insurance (ESIC)",
    links: [
      {
        title: "ESIC official website",
        purpose: "Your ESI benefits, dispensaries and e-Pehchan card.",
        url: "https://www.esic.gov.in/",
      },
    ],
  },
];

export const EMPLOYER_LINKS: StatutoryGroup[] = [
  {
    scheme: "EPFO",
    heading: "Provident Fund (EPFO)",
    links: [
      {
        title: "Employer portal",
        purpose: "Sign in as the establishment: ECR, member registration, KYC approval.",
        url: "https://unifiedportal-emp.epfindia.gov.in/epfo/",
      },
      {
        title: "Employer services",
        purpose: "EPFO's circulars, guides and services for employers.",
        url: "https://www.epfindia.gov.in/site_en/For_Employers.php",
      },
      {
        title: "Public / TRRN portal",
        purpose: "Check a challan's payment status by its TRRN.",
        url: "https://unifiedportal-emp.epfindia.gov.in/publicPortal/",
      },
    ],
  },
  {
    scheme: "ESIC",
    heading: "Employees' State Insurance (ESIC)",
    links: [
      {
        title: "Employer services",
        purpose: "Sign in as the employer: registration, monthly contribution, challans.",
        url: "https://www.esic.in/",
      },
      {
        title: "ESIC official website",
        purpose: "Notifications, rates and circulars.",
        url: "https://www.esic.gov.in/",
      },
    ],
  },
];

/** The host shown under each link, so people can see where they are going. */
export function linkHost(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
