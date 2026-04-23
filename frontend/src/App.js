import { useEffect, useState } from "react";
import "./App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import DashboardLayout from "./components/DashboardLayout";
import Dashboard from "./pages/Dashboard";
import LinksPage from "./pages/LinksPage";
import ClicksPage from "./pages/ClicksPage";
import ConversionsPage from "./pages/ConversionsPage";
import ProxiesPage from "./pages/ProxiesPage";
import SettingsPage from "./pages/SettingsPage";
import ReferrerStatsPage from "./pages/ReferrerStatsPage";
import ImportTrafficPage from "./pages/ImportTrafficPage";
import EmailCheckerPage from "./pages/EmailCheckerPage";
import SeparateDataPage from "./pages/SeparateDataPage";
import UserAgentGeneratorPage from "./pages/UserAgentGeneratorPage";
import UserAgentCheckerPage from "./pages/UserAgentCheckerPage";
import FormFillerPage from "./pages/FormFillerPage";
import RealUserTrafficPage from "./pages/RealUserTrafficPage";
import AdminLoginPage from "./pages/AdminLoginPage";
import AdminDashboard from "./pages/AdminDashboard";
import { Toaster } from "./components/ui/sonner";
import { BrandingProvider } from "./context/BrandingContext";

function PrivateRoute({ children }) {
  const token = localStorage.getItem("token");
  return token ? children : <Navigate to="/login" />;
}

function AdminRoute({ children }) {
  const adminToken = localStorage.getItem("adminToken");
  return adminToken ? children : <Navigate to="/admin" />;
}

// Feature-protected route component
function FeatureRoute({ children, feature }) {
  const user = JSON.parse(localStorage.getItem("user") || "{}");
  const features = user.features || {};
  const isSubUser = user.is_sub_user === true;
  
  // Settings is ONLY for main users, and only if not explicitly disabled
  if (feature === "settings") {
    // Sub-users can NEVER access settings
    if (isSubUser) {
      return <Navigate to="/" replace />;
    }
    // Main users can access unless explicitly set to false
    if (features.settings === false) {
      return <Navigate to="/" replace />;
    }
    return children;
  }
  
  // Backward compat: new granular features fall back to "import_data" legacy flag
  const LEGACY_IMPORT_GROUP = new Set([
    "email_checker", "separate_data", "import_traffic", "real_traffic", "ua_generator"
  ]);

  // If feature is specified and not enabled, redirect to dashboard
  if (feature) {
    const explicit = features[feature];
    const hasAccess =
      explicit === true ||
      (explicit === undefined && LEGACY_IMPORT_GROUP.has(feature) && features.import_data === true);
    if (!hasAccess) {
      return <Navigate to="/" replace />;
    }
  }
  
  return children;
}

function App() {
  return (
    <BrandingProvider>
      <div className="App">
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/admin" element={<AdminLoginPage />} />
            <Route path="/admin/dashboard" element={
              <AdminRoute>
                <AdminDashboard />
              </AdminRoute>
            } />
            <Route
              path="/*"
              element={
                <PrivateRoute>
                  <DashboardLayout>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/links" element={
                        <FeatureRoute feature="links">
                          <LinksPage />
                        </FeatureRoute>
                      } />
                      <Route path="/clicks" element={
                        <FeatureRoute feature="clicks">
                          <ClicksPage />
                        </FeatureRoute>
                      } />
                      <Route path="/conversions" element={
                        <FeatureRoute feature="conversions">
                          <ConversionsPage />
                        </FeatureRoute>
                      } />
                      <Route path="/proxies" element={
                        <FeatureRoute feature="proxies">
                          <ProxiesPage />
                        </FeatureRoute>
                      } />
                      <Route path="/referrers" element={
                        <FeatureRoute feature="clicks">
                          <ReferrerStatsPage />
                        </FeatureRoute>
                      } />
                      <Route path="/import-traffic" element={
                        <FeatureRoute feature="import_traffic">
                          <ImportTrafficPage />
                        </FeatureRoute>
                      } />
                      <Route path="/email-checker" element={
                        <FeatureRoute feature="email_checker">
                          <EmailCheckerPage />
                        </FeatureRoute>
                      } />
                      <Route path="/separate-data" element={
                        <FeatureRoute feature="separate_data">
                          <SeparateDataPage />
                        </FeatureRoute>
                      } />
                      <Route path="/ua-generator" element={
                        <FeatureRoute feature="ua_generator">
                          <UserAgentGeneratorPage />
                        </FeatureRoute>
                      } />
                      <Route path="/ua-checker" element={
                        <FeatureRoute feature="ua_generator">
                          <UserAgentCheckerPage />
                        </FeatureRoute>
                      } />
                      <Route path="/form-filler" element={
                        <FeatureRoute feature="form_filler">
                          <FormFillerPage />
                        </FeatureRoute>
                      } />
                      <Route path="/real-user-traffic" element={
                        <FeatureRoute feature="real_user_traffic">
                          <RealUserTrafficPage />
                        </FeatureRoute>
                      } />
                      <Route path="/settings" element={
                        <FeatureRoute feature="settings">
                          <SettingsPage />
                        </FeatureRoute>
                      } />
                    </Routes>
                  </DashboardLayout>
                </PrivateRoute>
              }
            />
          </Routes>
        </BrowserRouter>
        <Toaster position="bottom-left" />
      </div>
    </BrandingProvider>
  );
}

export default App;
