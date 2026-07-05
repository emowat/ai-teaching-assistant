export type CognitoAuthStatus =
    | 'unconfigured'
    | 'signed_out'
    | 'signing_in'
    | 'signed_in'
    | 'refreshing'
    | 'error';

export interface CognitoAuthConfig {
    domain: string;
    region: string;
    userPoolId: string;
    clientId: string;
    scopes: string[];
    redirectUri: string;
    logoutUri: string;
}

export interface CognitoAuthSnapshot {
    status: CognitoAuthStatus;
    message?: string;
    expiresAt?: number;
    email?: string;
}

export interface CognitoTokenSession {
    accessToken: string;
    refreshToken?: string;
    idToken?: string;
    expiresAt: number;
}
