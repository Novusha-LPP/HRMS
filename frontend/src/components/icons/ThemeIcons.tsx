/** Each palette owns its treatment; Classic Teal keeps the original Lucide glyph. */
import { forwardRef } from "react";
import type { LucideIcon, LucideProps, IconNode } from "lucide-react";
import { createLucideIcon } from "lucide-react";
import { useTheme } from "../../context/ThemeContext";
import {
  Users as ClassicUsers,
  UserPlus as ClassicUserPlus,
  UserMinus as ClassicUserMinus,
  UserCheck as ClassicUserCheck,
  UserCircle as ClassicUserCircle,
  Armchair as ClassicArmchair,
  Hourglass as ClassicHourglass,
  LogOut as ClassicLogOut,
  DoorOpen as ClassicDoorOpen,
  Calendar as ClassicCalendar,
  CalendarCheck as ClassicCalendarCheck,
  CalendarClock as ClassicCalendarClock,
  CalendarX2 as ClassicCalendarX2,
  Clock as ClassicClock,
  Timer as ClassicTimer,
  TimerReset as ClassicTimerReset,
  FileText as ClassicFileText,
  FilePenLine as ClassicFilePenLine,
  FileClock as ClassicFileClock,
  ClipboardCheck as ClassicClipboardCheck,
  ShieldCheck as ClassicShieldCheck,
  IdCard as ClassicIdCard,
  Building2 as ClassicBuilding2,
  Briefcase as ClassicBriefcase,
  BookOpen as ClassicBookOpen,
  GraduationCap as ClassicGraduationCap,
  BarChart3 as ClassicBarChart3,
  ChartPie as ClassicChartPie,
  Cake as ClassicCake,
  Gift as ClassicGift,
  Award as ClassicAward,
  Sparkles as ClassicSparkles,
  Inbox as ClassicInbox,
  ListChecks as ClassicListChecks,
  Umbrella as ClassicUmbrella,
  MapPin as ClassicMapPin,
  Plane as ClassicPlane,
  LayoutGrid as ClassicLayoutGrid,
  LayoutDashboard as ClassicLayoutDashboard,
  Search as ClassicSearch,
  Bell as ClassicBell,
  PanelLeft as ClassicPanelLeft,
  Palette as ClassicPalette,
  Sun as ClassicSun,
  Moon as ClassicMoon,
  Monitor as ClassicMonitor,
  TriangleAlert as ClassicTriangleAlert,
  Zap as ClassicZap,
  Check as ClassicCheck,
  CheckCheck as ClassicCheckCheck,
  CircleCheck as ClassicCircleCheck,
  CircleX as ClassicCircleX,
  X as ClassicX,
  Plus as ClassicPlus,
  ChevronRight as ClassicChevronRight,
  ChevronsUpDown as ClassicChevronsUpDown,
  ArrowUp as ClassicArrowUp,
  ArrowDown as ClassicArrowDown,
  ArrowUpRight as ClassicArrowUpRight,
  ArrowDownRight as ClassicArrowDownRight,
  Wallet as ClassicWallet,
  ExternalLink as ClassicExternalLink,
  Copy as ClassicCopy,
  GripVertical as ClassicGripVertical,
  RotateCcw as ClassicRotateCcw,
  RefreshCw as ClassicRefreshCw,
  ClipboardList as ClassicClipboardList,
  ShieldAlert as ClassicShieldAlert,
  ShieldOff as ClassicShieldOff,
  ChevronLeft as ClassicChevronLeft,
  ArrowLeft as ClassicArrowLeft,
  ArrowRight as ClassicArrowRight,
  Archive as ClassicArchive,
  ArchiveRestore as ClassicArchiveRestore,
  Loader2 as ClassicLoader2,
} from "lucide-react";

