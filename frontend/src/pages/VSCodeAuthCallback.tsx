import { useState } from "react";
import { D } from "../design/tokens";

export function VSCodeAuthCallback({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background:
          "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
        color: D.text,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-sans)",
        padding: "2rem",
      }}
    >
      <div
        style={{
          background: "#fff",
          padding: "3rem",
          borderRadius: "16px",
          boxShadow: "0 10px 40px rgba(0,0,0,0.05)",
          maxWidth: "500px",
          width: "100%",
          textAlign: "center",
        }}
      >
        <div style={{ marginBottom: "1.5rem" }}>
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke={D.green} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
        </div>
        <h1 style={{ fontSize: "1.5rem", fontWeight: "bold", marginBottom: "1rem", color: D.text }}>
          VS Code Authentication Successful!
        </h1>
        <p style={{ color: D.muted, marginBottom: "2rem", lineHeight: "1.5" }}>
          To complete your sign-in, please copy the authorization code below and paste it back into your VS Code extension.
        </p>
        
        <div 
          style={{ 
            display: "flex", 
            gap: "0.5rem",
            marginBottom: "1rem"
          }}
        >
          <input 
            type="text" 
            value={code} 
            readOnly 
            style={{
              flex: 1,
              padding: "0.75rem 1rem",
              borderRadius: "8px",
              border: `1px solid ${D.border}`,
              background: D.surface,
              fontFamily: "monospace",
              fontSize: "0.9rem",
              color: D.text,
              outline: "none"
            }}
          />
          <button
            onClick={handleCopy}
            style={{
              padding: "0.75rem 1.5rem",
              borderRadius: "8px",
              border: "none",
              background: copied ? D.green : D.orange,
              color: "#fff",
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.2s",
            }}
          >
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
        
        <p style={{ fontSize: "0.85rem", color: D.dim }}>
          You can safely close this window after pasting the code.
        </p>
      </div>
    </div>
  );
}
