import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Read env vars from the repo root.
// Expose VITE_ (frontend-only) and COGNITO_ (shared with backend) prefixes.
export default defineConfig({
  plugins: [react()],
  envDir: path.resolve(__dirname, ".."),
  envPrefix: ["VITE_", "COGNITO_"],
});
