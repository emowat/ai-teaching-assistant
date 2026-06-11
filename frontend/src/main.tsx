import { createRoot } from "react-dom/client";
import { AuthProvider } from "react-oidc-context";
import { createCognitoAuthConfig } from "./auth/cognitoConfig";
import App from "./App.tsx";
import "./index.css";

// StrictMode disabled: it double-mounts AuthProvider in dev and breaks OIDC state handling.
const cognitoAuthConfig = createCognitoAuthConfig();

// After Cognito logout redirect, land on home (not /logout).
if (window.location.pathname === "/logout") {
  window.history.replaceState({}, document.title, "/");
}

createRoot(document.getElementById("root")!).render(
  <AuthProvider
    {...cognitoAuthConfig}
    onSigninCallback={() => {
      window.history.replaceState({}, document.title, "/");
    }}
  >
    <App />
  </AuthProvider>
);
