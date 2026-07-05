const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildAuthorizeUrl,
  buildLogoutUrl,
  generateCodeChallenge,
  generateCodeVerifier,
} = require('../out/auth/pkce.js');

const config = {
  domain: 'https://us-east-1z5dab8wni.auth.us-east-1.amazoncognito.com',
  region: 'us-east-1',
  userPoolId: 'us-east-1_Z5DAb8wni',
  clientId: '5k11ek5do9l3p6vhpev3aifh0f',
  scopes: ['openid', 'email', 'profile'],
  redirectUri: 'vscode://berkeley.coding-rabbit/auth/callback',
  logoutUri: 'vscode://berkeley.coding-rabbit/auth/logout',
};

test('generateCodeVerifier returns a PKCE-safe value', () => {
  const verifier = generateCodeVerifier();
  assert.match(verifier, /^[A-Za-z0-9_-]+$/);
  assert.ok(verifier.length >= 43);
});

test('generateCodeChallenge matches the RFC7636 example', () => {
  const verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
  const challenge = generateCodeChallenge(verifier);
  assert.equal(challenge, 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
});

test('buildAuthorizeUrl includes PKCE and Cognito query parameters', () => {
  const url = new URL(buildAuthorizeUrl(config, 'state-123', 'challenge-456'));

  assert.equal(url.origin, 'https://us-east-1z5dab8wni.auth.us-east-1.amazoncognito.com');
  assert.equal(url.pathname, '/oauth2/authorize');
  assert.equal(url.searchParams.get('client_id'), config.clientId);
  assert.equal(url.searchParams.get('response_type'), 'code');
  assert.equal(url.searchParams.get('scope'), 'openid email profile');
  assert.equal(url.searchParams.get('redirect_uri'), config.redirectUri);
  assert.equal(url.searchParams.get('state'), 'state-123');
  assert.equal(url.searchParams.get('code_challenge'), 'challenge-456');
  assert.equal(url.searchParams.get('code_challenge_method'), 'S256');
});

test('buildLogoutUrl uses the Cognito logout endpoint', () => {
  const url = new URL(buildLogoutUrl(config));

  assert.equal(url.pathname, '/logout');
  assert.equal(url.searchParams.get('client_id'), config.clientId);
  assert.equal(url.searchParams.get('logout_uri'), config.logoutUri);
});
