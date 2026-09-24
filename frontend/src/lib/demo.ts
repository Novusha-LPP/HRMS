/**
 * Sample data for widgets that have no backing API yet, and for when the API
 * is unreachable. Cards that render this show a "Sample" tag.
 */

export type EmploymentType = "Permanent" | "Contract" | "Trainee";

export interface EmployeeRow {
  id: string;
  employeeNumber: string;
  name: string;
  email: string;
  department: string;
  designation: string;
  location: string;
  hireDate: string;
  type: EmploymentType;
  state: "ACTIVE" | "PROBATION" | "ON_NOTICE" | "INACTIVE";
  manager: string;
}

const FIRST = [
  "Rahul", "Neha", "Vikram", "Anjali", "Sandeep", "Pooja", "Amit", "Divya", "Rohan", "Sonali",
  "Karan", "Meera", "Arjun", "Priya", "Nikhil", "Kavya", "Siddharth", "Ishita", "Manish", "Tanvi",
  "Aditya", "Riya", "Varun", "Shreya",
];
const LAST = [
  "Sharma", "Patil", "Singh", "Mehta", "Rao", "Verma", "Kumar", "Nair",
  "Das", "Gupta", "Iyer", "Joshi", "Kulkarni", "Reddy", "Bose", "Menon",
];
export const DEPARTMENTS = ["Export", "Import", "Operations", "Accounts", "Sales", "HR", "Admin", "IT", "Finance", "Logistics"];
const DESIGNATIONS: Record<string, string[]> = {
  Export: ["Export Executive", "Documentation Lead", "Export Manager"],
  Import: ["Import Executive", "Customs Coordinator"],
  Operations: ["Operations Executive", "Supervisor", "Operations Manager"],
  Accounts: ["Accounts Assistant", "Senior Accountant"],
  Sales: ["Sales Executive", "Key Account Manager", "Regional Sales Head"],
  HR: ["HR Executive", "HR Business Partner"],
  Admin: ["Admin Executive", "Facilities Coordinator"],
  IT: ["Software Engineer", "IT Support Engineer", "Systems Admin"],
  Finance: ["Financial Analyst", "Finance Manager"],
  Logistics: ["Logistics Coordinator", "Fleet Supervisor"],
};
const LOCATIONS = ["Mumbai", "Pune", "Chennai", "Delhi NCR", "Ahmedabad"];

function hireDateFor(i: number) {
  if (i < 6) return `2026-0${9 - Math.floor(i / 3)}-${String(18 - i * 2).padStart(2, "0")}`;
  const year = 2019 + (i % 7);
  const month = ((i * 5) % 12) + 1;
  const day = ((i * 7) % 27) + 1;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export const DEMO_EMPLOYEES: EmployeeRow[] = Array.from({ length: 48 }, (_, i) => {
  const name = `${FIRST[i % FIRST.length]} ${LAST[(i * 7 + Math.floor(i / FIRST.length)) % LAST.length]}`;
  const department = DEPARTMENTS[(i * 3) % DEPARTMENTS.length];
  const desgs = DESIGNATIONS[department];
  const hireDate = hireDateFor(i);
  const state: EmployeeRow["state"] =
    hireDate.startsWith("2026") ? "PROBATION" : i % 17 === 5 ? "ON_NOTICE" : i % 23 === 7 ? "INACTIVE" : "ACTIVE";
  return {
    id: `demo_${i}`,
    employeeNumber: `SRJ${String(1001 + i)}`,
    name,
    email: `${name.toLowerCase().replace(" ", ".")}@surajgroup.in`,
    department,
    designation: desgs[i % desgs.length],
    location: LOCATIONS[i % LOCATIONS.length],
    hireDate,
    type: i % 7 === 3 ? "Contract" : i % 11 === 4 ? "Trainee" : "Permanent",
    state,
    manager: `${FIRST[(i + 5) % FIRST.length]} ${LAST[(i + 3) % LAST.length]}`,
  };
});

export const ATTENDANCE_TREND = [
  { label: "Sep 7", value: 93, present: 136, late: 6, absent: 6 },
  { label: "Sep 8", value: 95, present: 139, late: 4, absent: 5 },
  { label: "Sep 9", value: 94, present: 138, late: 7, absent: 3 },
  { label: "Sep 10", value: 91, present: 134, late: 9, absent: 5 },
  { label: "Sep 11", value: 96, present: 141, late: 3, absent: 4 },
  { label: "Sep 14", value: 92, present: 135, late: 8, absent: 5 },
  { label: "Sep 15", value: 94, present: 138, late: 5, absent: 5 },
  { label: "Sep 16", value: 97, present: 142, late: 2, absent: 4 },
  { label: "Sep 17", value: 95, present: 139, late: 5, absent: 4 },
  { label: "Sep 18", value: 93, present: 137, late: 6, absent: 5 },
  { label: "Sep 21", value: 96, present: 141, late: 4, absent: 3 },
  { label: "Sep 22", value: 95, present: 140, late: 5, absent: 3 },
];

export const DEPT_HEADCOUNT = [
  { label: "Operations", value: 32 },
  { label: "Export", value: 28 },
  { label: "Sales", value: 24 },
  { label: "Import", value: 22 },
  { label: "Accounts", value: 18 },
  { label: "Admin", value: 16 },
  { label: "HR", value: 8 },
];

export const LEAVE_BY_TYPE = [
  { label: "Casual", value: 14, color: "#14b8a6" },
  { label: "Sick", value: 9, color: "#3b82f6" },
  { label: "Earned", value: 6, color: "#8b5cf6" },
  { label: "Comp-off", value: 3, color: "#f59e0b" },
];

export const ACTION_ITEMS = [
  { label: "Leave approvals", count: 7, tone: "warning", to: "/leave" },
  { label: "Attendance regularisation", count: 3, tone: "warning", to: "/corrections" },
  { label: "Probation reviews due", count: 4, tone: "danger", to: "/employees" },
  { label: "Confirmations due", count: 2, tone: "info", to: "/employees" },
  { label: "Onboarding tasks overdue", count: 3, tone: "danger", to: "/onboarding" },
  { label: "Documents expiring", count: 3, tone: "neutral", to: "/employees" },
] as const;

export const TODAY_EVENTS = [
  { name: "Kavya Nair", kind: "birthday", detail: "Birthday" },
  { name: "Arjun Joshi", kind: "birthday", detail: "Birthday" },
  { name: "Meera Kulkarni", kind: "anniversary", detail: "5 years at SFPL" },
  { name: "Varun Reddy", kind: "joining", detail: "Joins Sales today" },
] as const;
