export interface CognitoEnvStatus {
  ok: boolean;
  missing: string[];
}

export function validateCognitoEnv(): CognitoEnvStatus {
  const required = [
    "COGNITO_REGION",
    "COGNITO_USER_POOL_ID",
    "COGNITO_APP_CLIENT_ID",
    "VITE_COGNITO_DOMAIN",
    "VITE_COGNITO_REDIRECT_URI",
    "VITE_COGNITO_LOGOUT_URI",
  ] as const;

  const missing = required.filter((key) => {
    const value = import.meta.env[key];
    return typeof value !== "string" || value.trim() === "";
  });

  return { ok: missing.length === 0, missing: [...missing] };
}
