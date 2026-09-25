import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PlatformAuthProvider, usePlatformAuth } from "./context/PlatformAuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./components/ui/Toast";
import { AppShell } from "./components/layout/AppShell";
import { LoginPage } from "./pages/LoginPage";
import { RegisterCompanyPage } from "./pages/RegisterCompanyPage";
import { PlatformLoginPage } from "./pages/PlatformLoginPage";
import { PlatformForgotPasswordPage } from "./pages/PlatformForgotPasswordPage";
import { PlatformResetPasswordPage } from "./pages/PlatformResetPasswordPage";
import { PlatformConsolePage } from "./pages/PlatformConsolePage";
import { DashboardPage } from "./pages/DashboardPage";
import { EmployeePage } from "./pages/EmployeePage";
import { AttendancePage } from "./pages/AttendancePage";
import { LeavePage } from "./pages/LeavePage";
import { CorrectionsPage } from "./pages/CorrectionsPage";
import { PolicyPage } from "./pages/PolicyPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { ReportsPage } from "./pages/ReportsPage";
import { OrganizationPage } from "./pages/OrganizationPage";
import { ProfilePage } from "./pages/ProfilePage";
import { DailyAnalysisPage } from "./pages/DailyAnalysisPage";

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
            </BrowserRouter>
          </ToastProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
