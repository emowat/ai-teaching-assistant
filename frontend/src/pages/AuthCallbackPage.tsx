import { useAuth } from "react-oidc-context";
import { D } from "../design/tokens";

export function AuthCallbackPage() {
  const auth = useAuth();

  if (auth.isLoading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background: D.bg,
          color: D.text,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        Completing sign in...
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
        }}
      >
        Sign-in failed: {auth.error.message}
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: D.bg,
        color: D.text,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      Redirecting...
    </div>
  );
}
