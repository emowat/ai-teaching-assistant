import { WebStorageStateStore, type UserManagerSettings } from "oidc-client-ts";

/** Must match Cognito app client callback URLs exactly (from root .env). */
export function getRedirectUri(): string {
  return import.meta.env.VITE_COGNITO_REDIRECT_URI as string;
}

export function getLogoutUri(): string {
  return import.meta.env.VITE_COGNITO_LOGOUT_URI as string;
}

export function getRedirectOrigin(): string {
  return new URL(getRedirectUri()).origin;
}

/** True when the browser origin differs from the configured callback origin. */
export function hasOriginMismatch(): boolean {
  if (typeof window === "undefined") return false;
  return window.location.origin !== getRedirectOrigin();
}

export function createCognitoAuthConfig(): UserManagerSettings {
  const storage = new WebStorageStateStore({ store: window.sessionStorage });

  return {
    authority: `https://cognito-idp.${import.meta.env.COGNITO_REGION}.amazonaws.com/${import.meta.env.COGNITO_USER_POOL_ID}`,
    client_id: import.meta.env.COGNITO_APP_CLIENT_ID as string,
    redirect_uri: getRedirectUri(),
    post_logout_redirect_uri: getLogoutUri(),
    response_type: "code",
    scope: "openid email profile",
    automaticSilentRenew: true,
    userStore: storage,
    stateStore: storage,
  };
}
