import * as vscode from 'vscode';
import { TAChatViewProvider } from './TAChatViewProvider';
import { trackTerminal } from './TerminalTracker';
import { createPatch } from 'diff';
import * as crypto from 'crypto';

export const pasteStatusByUri = new Map<string, boolean>();
const previousTextByUri = new Map<string, string>();

export function activate(context: vscode.ExtensionContext) {
    console.log('Socratic TA extension activated.');

    const provider = new TAChatViewProvider(context.extensionUri, pasteStatusByUri);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(TAChatViewProvider.viewType, provider)
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

        for (const change of event.contentChanges) {
            // 1. Record significant deletions (to detect cut-and-paste or vim 'dd' -> 'p')
            if (change.rangeLength > 10 && change.text.trim().length === 0) {
                const deletedText = before.substring(change.rangeOffset, change.rangeOffset + change.rangeLength).trim();
                if (deletedText.length > 10) {
                    const hash = crypto.createHash('md5').update(deletedText).digest('hex');
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
                const insertedHash = crypto.createHash('md5').update(insertedText).digest('hex');
                const isInternalCopy = before.includes(insertedText);
                const isInternalCut = recentlyDeletedHashes.has(insertedHash);
                
                if (!isInternalCopy && !isInternalCut) {
                    likelyPaste = true;
                }
            }
        }

        if (likelyPaste) {
            pasteStatusByUri.set(uri, true);
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
        vscode.commands.registerCommand('socratic-ta.startTerminal', () => {
            trackTerminal();
        })
    );

    // Removed aggressive terminal disposal so startup error logs (from devcontainers, etc) remain visible.
    // The TA Console will simply be focused over them instead.
    
    // Automatically start it immediately
    trackTerminal();

    // Aggressively hunt down and uninstall Copilot programmatically to enforce Hard Mode
    setTimeout(() => {
        vscode.commands.executeCommand('workbench.extensions.uninstallExtension', 'github.copilot').then(() => {}, () => {});
        vscode.commands.executeCommand('workbench.extensions.uninstallExtension', 'github.copilot-chat').then(() => {}, () => {});
    }, 2000);

    // Automatically pop open the TA Chat window in the sidebar
    vscode.commands.executeCommand('socratic-ta.chatView.focus');
}

export function deactivate() {}