type Attributes = IconNode[number][1];
const solid: Attributes = { fill: "currentColor", stroke: "none" };
const path = (d: string, attrs: Attributes = {}): IconNode[number] => ["path", { d, ...attrs }];
const circle = (cx: number, cy: number, r: number, attrs: Attributes = {}): IconNode[number] => ["circle", { cx, cy, r, ...attrs }];
const rect = (x: number, y: number, width: number, height: number, rx: number, attrs: Attributes = {}): IconNode[number] => ["rect", { x, y, width, height, rx, ...attrs }];
const calendar: IconNode = [rect(2,4,20,18,2),path("M2 9h20M7 1v6m10-6v6"),path("M6 13h2m3 0h2m3 0h2M6 17h2m3 0h2m3 0h2",{strokeOpacity:.35})];
const clock: IconNode = [circle(12,13,9),path("M12 7v6l4 2M10 1h4"),circle(12,13,1,solid)];
const file: IconNode = [path("M4 2h10l6 6v14H4Z"),path("M14 2v6h6M8 12h8m-8 4h8m-8 3h5")];

function themed(name: string, Classic: LucideIcon, nodes: IconNode): LucideIcon {
  const Midnight = createLucideIcon(`Midnight${name}`, nodes.map(([tag, attrs], index) => [tag, { ...attrs, key: String(index) }]));
  const themedIcon = forwardRef<SVGSVGElement, LucideProps>((props, ref) => {
    const { colorTheme } = useTheme();
    if (colorTheme === "ember-sand") {
      return <Classic ref={ref} {...props} strokeWidth={1.75} data-icon-set="ember-sand" data-icon-name={name} />;
    }
    return colorTheme === "midnight-blue"
      ? <Midnight ref={ref} strokeWidth={1.7} {...props} data-icon-set="midnight-blue" data-icon-name={name} />
      : <Classic ref={ref} {...props} />;
  });
  themedIcon.displayName = `Theme${name}`;
  return themedIcon;
}

