import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, type ReactNode } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PlatformAuthProvider, usePlatformAuth } from "./context/PlatformAuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./components/ui/Toast";
import { AppShell } from "./components/layout/AppShell";
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
const CorrectionsPage = lazy(() => import("./pages/CorrectionsPage").then(m => ({ default: m.CorrectionsPage })));
const PolicyPage = lazy(() => import("./pages/PolicyPage").then(m => ({ default: m.PolicyPage })));
const OnboardingPage = lazy(() => import("./pages/OnboardingPage").then(m => ({ default: m.OnboardingPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then(m => ({ default: m.ReportsPage })));
const OrganizationPage = lazy(() => import("./pages/OrganizationPage").then(m => ({ default: m.OrganizationPage })));
const ProfilePage = lazy(() => import("./pages/ProfilePage").then(m => ({ default: m.ProfilePage })));
const DailyAnalysisPage = lazy(() => import("./pages/DailyAnalysisPage").then(m => ({ default: m.DailyAnalysisPage })));

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } });

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequirePlatformAuth({ children }: { children: ReactNode }) {
  const { admin, loading } = usePlatformAuth();
  if (loading) return null;
  if (!admin) return <Navigate to="/platform/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <ToastProvider>
            <BrowserRouter>
              <Suspense fallback={<p role="status" className="p-6">Loading…</p>}>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/register" element={<RegisterCompanyPage />} />
                <Route
                  path="/platform/*"
                  element={
                    <PlatformAuthProvider>
                      <Routes>
                        <Route path="/login" element={<PlatformLoginPage />} />
                        <Route path="/forgot-password" element={<PlatformForgotPasswordPage />} />
                        <Route path="/reset-password" element={<PlatformResetPasswordPage />} />
                        <Route path="/" element={<RequirePlatformAuth><PlatformConsolePage /></RequirePlatformAuth>} />
                      </Routes>
                    </PlatformAuthProvider>
                  }
                />
                <Route
                  path="/*"
                  element={
                    <RequireAuth>
                      <AppShell>
                        <Routes>
                          <Route path="/" element={<Navigate to="/dashboard" replace />} />
                          <Route path="/dashboard" element={<DashboardPage />} />
                          <Route path="/employees" element={<EmployeePage />} />
                          <Route path="/daily-analysis" element={<DailyAnalysisPage />} />
                          <Route path="/kyc" element={<Navigate to="/profile?tab=kyc" replace />} />
                          <Route path="/attendance" element={<AttendancePage />} />
                          <Route path="/leave" element={<LeavePage />} />
                          <Route path="/corrections" element={<CorrectionsPage />} />
                          <Route path="/organization" element={<OrganizationPage />} />
                          <Route path="/profile" element={<ProfilePage />} />
                          <Route path="/policy" element={<PolicyPage />} />
                          <Route path="/onboarding" element={<OnboardingPage />} />
                          <Route path="/reports" element={<ReportsPage />} />
                          <Route path="*" element={<Navigate to="/dashboard" replace />} />
                        </Routes>
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
  );
}
