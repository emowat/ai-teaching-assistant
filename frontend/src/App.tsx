import { useMemo, useState } from "react";
import { useAuth } from "react-oidc-context";
import { getPrimaryRole, getUserGroups } from "./auth/getUserGroups";
import {
  canAccessView,
  getAllowedViews,
  getDefaultView,
} from "./auth/roleAccess";
import { AdminDashboard } from "./pages/AdminDashboard";
import { LandingPage } from "./pages/LandingPage";
import { signOutCognito } from "./auth/signOutCognito";
import { ProfessorDashboard } from "./pages/ProfessorDashboard";
import { StudentInterface } from "./pages/StudentInterface";
import type { AppView } from "./types/navigation";
import { D } from "./design/tokens";
import { validateCognitoEnv } from "./auth/validateCognitoConfig";

const cognitoEnv = validateCognitoEnv();

function App() {
  const auth = useAuth();
  const groups = getUserGroups(auth.user?.profile);
  const role = getPrimaryRole(groups);
  const defaultView = getDefaultView(role);
  const allowedViews = getAllowedViews(role);

  const demoMode = import.meta.env.DEV;
  const [viewOverride, setViewOverride] = useState<AppView | null>(null);

  const activeView = useMemo(() => {
    const sanitizedOverride = viewOverride && canAccessView(role, viewOverride)
      ? viewOverride
      : null;
    if (sanitizedOverride) return sanitizedOverride;
    if (demoMode && viewOverride && !auth.isAuthenticated) return viewOverride;
    if (auth.isAuthenticated) return defaultView;
    return "landing";
  }, [auth.isAuthenticated, defaultView, demoMode, role, viewOverride]);

  const handleSignOut = () => {
    void signOutCognito(auth);
  };

  const navigate = (view: AppView) => {
    if (view === "landing" && auth.isAuthenticated) {
      handleSignOut();
      return;
    }
    if (auth.isAuthenticated && canAccessView(role, view)) {
      setViewOverride(view);
      return;
    }
    if (demoMode && !auth.isAuthenticated) {
      setViewOverride(view);
    }
  };

  const dashboardProps = {
    onNavigate: navigate,
    allowedViews,
    onSignOut: handleSignOut,
    accessToken: auth.user?.access_token ?? "",
  };

  if (!cognitoEnv.ok) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background:
            "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
          color: D.text,
          fontFamily: "var(--font-sans)",
          padding: 48,
          maxWidth: 640,
        }}
      >
        <h2 style={{ marginTop: 0 }}>Cognito not configured</h2>
        <p style={{ color: D.muted }}>
          Missing environment variables in the repo root <code>.env</code>:
        </p>
        <ul>
          {cognitoEnv.missing.map((key) => (
            <li key={key}>
              <code>{key}</code>
            </li>
          ))}
        </ul>
        <p style={{ color: D.muted, fontSize: 14 }}>
          Restart <code>npm run dev</code> after updating <code>.env</code>.
        </p>
      </div>
    );
  }

  if (auth.isLoading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background:
            "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
          color: D.muted,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-sans)",
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
          background:
            "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
          color: D.red,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-sans)",
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
    return <AdminDashboard {...dashboardProps} />;
  }
  if (activeView === "professor") {
    return <ProfessorDashboard {...dashboardProps} />;
  }
  if (activeView === "student") {
    return <StudentInterface {...dashboardProps} />;
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background:
          "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
        color: D.text,
        fontFamily: "var(--font-sans)",
        padding: 48,
      }}
    >
      <p>Signed in as {auth.user?.profile.email as string}</p>
      <p>No Cognito group assigned. Contact an administrator.</p>
      <button
        type="button"
        onClick={handleSignOut}
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