export const Users = themed("Users", ClassicUsers, [circle(12, 6, 4, solid), path("M2.5 22v-4c0-4 4.3-6 9.5-6s9.5 2 9.5 6v4Z", solid)]);
export const UserPlus = themed("UserPlus", ClassicUserPlus, [circle(8, 6, 4, solid), path("M0 22v-4c0-3.7 3.5-5.5 8-5.5s8 1.8 8 5.5v4Z", solid), path("M20 8v8m-4-4h8",{strokeWidth:2})]);
export const UserMinus = themed("UserMinus", ClassicUserMinus, [circle(8, 6, 3.4, solid), path("M1.5 21v-3.3c0-3.3 2.9-5.2 6.5-5.2s6.5 1.9 6.5 5.2V21Z", solid), path("M16 11h7")]);
export const UserCheck = themed("UserCheck", ClassicUserCheck, [circle(12, 6, 3.5, solid), circle(4, 8, 2.8, solid), circle(20, 8, 2.8, solid), path("M5.5 22v-5c0-3.3 2.7-5.1 6.5-5.1s6.5 1.8 6.5 5.1v5ZM0 20v-4c0-2.6 1.8-4.3 4-4.3h1.8C4 13.1 3.5 15 3.5 17v3Zm24 0v-4c0-2.6-1.8-4.3-4-4.3h-1.8c1.8 1.4 2.3 3.3 2.3 5.3v3Z", solid)]);
export const UserCircle = themed("UserCircle", ClassicUserCircle, [circle(12,12,10), circle(12,8,3,solid), path("M5 19c.6-4 3-6 7-6s6.4 2 7 6",{fill:"currentColor",fillOpacity:.18})]);
export const Armchair = themed("Armchair", ClassicArmchair, [rect(6,1,12,12,3,solid),rect(5,14,14,3,1.5,solid),path("M2 10v3c0 3 2 4 4 4m16-7v3c0 3-2 4-4 4M12 17v4m-6 2v-1c0-1 3-2 6-2s6 1 6 2v1",{strokeWidth:2}),circle(2,9,1,solid),circle(22,9,1,solid)]);
export const Hourglass = themed("Hourglass", ClassicHourglass, [path("M5 2h14M5 22h14M7 2v4c0 3 3 4 5 6-2 2-5 3-5 6v4m10-20v4c0 3-3 4-5 6 2 2 5 3 5 6v4"),path("M8.5 6h7L12 10Zm0 13 3.5-4 3.5 4Z",solid)]);
export const LogOut = themed("LogOut", ClassicLogOut, [path("M13 3H4v18h9M10 12h12m-4-4 4 4-4 4"),path("M4 6h5v12H4Z",{fill:"currentColor",fillOpacity:.14,stroke:"none"})]);
export const DoorOpen = themed("DoorOpen", ClassicDoorOpen, [path("M13 3H4v18h9M10 12h12m-4-4 4 4-4 4"),path("M4 3 10 5v14l-6 2Z",{fill:"currentColor",fillOpacity:.16})]);
export const Calendar = themed("Calendar", ClassicCalendar, calendar);
export const CalendarCheck = themed("CalendarCheck", ClassicCalendarCheck, [...calendar,path("m8 15 3 3 5-6")]);
export const CalendarClock = themed("CalendarClock", ClassicCalendarClock, [...calendar.slice(0,3),circle(16,16,6),path("M16 12v4l2.5 1.5")]);
export const CalendarX2 = themed("CalendarX2", ClassicCalendarX2, [...calendar,path("m9 13 6 6m0-6-6 6")]);
export const Clock = themed("Clock", ClassicClock, clock);
export const Timer = themed("Timer", ClassicTimer, [...clock,path("M9 1h6m-3 0v2")]);
export const TimerReset = themed("TimerReset", ClassicTimerReset, [path("M3 8a9 9 0 1 1 0 9M3 3v5h5M12 7v6l4 2")]);
export const FileText = themed("FileText", ClassicFileText, file);
export const FilePenLine = themed("FilePenLine", ClassicFilePenLine, [...file.slice(0,2),path("m10 18 8-8 3 3-8 8-4 1Z") ]);
export const FileClock = themed("FileClock", ClassicFileClock, [...file.slice(0,2),circle(17,17,5),path("M17 14v3l2 1")]);
export const ClipboardCheck = themed("ClipboardCheck", ClassicClipboardCheck, [rect(4,4,16,18,2),rect(8,2,8,4,1,{fill:"currentColor",fillOpacity:.15}),path("m7 14 3 3 7-7")]);
export const ShieldCheck = themed("ShieldCheck", ClassicShieldCheck, [path("M12 2 3 6v6c0 5 4 8 9 10 5-2 9-5 9-10V6Z",{fill:"currentColor",fillOpacity:.12}),path("m7 12 3 3 7-7")]);
export const IdCard = themed("IdCard", ClassicIdCard, [rect(2,4,20,16,2),circle(8,10,2.5,solid),path("M4 17c0-4 8-4 8 0Z",solid),path("M15 9h4m-4 4h4m-4 4h2")]);
export const Wallet = themed("Wallet", ClassicWallet, [rect(2,6,20,15,2,{fill:"currentColor",fillOpacity:.1}),path("M5 6V4.5A1.5 1.5 0 0 1 6.5 3H18v3"),path("M15 11h7v6h-7a3 3 0 0 1 0-6Z"),circle(16.5,14,1.2,solid)]);
export const Building2 = themed("Building2", ClassicBuilding2, [path("M3 22V7h7v15M10 22V2h11v20M1 22h22M5 10h2m-2 4h2m-2 4h2m7-12h3m-3 4h3m-3 4h3m-3 4h3"),path("M11 3h9v3h-9Z",{fill:"currentColor",fillOpacity:.15,stroke:"none"})]);
export const Briefcase = themed("Briefcase", ClassicBriefcase, [rect(2,7,20,14,2),path("M8 7V3h8v4M2 12c6 4 14 4 20 0M10 12h4v5h-4Z")]);
export const BookOpen = themed("BookOpen", ClassicBookOpen, [path("M12 5C9 2 4 2 2 3v17c4-1 7-1 10 2 3-3 6-3 10-2V3c-2-1-7-1-10 2Zm0 0v17M5 7h4M5 11h4m6-4h4m-4 4h4")]);
export const GraduationCap = themed("GraduationCap", ClassicGraduationCap, [path("m1 8 11-5 11 5-11 5ZM5 10v7c4 4 10 4 14 0v-7M23 8v10"),path("m5 6 7-3 7 3-7 3Z",{fill:"currentColor",fillOpacity:.16,stroke:"none"})]);
export const BarChart3 = themed("BarChart3", ClassicBarChart3, [path("M3 22V13h4v9m3 0V9h4v13m3 0V4h4v18M3 8l6-4 5 2 7-5"),path("M4 17h2v5H4Zm7-4h2v9h-2Zm7-5h2v14h-2Z",{fill:"currentColor",fillOpacity:.2,stroke:"none"})]);
export const ChartPie = themed("ChartPie", ClassicChartPie, [path("M10 2a10 10 0 1 0 12 12H10Zm4 0v8h8a10 10 0 0 0-8-8Z",{fill:"currentColor",fillOpacity:.15})]);
export const Cake = themed("Cake", ClassicCake, [path("M3 21V11h18v10ZM3 15c2 3 4-3 6 0s4-3 6 0 4-3 6 0M1 22h22M7 7v4m5-4v4m5-4v4"),path("M7 2c-3 3 3 5 0 0m5 0c-3 3 3 5 0 0m5 0c-3 3 3 5 0 0",solid)]);
export const Gift = themed("Gift", ClassicGift, [rect(2,7,20,5,1),path("M4 12v10h16V12M12 7v15M12 7C2 8 4-3 12 7Zm0 0c10 1 8-10 0 0"),path("M10 12h4v10h-4Z",{fill:"currentColor",fillOpacity:.2,stroke:"none"})]);
export const Award = themed("Award", ClassicAward, [circle(12,8,6,{fill:"currentColor",fillOpacity:.14}),path("m8 13-3 9 7-3 7 3-3-9m-4-9 1 3 3 1-3 1-1 3-1-3-3-1 3-1Z")]);
export const Sparkles = themed("Sparkles", ClassicSparkles, [path("m12 2 2.5 6.5L21 11l-6.5 2.5L12 20l-2.5-6.5L3 11l6.5-2.5Z",{fill:"currentColor",fillOpacity:.17}),path("M20 1v5m-2.5-2.5h5M3 17v5m-2.5-2.5h5")]);
export const Inbox = themed("Inbox", ClassicInbox, [path("M2 17 5 4h14l3 13v5H2Zm0 0h6l2 3h4l2-3h6M8 8h8m-9 4h10"),path("M3 18h4l2 3h6l2-3h4v3H3Z",{fill:"currentColor",fillOpacity:.15,stroke:"none"})]);
export const ListChecks = themed("ListChecks", ClassicListChecks, [path("m2 5 2 2 3-4m-5 9 2 2 3-4m-5 10 2 2 3-4M11 5h11M11 12h11M11 20h11")]);
export const Umbrella = themed("Umbrella", ClassicUmbrella, [path("M2 11a10 10 0 0 1 20 0c-2-2-4-2-6 0-2-2-6-2-8 0-2-2-4-2-6 0ZM12 2C8 4 8 7 8 11m4-9c4 2 4 5 4 9m-4 0v8a3 3 0 0 0 6 0"),path("M12 2V0")]);
export const MapPin = themed("MapPin", ClassicMapPin, [path("M12 23C9 18 4 13 4 8a8 8 0 1 1 16 0c0 5-5 10-8 15Z",{fill:"currentColor",fillOpacity:.12}),circle(12,8,3)]);
export const Plane = themed("Plane", ClassicPlane, [path("m2 10 8-2 2-7 2 7 8 2v3l-8-1v7l3 2v2l-5-1-5 1v-2l3-2v-7-0l-8 1Z")]);
export const LayoutGrid = themed("LayoutGrid", ClassicLayoutGrid, [path("m2 10 10-8 10 8M4 9v13h6v-8h4v8h6V9",{fill:"currentColor",fillOpacity:.1})]);
export const LayoutDashboard = themed("LayoutDashboard", ClassicLayoutDashboard, [rect(2,3,20,18,2),path("M2 9h20M9 9v12"),rect(12,12,7,6,1,{fill:"currentColor",fillOpacity:.18,stroke:"none"})]);
export const Search = themed("Search", ClassicSearch, [circle(10,10,7),path("m15 15 7 7M6 10a4 4 0 0 1 4-4")]);
export const Bell = themed("Bell", ClassicBell, [path("M3 18h18l-3-4V9a6 6 0 0 0-12 0v5Zm6 3c1 2 5 2 6 0M12 1v2"),path("M8 14V9a4 4 0 0 1 4-4",{opacity:.5})]);
export const PanelLeft = themed("PanelLeft", ClassicPanelLeft, [path("M3 5h18M3 12h13M3 19h18")]);
export const Palette = themed("Palette", ClassicPalette, [circle(12,12,10),circle(8,8,1.5,solid),circle(15,7,1.5,solid),circle(18,13,1.5,solid),path("M6 17c1-3 7-3 7 0s-4 5-7 0Z",{fill:"currentColor",fillOpacity:.2})]);
export const Sun = themed("Sun", ClassicSun, [circle(12,12,4,solid),path("M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2")]);
export const Moon = themed("Moon", ClassicMoon, [path("M20 16A10 10 0 0 1 8 3a10 10 0 1 0 12 13Z",{fill:"currentColor",fillOpacity:.2}),path("M18 2v5m-2.5-2.5h5")]);
export const Monitor = themed("Monitor", ClassicMonitor, [rect(1,3,22,15,2),path("M8 23h8m-4-5v5M1 14h22")]);
export const TriangleAlert = themed("TriangleAlert", ClassicTriangleAlert, [path("m12 2 11 20H1Z",{fill:"currentColor",fillOpacity:.1}),path("M12 8v6"),circle(12,18,1,solid)]);
export const Zap = themed("Zap", ClassicZap, [path("m14 1-12 13h9l-1 9 12-14h-9Z",{fill:"currentColor",fillOpacity:.22})]);
export const Check = themed("Check", ClassicCheck, [path("m3 12 6 6L21 5")]);
export const CheckCheck = themed("CheckCheck", ClassicCheckCheck, [path("m1 12 5 6L18 5m-6 11 2 2L24 6")]);
export const CircleCheck = themed("CircleCheck", ClassicCircleCheck, [circle(12,12,10,{fill:"currentColor",fillOpacity:.1}),path("m6 12 4 4 8-9")]);
export const CircleX = themed("CircleX", ClassicCircleX, [circle(12,12,10,{fill:"currentColor",fillOpacity:.1}),path("m8 8 8 8m0-8-8 8")]);
export const X = themed("X", ClassicX, [path("m5 5 14 14m0-14L5 19")]);
export const Plus = themed("Plus", ClassicPlus, [path("M12 3v18M3 12h18")]);
export const ChevronRight = themed("ChevronRight", ClassicChevronRight, [path("m8 4 8 8-8 8")]);
export const ChevronsUpDown = themed("ChevronsUpDown", ClassicChevronsUpDown, [path("m7 8 5-5 5 5M7 16l5 5 5-5")]);
export const ArrowUp = themed("ArrowUp", ClassicArrowUp, [path("M12 22V2m-7 7 7-7 7 7")]);
export const ArrowDown = themed("ArrowDown", ClassicArrowDown, [path("M12 2v20m-7-7 7 7 7-7")]);
export const ArrowUpRight = themed("ArrowUpRight", ClassicArrowUpRight, [path("M3 21 21 3H7m14 0v14")]);
export const ArrowDownRight = themed("ArrowDownRight", ClassicArrowDownRight, [path("m3 3 18 18H7m14 0V7")]);
export const ExternalLink = themed("ExternalLink", ClassicExternalLink, [path("M13 2h9v9M22 2 10 14M10 5H2v17h17v-8")]);
export const Copy = themed("Copy", ClassicCopy, [rect(7,7,15,15,2),path("M17 4V2H2v15h2M11 12h7m-7 5h7")]);
export const GripVertical = themed("GripVertical", ClassicGripVertical, [rect(5,3,3,3,0,solid),rect(15,3,3,3,0,solid),rect(5,10.5,3,3,0,solid),rect(15,10.5,3,3,0,solid),rect(5,18,3,3,0,solid),rect(15,18,3,3,0,solid)]);
export const RotateCcw = themed("RotateCcw", ClassicRotateCcw, [path("M2 9a10 10 0 1 1 1 9M2 2v7h7")]);
export const RefreshCw = themed("RefreshCw", ClassicRefreshCw, [path("M3 9a9 9 0 0 1 16-4l3 4M22 2v7h-7M21 15a9 9 0 0 1-16 4l-3-4M2 22v-7h7")]);

