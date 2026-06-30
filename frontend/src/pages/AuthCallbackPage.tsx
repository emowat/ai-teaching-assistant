import { useAuth } from "react-oidc-context";
import { D } from "../design/tokens";

export function AuthCallbackPage() {
  const auth = useAuth();

  if (auth.isLoading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background:
            "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
          color: D.text,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-sans)",
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
          background:
            "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
          color: D.red,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-sans)",
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
        background:
          "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
        color: D.text,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-sans)",
      }}
    >
      Redirecting...
    </div>
  );
}
