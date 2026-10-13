import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PlatformAuthProvider, usePlatformAuth } from "./context/PlatformAuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./components/ui/Toast";
import { AppShell } from "./components/layout/AppShell";
const MfaSetupPage = lazy(() => import("./pages/MfaSetupPage").then(m => ({ default: m.MfaSetupPage })));
const LoginPage = lazy(() => import("./pages/LoginPage").then(m => ({ default: m.LoginPage })));
const RegisterCompanyPage = lazy(() => import("./pages/RegisterCompanyPage").then(m => ({ default: m.RegisterCompanyPage })));
const PlatformLoginPage = lazy(() => import("./pages/PlatformLoginPage").then(m => ({ default: m.PlatformLoginPage })));
const PlatformForgotPasswordPage = lazy(() => import("./pages/PlatformForgotPasswordPage").then(m => ({ default: m.PlatformForgotPasswordPage })));
const PlatformResetPasswordPage = lazy(() => import("./pages/PlatformResetPasswordPage").then(m => ({ default: m.PlatformResetPasswordPage })));
const PlatformConsolePage = lazy(() => import("./pages/PlatformConsolePage").then(m => ({ default: m.PlatformConsolePage })));
const DashboardPage = lazy(() => import("./pages/DashboardPage").then(m => ({ default: m.DashboardPage })));
const EmployeePage = lazy(() => import("./pages/EmployeePage").then(m => ({ default: m.EmployeePage })));
const AttendancePage = lazy(() => import("./pages/AttendancePage").then(m => ({ default: m.AttendancePage })));
const LeavePage = lazy(() => import("./pages/LeavePage").then(m => ({ default: m.LeavePage })));
const ApprovalsPage = lazy(() => import("./pages/ApprovalsPage").then(m => ({ default: m.ApprovalsPage })));
const CorrectionsPage = lazy(() => import("./pages/CorrectionsPage").then(m => ({ default: m.CorrectionsPage })));
const PolicyPage = lazy(() => import("./pages/PolicyPage").then(m => ({ default: m.PolicyPage })));
const OnboardingPage = lazy(() => import("./pages/OnboardingPage").then(m => ({ default: m.OnboardingPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then(m => ({ default: m.ReportsPage })));
const OrganizationPage = lazy(() => import("./pages/OrganizationPage").then(m => ({ default: m.OrganizationPage })));
const ProfilePage = lazy(() => import("./pages/ProfilePage").then(m => ({ default: m.ProfilePage })));
const RecruitmentPage = lazy(() => import("./pages/RecruitmentPage").then(m => ({ default: m.RecruitmentPage })));
const OpeningDetailPage = lazy(() => import("./pages/OpeningDetailPage").then(m => ({ default: m.OpeningDetailPage })));
const DailyAnalysisPage = lazy(() => import("./pages/DailyAnalysisPage").then(m => ({ default: m.DailyAnalysisPage })));
const AttendanceRegisterPage = lazy(() => import("./pages/AttendanceRegisterPage").then(m => ({ default: m.AttendanceRegisterPage })));
const MyTeamPage = lazy(() => import("./pages/MyTeamPage").then(m => ({ default: m.MyTeamPage })));
const StatutoryPage = lazy(() => import("./pages/StatutoryPage").then(m => ({ default: m.StatutoryPage })));
const PayrollPage = lazy(() => import("./pages/PayrollPage").then(m => ({ default: m.PayrollPage })));
const IntegrationsPage = lazy(() => import("./pages/IntegrationsPage").then(m => ({ default: m.IntegrationsPage })));
const ChangePasswordPage = lazy(() => import("./pages/ChangePasswordPage").then(m => ({ default: m.ChangePasswordPage })));

import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { API_DOCS_URL } from "./lib/runtimeConfig";
import { EnvironmentBadge } from "./components/layout/EnvironmentBadge";

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } });

function RequireAuth({ children, allowPasswordChange = false, allowMfaSetup = false }: { children: ReactNode; allowPasswordChange?: boolean; allowMfaSetup?: boolean }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  // An imported / admin-reset account must set its own password before anything else. The API refuses
  // every other request until it has (403 PASSWORD_CHANGE_REQUIRED); this just takes the user there.
  if (user.mustChangePassword && !allowPasswordChange) return <Navigate to="/change-password" replace />;
  if (user.mfaRequired && !allowMfaSetup && !allowPasswordChange) return <Navigate to="/security/mfa" replace />;
  return <>{children}</>;
}

