import * as vscode from 'vscode';
import { TAChatViewProvider } from './TAChatViewProvider';
import { trackTerminal } from './TerminalTracker';
import { createPatch } from 'diff';
import * as crypto from 'crypto';
import { CognitoAuthService } from './auth/CognitoAuthService';

export const pasteStatusByUri = new Map<string, number>();
const previousTextByUri = new Map<string, string>();

export async function activate(context: vscode.ExtensionContext) {
    console.log('CodingRabbit extension activated.');

    const authService = new CognitoAuthService(context);
    await authService.initialize();

    const uriHandler = vscode.window.registerUriHandler({
        handleUri: async (uri: vscode.Uri) => {
            await authService.handleUri(uri);
        },
    });

    const provider = new TAChatViewProvider(context.extensionUri, pasteStatusByUri, context, authService);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(TAChatViewProvider.viewType, provider),
        uriHandler,
        vscode.commands.registerCommand('coding-rabbit.signIn', async () => {
            await authService.signIn();
        }),
        vscode.commands.registerCommand('coding-rabbit.signOut', async () => {
            await authService.signOutEverywhere();
        }),
        vscode.commands.registerCommand('coding-rabbit.resetAuth', async () => {
            await authService.signOutEverywhere();
            await authService.signIn();
        })
    );

    const output = vscode.window.createOutputChannel("TA Anti-Cheat Logs");

    // Capture initial state of already open files.
    for (const document of vscode.workspace.textDocuments) {
        if (document.uri.scheme === "file") {
            previousTextByUri.set(document.uri.toString(), document.getText());
        }
    }

    const openListener = vscode.workspace.onDidOpenTextDocument((document) => {
        if (document.uri.scheme === "file") {
            previousTextByUri.set(document.uri.toString(), document.getText());
        }
    });

    const closeListener = vscode.workspace.onDidCloseTextDocument((document) => {
        previousTextByUri.delete(document.uri.toString());
        pasteStatusByUri.delete(document.uri.toString());
    });

    const recentlyDeletedHashes = new Set<string>();

    const changeListener = vscode.workspace.onDidChangeTextDocument((event) => {
        if (event.contentChanges.length === 0) {
            return;
        }

        const document = event.document;
        if (document.uri.scheme !== "file") {
            return;
        }

        const uri = document.uri.toString();
        const before = previousTextByUri.get(uri) ?? "";
        const after = document.getText();

        let likelyPaste = false;
        let pastedCharCount = 0;

        for (const change of event.contentChanges) {
            // 1. Record significant deletions (to detect cut-and-paste or vim 'dd' -> 'p')
            if (change.rangeLength > 10 && change.text.trim().length === 0) {
                const deletedText = before.substring(change.rangeOffset, change.rangeOffset + change.rangeLength);
                const normalizedDeleted = deletedText.replace(/\s+/g, '');
                if (normalizedDeleted.length > 10) {
                    const hash = crypto.createHash('md5').update(normalizedDeleted).digest('hex');
                    recentlyDeletedHashes.add(hash);
                    // Prevent memory leak
                    if (recentlyDeletedHashes.size > 20) {
                        recentlyDeletedHashes.delete(recentlyDeletedHashes.values().next().value!);
                    }
                }
            }

            // 2. Check for significant insertions (pastes)
            const insertedText = change.text.trim();
            if (insertedText.length > 30 || (change.text.includes("\n") && insertedText.length > 15)) {
                // If the exact same text was recently deleted OR already exists elsewhere in the file, it's an internal move/copy.
                const normalizedInserted = insertedText.replace(/\s+/g, '');
                const insertedHash = crypto.createHash('md5').update(normalizedInserted).digest('hex');

                // Also ignore whitespace for the internal copy check
                const normalizedBefore = before.replace(/\s+/g, '');
                const isInternalCopy = normalizedBefore.includes(normalizedInserted);

                const isInternalCut = recentlyDeletedHashes.has(insertedHash);

                if (!isInternalCopy && !isInternalCut) {
                    likelyPaste = true;
                    pastedCharCount += change.text.length;
                }
            } else if (change.rangeLength > 30 && change.text.trim().length === 0) {
                // This is likely an Undo of a previous paste or a large deletion
                // This is likely an Undo of a previous paste or a large deletion
                pasteStatusByUri.set(uri, 0);
            }
        }

        if (likelyPaste) {
            const currentCount = pasteStatusByUri.get(uri) || 0;
            pasteStatusByUri.set(uri, currentCount + pastedCharCount);
            const patch = createPatch(document.fileName, before, after, "before", "after");
            output.appendLine("=".repeat(80));
            output.appendLine(`File: ${document.fileName}`);
            output.appendLine(`Likely EXTERNAL paste detected at ${new Date().toLocaleTimeString()}`);
            output.appendLine(patch);
        }

        previousTextByUri.set(uri, after);
    });

    context.subscriptions.push(output, openListener, closeListener, changeListener);

    context.subscriptions.push(
        vscode.commands.registerCommand('coding-rabbit.startTerminal', () => {
            trackTerminal();
        }),
        vscode.commands.registerCommand('coding-rabbit.openChatView', async () => {
            await vscode.commands.executeCommand('workbench.view.extension.coding-rabbit-explorer');
        })
    );

    // Removed aggressive terminal disposal so startup error logs (from devcontainers, etc) remain visible.
    // The TA Console will simply be focused over them instead.

    // Automatically start it immediately
    trackTerminal(() => provider.recordShellActivity());

    // Aggressively hunt down Copilot Chat popups during the first 20 seconds of startup.
    // GitHub Codespaces injects Copilot asynchronously and it usually opens in the Secondary Side Bar (Auxiliary Bar)
    // or as an editor tab. We want to close these by default to avoid confusing testers.
    let attempts = 0;
    const squashCopilotInterval = setInterval(() => {
        attempts++;
        if (attempts > 10) { // 10 * 2s = 20 seconds
            clearInterval(squashCopilotInterval);
            return;
        }

        // Close the Secondary Side Bar (where Copilot Chat usually lives)
        vscode.commands.executeCommand('workbench.action.closeAuxiliaryBar');

        // Close any active Copilot Chat editor tabs
        for (const group of vscode.window.tabGroups.all) {
            for (const tab of group.tabs) {
                if (tab.label.includes('Copilot') || tab.label.includes('Chat')) {
                    // Only close it if it's NOT our own chat file if we ever use one
                    vscode.window.tabGroups.close(tab);
                }
            }
        }

        // Ensure our chat has focus in the primary sidebar
        vscode.commands.executeCommand('coding-rabbit.chatView.focus');
    }, 2000);

    // Automatically pop open the TA Chat window in the sidebar initially
    vscode.commands.executeCommand('coding-rabbit.openChatView');
}

export function deactivate() {}
