import * as vscode from 'vscode';
import { buildAuthorizeUrl, buildLogoutUrl, buildTokenEndpointUrl, generateCodeChallenge, generateCodeVerifier } from './pkce';
import type {
    CognitoAuthConfig,
    CognitoAuthSnapshot,
    CognitoTokenSession,
} from './types';

const AUTH_SESSION_KEY = 'codingRabbit.cognito.authSession';

interface TokenResponse {
    access_token: string;
    refresh_token?: string;
    id_token?: string;
    expires_in?: number;
    token_type?: string;
}

function nowMs(): number {
    return Date.now();
}

function isSessionExpired(session: CognitoTokenSession, skewMs = 60_000): boolean {
    return session.expiresAt <= nowMs() + skewMs;
}

export class CognitoAuthService {
    private static _outputChannel?: vscode.OutputChannel;
    private readonly _authStateEmitter = new vscode.EventEmitter<CognitoAuthSnapshot>();
    private readonly _config: CognitoAuthConfig | null;
    private _snapshot: CognitoAuthSnapshot = { status: 'signed_out' };
    private _pendingState?: string;
    private _pendingVerifier?: string;
    private _session: CognitoTokenSession | null = null;

    public readonly onDidChangeAuthState = this._authStateEmitter.event;

    constructor(private readonly _context: vscode.ExtensionContext) {
        this._config = this._resolveConfig();
    }

    public async initialize(): Promise<void> {
        if (!this._config) {
            this._setSnapshot({ status: 'unconfigured', message: 'Cognito authentication is not configured.' });
            return;
        }

        const session = await this._readSession();
        if (session) {
            this._session = session;
            if (isSessionExpired(session) && !session.refreshToken) {
                await this.signOut();
                return;
            }
            this._setSnapshot({ status: 'signed_in', expiresAt: session.expiresAt });
            return;
        }

        this._setSnapshot({ status: 'signed_out' });
    }

    public get snapshot(): CognitoAuthSnapshot {
        return this._snapshot;
    }

    public get config(): CognitoAuthConfig | null {
        return this._config;
    }

    public isConfigured(): boolean {
        return this._config !== null;
    }

    public async signIn(): Promise<void> {
        if (!this._config) {
            this._setSnapshot({ status: 'unconfigured', message: 'Cognito authentication is not configured.' });
            throw new Error('Cognito authentication is not configured.');
        }

        const isWeb = vscode.env.uiKind === vscode.UIKind.Web;
        const state = isWeb ? `vscode-${this._randomState()}` : this._randomState();
        const verifier = generateCodeVerifier();
        const challenge = generateCodeChallenge(verifier);

        this._pendingState = state;
        this._pendingVerifier = verifier;
        this._setSnapshot({ status: 'signing_in', message: 'Opening Cognito login in your browser.' });

        const authorizeUrl = buildAuthorizeUrl(this._config, state, challenge);
        const opened = await vscode.env.openExternal(vscode.Uri.parse(authorizeUrl));
        if (!opened) {
            this._pendingState = undefined;
            this._pendingVerifier = undefined;
            this._setSnapshot({ status: 'error', message: 'Unable to open the browser for Cognito sign-in.' });
            throw new Error('Unable to open the browser for Cognito sign-in.');
        }

        if (isWeb) {
            const manualCode = await vscode.window.showInputBox({
                prompt: 'Please paste the authorization code from your browser',
                ignoreFocusOut: true
            });
            
            if (!manualCode) {
                this._pendingState = undefined;
                this._pendingVerifier = undefined;
                this._setSnapshot({ status: 'error', message: 'Authentication cancelled (no code provided).' });
                return;
            }

            try {
                this._setSnapshot({ status: 'signing_in', message: 'Exchanging code for session...' });
                const session = await this._exchangeCodeForSession(manualCode, verifier);
                this._session = session;
                await this._storeSession(session);
                this._setSnapshot({ status: 'signed_in', expiresAt: session.expiresAt, message: undefined });
            } catch (err) {
                this._pendingState = undefined;
                this._pendingVerifier = undefined;
                this._setSnapshot({ status: 'error', message: err instanceof Error ? err.message : 'Unable to complete login.' });
            }
        }
    }

    public async signOut(): Promise<void> {
        this._pendingState = undefined;
        this._pendingVerifier = undefined;
        this._session = null;
        await this._context.secrets.delete(AUTH_SESSION_KEY);
        this._setSnapshot({ status: this._config ? 'signed_out' : 'unconfigured', message: undefined, expiresAt: undefined });
    }

    public async signOutEverywhere(): Promise<void> {
        await this.signOut();
        await this.openLogoutInBrowser().catch(() => undefined);
    }

