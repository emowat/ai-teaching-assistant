import * as vscode from 'vscode';
import type { CognitoAuthConfig } from './auth/types';

function readWorkspaceString(key: string): string | undefined {
    const value = vscode.workspace.getConfiguration('codingRabbit').get<string>(key);
    const trimmed = value?.trim();
    return trimmed ? trimmed : undefined;
}

function readEnvString(names: string[]): string | undefined {
    for (const name of names) {
        const value = process.env[name]?.trim();
        if (value) {
            return value;
        }
    }
    return undefined;
}

function trimTrailingSlash(value: string): string {
    return value.replace(/\/$/, '');
}

function trimApiChatSuffix(value: string): string {
    if (value.endsWith('/api/chat')) {
        return value.slice(0, -'/api/chat'.length);
    }
    return value;
}

export function resolveApiBaseUrl(): string {
    const candidate =
        readEnvString(['RAG_ENG_URL', 'RAG_ENG_API_BASE_URL']) ??
        readWorkspaceString('apiUrl') ??
        readWorkspaceString('apiBaseUrl');

    if (!candidate) {
        return 'http://host.docker.internal:8001';
    }

    return trimTrailingSlash(trimApiChatSuffix(candidate));
}

export function resolveChatApiUrl(): string {
    return `${resolveApiBaseUrl()}/api/chat`;
}

function buildDefaultExtensionCallback(extensionId: string, pathSuffix: string): string {
    return `vscode://${extensionId}${pathSuffix}`;
}

export function resolveCognitoAuthConfig(extensionId: string): CognitoAuthConfig | null {
    const enabled = vscode.workspace.getConfiguration('codingRabbit').get<boolean>('auth.enabled');
    if (enabled === false) {
        return null;
    }

    const domain =
        readWorkspaceString('cognitoDomain') ??
        readEnvString(['VITE_COGNITO_DOMAIN', 'COGNITO_DOMAIN']);
    const region =
        readWorkspaceString('cognitoRegion') ??
        readEnvString(['COGNITO_REGION']);
    const userPoolId =
        readWorkspaceString('cognitoUserPoolId') ??
        readEnvString(['COGNITO_USER_POOL_ID']);
    const clientId =
        readWorkspaceString('cognitoClientId') ??
        readEnvString(['COGNITO_APP_CLIENT_ID']);
    const scopesRaw =
        readWorkspaceString('cognitoScopes') ??
        readEnvString(['COGNITO_SCOPES']);

    if (!domain || !region || !userPoolId || !clientId) {
        return null;
    }

    const redirectUri =
        readWorkspaceString('cognitoRedirectUri') ??
        readEnvString(['COGNITO_REDIRECT_URI']) ??
        buildDefaultExtensionCallback(extensionId, '/auth/callback');
    const logoutUri =
        readWorkspaceString('cognitoLogoutUri') ??
        readEnvString(['COGNITO_LOGOUT_URI']) ??
        buildDefaultExtensionCallback(extensionId, '/auth/logout');

    return {
        domain: trimTrailingSlash(domain),
        region,
        userPoolId,
        clientId,
        scopes: scopesRaw ? scopesRaw.split(/\s+/).filter(Boolean) : ['openid', 'email', 'profile'],
        redirectUri,
        logoutUri,
    };
}