// Navigation uses the reference's line-style people and calendar silhouettes.
export const NavigationUsers = themed("NavigationUsers", ClassicUsers, [circle(9,6,3),circle(18,8,2.5),path("M2 21v-4c0-3 3-5 7-5s7 2 7 5v4Zm16-8c3 0 5 2 5 4v4h-4")]);
export const NavigationLeave = themed("NavigationLeave", ClassicUmbrella, [...calendar,path("m8 15 3 3 5-6")]);

// Quick actions in the reference use outlines, separate from the filled KPI silhouettes.
export const ActionUserPlus = themed("ActionUserPlus", ClassicUserPlus, [circle(8,5,4),path("M1 22v-4c0-4 3-6 7-6s7 2 7 6v4ZM20 8v8m-4-4h8")]);
export const ActionCorrection = themed("ActionCorrection", ClassicFilePenLine, [path("M21 8a10 10 0 1 0 1 8M22 3v5h-5M12 6v7l4 2"),path("m18 20 2 2 4-4")]);
export const ActionReports = themed("ActionReports", ClassicListChecks, [path("M3 22v-7h3v7m4 0V10h3v12m4 0V5h3v17M3 9l7-5 4 2 7-5m-5 0h5v5")]);

export const ClipboardList = themed("ClipboardList", ClassicClipboardList, [rect(4,4,16,18,2),rect(8,2,8,4,1),path("M10 10h6m-6 5h6m-6 4h6"),circle(7,10,.7,solid),circle(7,15,.7,solid),circle(7,19,.7,solid)]);
export const ShieldAlert = themed("ShieldAlert", ClassicShieldAlert, [path("M12 2 3 6v6c0 5 4 8 9 10 5-2 9-5 9-10V6Z",{fill:"currentColor",fillOpacity:.12}),path("M12 7v6"),circle(12,17,1,solid)]);
export const ShieldOff = themed("ShieldOff", ClassicShieldOff, [path("m3 2 19 20M12 2l9 4v6c0 2-.5 3.5-1.5 5M6 5 3 6v6c0 5 4 8 9 10 2-.8 3.8-1.8 5.2-3")]);
export const ChevronLeft = themed("ChevronLeft", ClassicChevronLeft, [path("m16 4-8 8 8 8")]);
export const ArrowLeft = themed("ArrowLeft", ClassicArrowLeft, [path("M22 12H2m7-7-7 7 7 7")]);
export const ArrowRight = themed("ArrowRight", ClassicArrowRight, [path("M2 12h20m-7-7 7 7-7 7")]);
export const Archive = themed("Archive", ClassicArchive, [rect(2,2,20,5,1),path("M4 7v15h16V7M9 12h6")]);
export const ArchiveRestore = themed("ArchiveRestore", ClassicArchiveRestore, [rect(2,2,20,5,1),path("M4 7v15h16V7M12 18V10m-4 4 4-4 4 4")]);
export const Loader2 = themed("Loader2", ClassicLoader2, [path("M22 12A10 10 0 1 1 12 2")]);
