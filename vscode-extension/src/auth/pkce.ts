import * as crypto from 'crypto';
import type { CognitoAuthConfig } from './types';

function base64UrlEncode(input: Buffer): string {
    return input
        .toString('base64')
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/g, '');
}

export function generateCodeVerifier(length = 32): string {
    return base64UrlEncode(crypto.randomBytes(length));
}

export function generateCodeChallenge(verifier: string): string {
    return base64UrlEncode(crypto.createHash('sha256').update(verifier).digest());
}

export function buildAuthorizeUrl(
    config: CognitoAuthConfig,
    state: string,
    codeChallenge: string,
): string {
    const url = new URL('/oauth2/authorize', config.domain);
    url.searchParams.set('client_id', config.clientId);
    url.searchParams.set('response_type', 'code');
    url.searchParams.set('scope', config.scopes.join(' '));
    url.searchParams.set('redirect_uri', config.redirectUri);
    url.searchParams.set('state', state);
    url.searchParams.set('code_challenge', codeChallenge);
    url.searchParams.set('code_challenge_method', 'S256');
    return url.toString();
}

export function buildTokenEndpointUrl(config: CognitoAuthConfig): string {
    return new URL('/oauth2/token', config.domain).toString();
}

export function buildLogoutUrl(config: CognitoAuthConfig): string {
    const url = new URL('/logout', config.domain);
    url.searchParams.set('client_id', config.clientId);
    url.searchParams.set('logout_uri', config.logoutUri);
    return url.toString();
}