    public async handleUri(uri: vscode.Uri): Promise<boolean> {
        if (!this._config) {
            return false;
        }

        const rawUri = uri.toString(true);
        CognitoAuthService.getOutputChannel().appendLine(`[Auth Callback] Received URI: ${rawUri}`);

        const parsed = new URL(uri.toString());
        if (parsed.pathname !== '/auth/callback' && parsed.pathname !== '/auth/logout') {
            return false;
        }

        if (parsed.pathname === '/auth/logout') {
            await this.signOut();
            return true;
        }

        const error = parsed.searchParams.get('error');
        if (error) {
            const description = parsed.searchParams.get('error_description') ?? error;
            this._pendingState = undefined;
            this._pendingVerifier = undefined;
            this._setSnapshot({ status: 'error', message: `Cognito login failed: ${description}` });
            return true;
        }

        const queryParams = new URLSearchParams(uri.query);
        const fragmentParams = uri.fragment ? new URLSearchParams(uri.fragment.replace(/^#/, '')) : null;
        const code =
            queryParams.get('code') ??
            fragmentParams?.get('code') ??
            parsed.searchParams.get('code');
        const state =
            queryParams.get('state') ??
            fragmentParams?.get('state') ??
            parsed.searchParams.get('state');
        if (!code || !state) {
            this._setSnapshot({
                status: 'error',
                message: `Cognito callback is missing code or state. Query: ${uri.query || '(empty)'}`,
            });
            return true;
        }

        if (!this._pendingState || !this._pendingVerifier || state !== this._pendingState) {
            this._setSnapshot({ status: 'error', message: 'Cognito callback state did not match the sign-in request.' });
            this._pendingState = undefined;
            this._pendingVerifier = undefined;
            return true;
        }

        try {
            this._setSnapshot({ status: 'refreshing', message: 'Finishing Cognito sign-in.' });
            const session = await this._exchangeCodeForSession(code, this._pendingVerifier);
            this._pendingState = undefined;
            this._pendingVerifier = undefined;
            this._session = session;
            await this._storeSession(session);
            this._setSnapshot({ status: 'signed_in', expiresAt: session.expiresAt, message: undefined });
            return true;
        } catch (err) {
            this._pendingState = undefined;
            this._pendingVerifier = undefined;
            this._session = null;
            await this._context.secrets.delete(AUTH_SESSION_KEY);
            this._setSnapshot({
                status: 'error',
                message: err instanceof Error ? err.message : 'Unable to finish Cognito sign-in.',
            });
            return true;
        }
    }

    public async getAccessToken(): Promise<string | undefined> {
        const session = await this._ensureSession();
        return session?.accessToken;
    }

    public async fetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
        const token = await this.getAccessToken();
        const headers = new Headers(init.headers ?? {});
        if (token) {
            headers.set('Authorization', `Bearer ${token}`);
        }
        return fetch(input, {
            ...init,
            headers,
        });
    }

    public async openLogoutInBrowser(): Promise<void> {
        if (!this._config) {
            return;
        }
        await vscode.env.openExternal(vscode.Uri.parse(buildLogoutUrl(this._config)));
    }

    private async _readSession(): Promise<CognitoTokenSession | null> {
        const raw = await this._context.secrets.get(AUTH_SESSION_KEY);
        if (!raw) {
            return null;
        }

        try {
            const parsed = JSON.parse(raw) as CognitoTokenSession;
            if (typeof parsed.accessToken !== 'string' || typeof parsed.expiresAt !== 'number') {
                return null;
            }
            return parsed;
        } catch {
            return null;
        }
    }


    private async _storeSession(session: CognitoTokenSession): Promise<void> {
        await this._context.secrets.store(AUTH_SESSION_KEY, JSON.stringify(session));
    }

    private async _ensureSession(): Promise<CognitoTokenSession | null> {
        if (!this._config) {
            return null;
        }

        if (!this._session) {
            this._session = await this._readSession();
        }

        if (!this._session) {
            return null;
        }

        if (!isSessionExpired(this._session)) {
            return this._session;
        }

        if (!this._session.refreshToken) {
            await this.signOut();
            return null;
        }

        try {
            const refreshed = await this._refreshSession(this._session.refreshToken);
            this._session = refreshed;
            await this._storeSession(refreshed);
            this._setSnapshot({ status: 'signed_in', expiresAt: refreshed.expiresAt, message: undefined });
            return refreshed;
        } catch (err) {
            this._session = null;
            await this._context.secrets.delete(AUTH_SESSION_KEY);
            this._setSnapshot({
                status: 'error',
                message: err instanceof Error ? err.message : 'Unable to refresh Cognito session.',
            });
            return null;
        }
    }

    private async _exchangeCodeForSession(code: string, codeVerifier: string): Promise<CognitoTokenSession> {
        if (!this._config) {
            throw new Error('Cognito authentication is not configured.');
        }

        const tokenUrl = buildTokenEndpointUrl(this._config);
        const body = new URLSearchParams({
            grant_type: 'authorization_code',
            client_id: this._config.clientId,
            code,
            code_verifier: codeVerifier,
            redirect_uri: this._config.redirectUri,
        });

        const response = await fetch(tokenUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                Accept: 'application/json',
            },
            body: body.toString(),
        });

