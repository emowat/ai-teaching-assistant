import type { AuthContextProps } from "react-oidc-context";
import { getLogoutUri } from "./cognitoConfig";

/**
 * Cognito hosted UI logout expects `logout_uri`, not OIDC `post_logout_redirect_uri`.
 * oidc-client-ts signoutRedirect sends the wrong param and Cognito returns 400.
 */
export async function signOutCognito(auth: AuthContextProps): Promise<void> {
  const clientId = import.meta.env.COGNITO_APP_CLIENT_ID as string;
  const domain = import.meta.env.VITE_COGNITO_DOMAIN as string;
  const logoutUri = getLogoutUri();

  await auth.removeUser();

  const url = new URL("/logout", domain);
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("logout_uri", logoutUri);

  window.location.assign(url.toString());
}