function RequirePlatformAuth({ children, allowMfaSetup = false }: { children: ReactNode; allowMfaSetup?: boolean }) {
  const { admin, loading } = usePlatformAuth();
  if (loading) return null;
  if (!admin) return <Navigate to="/platform/login" replace />;
  if (admin.mfa_required && !allowMfaSetup) return <Navigate to="/platform/security/mfa" replace />;
  return <>{children}</>;
}

function ExternalRedirect({ to }: { to: string }) {
  useEffect(() => {
    window.location.href = to;
  }, [to]);
  return (
    <div className="flex h-screen items-center justify-center p-6 text-sm text-fg-muted">
      Redirecting to API documentation…
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary variant="fullscreen">
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <AuthProvider>
            <ToastProvider>
              <BrowserRouter>
                <EnvironmentBadge />
                <Suspense fallback={<p role="status" className="p-6">Loading…</p>}>
                <Routes>
                  <Route path="/docs" element={<ExternalRedirect to={API_DOCS_URL} />} />
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/register" element={<RegisterCompanyPage />} />
                  <Route path="/security/mfa" element={<RequireAuth allowMfaSetup><MfaSetupPage /></RequireAuth>} />
                  <Route path="/change-password" element={<RequireAuth allowPasswordChange><ChangePasswordPage /></RequireAuth>} />
                  <Route
                    path="/platform/*"
                    element={
                      <PlatformAuthProvider>
                        <ErrorBoundary variant="card">
                          <Routes>
                            <Route path="/security/mfa" element={<RequirePlatformAuth allowMfaSetup><MfaSetupPage platform /></RequirePlatformAuth>} />
                            <Route path="/login" element={<PlatformLoginPage />} />
                            <Route path="/forgot-password" element={<PlatformForgotPasswordPage />} />
                            <Route path="/reset-password" element={<PlatformResetPasswordPage />} />
                            <Route path="/" element={<RequirePlatformAuth><PlatformConsolePage /></RequirePlatformAuth>} />
                          </Routes>
                        </ErrorBoundary>
                      </PlatformAuthProvider>
                    }
                  />
                  <Route
                    path="/*"
                    element={
                      <RequireAuth>
                        <AppShell>
                          <ErrorBoundary variant="card">
                            <Routes>
                              <Route path="/" element={<Navigate to="/dashboard" replace />} />
                              <Route path="/dashboard" element={<DashboardPage />} />
                              <Route path="/employees" element={<EmployeePage />} />
                              <Route path="/team" element={<MyTeamPage />} />
                              <Route path="/daily-analysis" element={<DailyAnalysisPage />} />
                              <Route path="/kyc" element={<Navigate to="/profile?tab=kyc" replace />} />
                              <Route path="/attendance" element={<AttendancePage />} />
                              <Route path="/attendance/register" element={<AttendanceRegisterPage />} />
                              <Route path="/leave" element={<LeavePage />} />
                              <Route path="/corrections" element={<CorrectionsPage />} />
                              <Route path="/approvals" element={<ApprovalsPage />} />
                              <Route path="/approval-flows" element={<ApprovalsPage key="flows" view="flows" />} />
                              <Route path="/organization" element={<OrganizationPage />} />
                              <Route path="/profile" element={<ProfilePage />} />
                              <Route path="/policy" element={<PolicyPage />} />
                              <Route path="/leave-policies" element={<Navigate to="/policy?tab=leave" replace />} />
                              <Route path="/recruitment" element={<RecruitmentPage />} />
                              <Route path="/recruitment/openings/:openingId" element={<OpeningDetailPage />} />
                              <Route path="/onboarding" element={<OnboardingPage />} />
                              <Route path="/reports" element={<ReportsPage />} />
                              <Route path="/statutory" element={<StatutoryPage />} />
                              <Route path="/payroll" element={<PayrollPage />} />
                              <Route path="/integrations" element={<IntegrationsPage />} />
                              <Route path="*" element={<Navigate to="/dashboard" replace />} />
                            </Routes>
                          </ErrorBoundary>
                        </AppShell>
                      </RequireAuth>
                    }
                  />
                </Routes>
                </Suspense>
              </BrowserRouter>
            </ToastProvider>
          </AuthProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
