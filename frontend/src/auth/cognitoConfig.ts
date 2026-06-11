export const cognitoAuthConfig = {
  authority: `https://cognito-idp.${import.meta.env.COGNITO_REGION}.amazonaws.com/${import.meta.env.COGNITO_USER_POOL_ID}`,
  client_id: import.meta.env.COGNITO_APP_CLIENT_ID as string,
  redirect_uri: import.meta.env.VITE_COGNITO_REDIRECT_URI as string,
  post_logout_redirect_uri: import.meta.env.VITE_COGNITO_LOGOUT_URI as string,
  response_type: "code",
  scope: "openid email profile",
};
