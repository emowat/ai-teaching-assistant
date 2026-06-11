import { useEffect, useMemo, useState } from "react";
import { useAuth } from "react-oidc-context";
import { getPrimaryRole, getUserGroups } from "./auth/getUserGroups";
import { AdminDashboard } from "./pages/AdminDashboard";
import { AuthCallbackPage } from "./pages/AuthCallbackPage";
import { LandingPage } from "./pages/LandingPage";
import { ProfessorDashboard } from "./pages/ProfessorDashboard";
import { StudentInterface } from "./pages/StudentInterface";
import type { AppView } from "./types/navigation";
import { D } from "./design/tokens";

function roleToView(role: string | null): AppView {
  if (role === "admin") return "admin";
  if (role === "professor") return "professor";
  if (role === "student") return "student";
  return "landing";
}

function App() {
  const auth = useAuth();
  const groups = getUserGroups(auth.user?.profile);
  const role = getPrimaryRole(groups);
  const defaultView = roleToView(role);

  const demoMode = import.meta.env.DEV;
  const [viewOverride, setViewOverride] = useState<AppView | null>(null);

  const isCallback =
    window.location.pathname === "/auth/callback" ||
    window.location.pathname.endsWith("/auth/callback");

  useEffect(() => {
    if (auth.isAuthenticated && isCallback) {
      window.history.replaceState({}, document.title, "/");
    }
  }, [auth.isAuthenticated, isCallback]);

  useEffect(() => {
    if (auth.isAuthenticated && !demoMode) {
      setViewOverride(null);
    }
  }, [auth.isAuthenticated, role, demoMode]);

  const activeView = useMemo(() => {
    if (demoMode && viewOverride) return viewOverride;
    if (auth.isAuthenticated) return defaultView;
    return "landing";
  }, [auth.isAuthenticated, defaultView, demoMode, viewOverride]);

  const navigate = (view: AppView) => {
    if (demoMode) {
      setViewOverride(view);
      return;
    }
    if (view === "landing" && auth.isAuthenticated) {
      void auth.signoutRedirect({
        post_logout_redirect_uri: import.meta.env.VITE_COGNITO_LOGOUT_URI,
      });
    }
  };

  if (isCallback) {
    return <AuthCallbackPage />;
  }

  if (auth.isLoading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background: D.bg,
          color: D.muted,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        Loading...
      </div>
    );
  }

  if (auth.error) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background: D.bg,
          color: D.red,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
          padding: 24,
        }}
      >
        Auth error: {auth.error.message}
      </div>
    );
  }

  const demoPreview =
    demoMode && !auth.isAuthenticated && viewOverride && viewOverride !== "landing";

  if (!auth.isAuthenticated && !demoPreview) {
    return <LandingPage onNavigate={navigate} demoMode={demoMode} />;
  }

  if (activeView === "admin") {
    return <AdminDashboard onNavigate={navigate} demoMode={demoMode} />;
  }
  if (activeView === "professor") {
    return <ProfessorDashboard onNavigate={navigate} demoMode={demoMode} />;
  }
  if (activeView === "student") {
    return <StudentInterface onNavigate={navigate} demoMode={demoMode} />;
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: D.bg,
        color: D.text,
        fontFamily: "system-ui, sans-serif",
        padding: 48,
      }}
    >
      <p>Signed in as {auth.user?.profile.email as string}</p>
      <p>No Cognito group assigned. Contact an administrator.</p>
      <button
        type="button"
        onClick={() =>
          auth.signoutRedirect({
            post_logout_redirect_uri: import.meta.env.VITE_COGNITO_LOGOUT_URI,
          })
        }
        style={{
          marginTop: 16,
          background: D.orange,
          color: "#fff",
          border: "none",
          borderRadius: 6,
          padding: "8px 16px",
          cursor: "pointer",
        }}
      >
        Sign Out
      </button>
    </div>
  );
}

export default App;