        if (!response.ok) {
            throw new Error(await this._extractErrorMessage(response, 'Unable to exchange the Cognito authorization code.'));
        }

        const json = (await response.json()) as TokenResponse;
        if (!json.access_token || typeof json.expires_in !== 'number') {
            throw new Error('Cognito token response was incomplete.');
        }

        return {
            accessToken: json.access_token,
            refreshToken: json.refresh_token,
            idToken: json.id_token,
            expiresAt: nowMs() + json.expires_in * 1000,
        };
    }

    private async _refreshSession(refreshToken: string): Promise<CognitoTokenSession> {
        if (!this._config) {
            throw new Error('Cognito authentication is not configured.');
        }

        const tokenUrl = buildTokenEndpointUrl(this._config);
        const body = new URLSearchParams({
            grant_type: 'refresh_token',
            client_id: this._config.clientId,
            refresh_token: refreshToken,
        });

        const response = await fetch(tokenUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                Accept: 'application/json',
            },
            body: body.toString(),
        });

        if (!response.ok) {
            throw new Error(await this._extractErrorMessage(response, 'Unable to refresh the Cognito session.'));
        }

        const json = (await response.json()) as TokenResponse;
        if (!json.access_token || typeof json.expires_in !== 'number') {
            throw new Error('Cognito refresh response was incomplete.');
        }

        return {
            accessToken: json.access_token,
            refreshToken,
            idToken: json.id_token,
            expiresAt: nowMs() + json.expires_in * 1000,
        };
    }

    private _resolveConfig(): CognitoAuthConfig | null {
        const extensionId = this._context.extension.id;
        return this._resolveConfigFromSettings(extensionId);
    }

    private _resolveConfigFromSettings(extensionId: string): CognitoAuthConfig | null {
        const config = vscode.workspace.getConfiguration('codingRabbit');
        const domain = config.get<string>('cognitoDomain')?.trim() || process.env.VITE_COGNITO_DOMAIN?.trim() || process.env.COGNITO_DOMAIN?.trim();
        const region = config.get<string>('cognitoRegion')?.trim() || process.env.COGNITO_REGION?.trim();
        const userPoolId = config.get<string>('cognitoUserPoolId')?.trim() || process.env.COGNITO_USER_POOL_ID?.trim();
        const clientId = config.get<string>('cognitoClientId')?.trim() || process.env.COGNITO_APP_CLIENT_ID?.trim();
        const scopesRaw = config.get<string>('cognitoScopes')?.trim() || process.env.COGNITO_SCOPES?.trim();
        const isWeb = vscode.env.uiKind === vscode.UIKind.Web;
        const redirectUri = config.get<string>('cognitoRedirectUri')?.trim() || process.env.COGNITO_REDIRECT_URI?.trim() || (isWeb ? 'https://www.codingrabbit.dev/auth/callback' : `vscode://${extensionId}/auth/callback`);
        const logoutUri = config.get<string>('cognitoLogoutUri')?.trim() || process.env.COGNITO_LOGOUT_URI?.trim() || `vscode://${extensionId}/auth/logout`;

        if (!domain || !region || !userPoolId || !clientId) {
            return null;
        }

        return {
            domain: domain.replace(/\/$/, ''),
            region,
            userPoolId,
            clientId,
            scopes: (scopesRaw ? scopesRaw.split(/\s+/) : ['openid', 'email', 'profile']).filter(Boolean),
            redirectUri,
            logoutUri,
        };
    }

    private _randomState(): string {
        return generateCodeVerifier(16);
    }

    private _setSnapshot(snapshot: Partial<CognitoAuthSnapshot> & Pick<CognitoAuthSnapshot, 'status'>): void {
        this._snapshot = {
            ...this._snapshot,
            ...snapshot,
        };
        this._authStateEmitter.fire(this._snapshot);
    }

    private async _extractErrorMessage(response: Response, fallback: string): Promise<string> {
        try {
            const text = await response.text();
            const trimmed = text.trim();
            if (!trimmed) {
                return `${fallback} (${response.status} ${response.statusText})`;
            }
            return `${fallback} (${response.status} ${response.statusText}): ${trimmed}`;
        } catch {
            return `${fallback} (${response.status} ${response.statusText})`;
        }
    }

    private static getOutputChannel(): vscode.OutputChannel {
        if (!this._outputChannel) {
            this._outputChannel = vscode.window.createOutputChannel("CodingRabbit Auth");
        }
        return this._outputChannel;
    }
}
