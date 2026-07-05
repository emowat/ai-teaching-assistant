import * as vscode from 'vscode';
import { terminalBuffer, lastExitCode } from './TerminalTracker';
import * as Parser from 'web-tree-sitter';
import * as marked from 'marked';
import * as fs from 'fs';
import * as path from 'path';
import { CognitoAuthService } from './auth/CognitoAuthService';
import type { CognitoAuthConfig, CognitoAuthSnapshot } from './auth/types';
import { resolveApiBaseUrl, resolveChatApiUrl } from './extensionConfig';

export class TAChatViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'coding-rabbit.chatView';
    private _conversationHistory: {role: string, content: string}[] = [];
    private static _outputChannel: vscode.OutputChannel;
    private _parser?: Parser;
    private _cppLanguage?: Parser.Language;
    private _consecutiveTerminalErrors: number = 0;
    private _chatRequestsSinceLastEdit: number = 0;
    private _lastDocumentVersion: number = -1;
    private _hasGivenStyleNudge: boolean = false;
    private _hasSentWakeup: boolean = false;
    private _hasProactivelyAskedAboutPaste: boolean = false;
    private _adversarialWarningCount: number = 0;
    private _sessionId: string = Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
    
    private _totalElapsedSeconds: number = 0;
    private _isStopwatchPaused: boolean = false;
    
    private _activeEditorSeconds: number = 0;
    private _activeShellSeconds: number = 0;
    private _activeChatSeconds: number = 0;
    
    // Delta trackers for backend telemetry (Homework Assist)
    private _homeworkDeltaEditorSeconds: number = 0;
    private _homeworkDeltaShellSeconds: number = 0;
    private _homeworkDeltaChatSeconds: number = 0;
    private _homeworkDeltaRewardsGiven: number = 0;
    private _homeworkDeltaStyleNudges: number = 0;
    
    // Delta trackers for backend telemetry (Study Assist)
    private _studyDeltaEditorSeconds: number = 0;
    private _studyDeltaShellSeconds: number = 0;
    private _studyDeltaChatSeconds: number = 0;
    private _studyDeltaRewardsGiven: number = 0;
    private _studyDeltaStyleNudges: number = 0;
    
    private _currentMode: string = 'Homework Assist';
    
    private _lastActivityTime: number = Date.now();
    private _lastActivityType: 'editor' | 'shell' | 'chat' = 'editor';
    private _activityInterval: NodeJS.Timeout;
    private _currentWebview?: vscode.Webview;
    private _authStateSubscription?: vscode.Disposable;

    private async getParser(): Promise<Parser> {
        if (this._parser && this._cppLanguage) {
            return this._parser;
        }
        await Parser.init();
        this._parser = new Parser();
        const wasmPath = vscode.Uri.joinPath(this._extensionUri, 'media', 'wasm', 'tree-sitter-cpp.wasm').fsPath;
        this._cppLanguage = await Parser.Language.load(wasmPath);
        this._parser.setLanguage(this._cppLanguage);
        return this._parser;
    }

    public static getOutputChannel(): vscode.OutputChannel {
        if (!this._outputChannel) {
            this._outputChannel = vscode.window.createOutputChannel("CodingRabbit Logs");
        }
        return this._outputChannel;
    }

    constructor(
        private readonly _extensionUri: vscode.Uri,
        private readonly _pasteStatusByUri: Map<string, number>,
        private readonly _context: vscode.ExtensionContext,
        private readonly _authService: CognitoAuthService
    ) {
        this._authStateSubscription = this._authService.onDidChangeAuthState(() => {
            if (this._currentWebview) {
                void this._renderCurrentWebview();
            }

            const status = this._authService.snapshot.status;
            if (status === 'signed_out' || status === 'unconfigured') {
                this._conversationHistory = [];
                this._hasGivenStyleNudge = false;
                this._hasSentWakeup = false;
                this._hasProactivelyAskedAboutPaste = false;
                this._adversarialWarningCount = 0;
                this._sessionId = Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
            }
        });
        this._context.subscriptions.push(this._authStateSubscription);

        // Activity listeners
        vscode.window.onDidChangeTextEditorSelection((event) => {
            if (event.textEditor.document.uri.scheme === 'file') {
                this._recordActivity('editor');
            }
        }, null, this._context.subscriptions);
        
        let pasteTimeout: NodeJS.Timeout | undefined;
        vscode.workspace.onDidChangeTextDocument((event) => {
            if (event.document.uri.scheme !== 'file') return;
            
            this._recordActivity('editor');
            const uri = event.document.uri.toString();
            
            if (pasteTimeout) clearTimeout(pasteTimeout);
            
            pasteTimeout = setTimeout(() => {
                if (!this._hasProactivelyAskedAboutPaste && (this._pasteStatusByUri.get(uri) || 0) > 0) {
                    this._hasProactivelyAskedAboutPaste = true; // Ask exactly once per session
                    if (this._currentWebview) {
                        this._handleAskTA("[IDE_EVENT: The student just pasted a large block of external code. Proactively ask them what part of it they are focusing on, or if they understand what it does. Do not give them the solution.]", "Homework Assist", { webview: this._currentWebview } as any, true);
                    }
                }
            }, 2500);
        }, null, this._context.subscriptions);
        vscode.window.onDidChangeActiveTerminal(() => this._recordActivity('shell'), null, this._context.subscriptions);
        vscode.window.onDidChangeTerminalState(() => this._recordActivity('shell'), null, this._context.subscriptions);
        
        // Auto-timer loop
        this._activityInterval = setInterval(() => {
            const timeSinceActivity = Date.now() - this._lastActivityTime;
            const shouldBePaused = timeSinceActivity > 5000;
            
            if (!shouldBePaused) {
                // Increment specific bucket
                if (this._lastActivityType === 'editor') {
                    this._activeEditorSeconds++;
                    if (this._currentMode === 'Study Assist') this._studyDeltaEditorSeconds++;
                    else this._homeworkDeltaEditorSeconds++;
                } else if (this._lastActivityType === 'shell') {
                    this._activeShellSeconds++;
                    if (this._currentMode === 'Study Assist') this._studyDeltaShellSeconds++;
                    else this._homeworkDeltaShellSeconds++;
                } else if (this._lastActivityType === 'chat') {
                    this._activeChatSeconds++;
                    if (this._currentMode === 'Study Assist') this._studyDeltaChatSeconds++;
                    else this._homeworkDeltaChatSeconds++;
                }
                
                this._totalElapsedSeconds = this._activeEditorSeconds + this._activeShellSeconds + this._activeChatSeconds;
                
                if (this._isStopwatchPaused) {
                    this._isStopwatchPaused = false;
                    this._notifyStopwatchState();
                }
            } else {
                if (!this._isStopwatchPaused) {
                    this._isStopwatchPaused = true;
                    this._notifyStopwatchState();
                    this._flushTelemetry();
                }
            }
        }, 1000);
        
        // Out-of-band telemetry sync loop (every 15 minutes)
        setInterval(() => {
            this._flushTelemetry();
        }, 900000);
    }
    
    private async _flushTelemetry() {
        const hasHomeworkMetrics = this._homeworkDeltaEditorSeconds > 0 || this._homeworkDeltaShellSeconds > 0 || this._homeworkDeltaChatSeconds > 0;
        const hasStudyMetrics = this._studyDeltaEditorSeconds > 0 || this._studyDeltaShellSeconds > 0 || this._studyDeltaChatSeconds > 0;
        
        if (!hasHomeworkMetrics && !hasStudyMetrics) return;

        const telemetryUrl = `${resolveApiBaseUrl()}/api/telemetry`;

        try {
            if (hasHomeworkMetrics) {
                await this._authService.fetch(telemetryUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: this._sessionId,
                        mode: "Homework Assist",
                        engagement_metrics: {
                            active_editor_seconds: this._homeworkDeltaEditorSeconds,
                            active_shell_seconds: this._homeworkDeltaShellSeconds,
                            active_chat_seconds: this._homeworkDeltaChatSeconds,
                            rewards_given: this._homeworkDeltaRewardsGiven,
                            style_nudges: this._homeworkDeltaStyleNudges
                        }
                    })
                });
                this._homeworkDeltaEditorSeconds = 0;
                this._homeworkDeltaShellSeconds = 0;
                this._homeworkDeltaChatSeconds = 0;
                this._homeworkDeltaRewardsGiven = 0;
                this._homeworkDeltaStyleNudges = 0;
            }

            if (hasStudyMetrics) {
                await this._authService.fetch(telemetryUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: this._sessionId,
                        mode: "Study Assist",
                        engagement_metrics: {
                            active_editor_seconds: this._studyDeltaEditorSeconds,
                            active_shell_seconds: this._studyDeltaShellSeconds,
                            active_chat_seconds: this._studyDeltaChatSeconds,
                            rewards_given: this._studyDeltaRewardsGiven,
                            style_nudges: this._studyDeltaStyleNudges
                        }
                    })
                });
                this._studyDeltaEditorSeconds = 0;
                this._studyDeltaShellSeconds = 0;
                this._studyDeltaChatSeconds = 0;
                this._studyDeltaRewardsGiven = 0;
                this._studyDeltaStyleNudges = 0;
            }
        } catch (e) {
            TAChatViewProvider.getOutputChannel().appendLine(`[Telemetry Error]: ${e}`);
        }
    }

    private _notifyStopwatchState() {
        if (this._currentWebview) {
            this._currentWebview.postMessage({ 
                type: 'syncStopwatch', 
                isPaused: this._isStopwatchPaused, 
                elapsedSeconds: this._totalElapsedSeconds 
            });
        }
        const outputChannel = TAChatViewProvider.getOutputChannel();
        outputChannel.appendLine(`[Telemetry] Auto-Stopwatch ${this._isStopwatchPaused ? 'paused' : 'resumed'} (Editor: ${this._activeEditorSeconds}s, Shell: ${this._activeShellSeconds}s, Chat: ${this._activeChatSeconds}s)`);
    }
    
    private _recordActivity(type: 'editor' | 'shell' | 'chat') {
        this._lastActivityTime = Date.now();
        this._lastActivityType = type;
    }

    private get _carrots(): number {
        this._checkCarrotReset();
        return this._context.workspaceState.get<number>('carrots', 100);
    }

    private set _carrots(value: number) {
        this._context.workspaceState.update('carrots', value);
    }

    private _checkCarrotReset() {
        const resetTime = this._context.workspaceState.get<number>('carrotsResetTime', 0);
        if (Date.now() > resetTime) {
            this._context.workspaceState.update('carrots', 100);
            this._context.workspaceState.update('carrotsResetTime', Date.now() + 3600000);
        }
    }

    private async _renderCurrentWebview(): Promise<void> {
        if (!this._currentWebview) {
            return;
        }

        const snapshot = this._authService.snapshot;
        const authConfig = this._authService.config;
        const elapsed = this._totalElapsedSeconds;
        if (snapshot.status === 'signed_in') {
            this._currentWebview.html = this._getHtmlForWebview(
                this._currentWebview,
                this._carrots,
                elapsed,
                this._isStopwatchPaused,
                snapshot,
            );
            return;
        }

        this._currentWebview.html = this._getSignedOutHtmlForWebview(snapshot, authConfig, this._currentWebview);
    }

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._extensionUri]
        };

        this._currentWebview = webviewView.webview;
        void this._renderCurrentWebview();

        webviewView.webview.onDidReceiveMessage(async (data) => {
            switch (data.type) {
                case 'authSignIn': {
                    try {
                        await this._authService.signIn();
                    } catch (error) {
                        TAChatViewProvider.getOutputChannel().appendLine(`[Auth Sign-In Error]: ${error}`);
                    }
                    break;
                }
                case 'authSignOut': {
                    try {
                        await this._authService.signOutEverywhere();
                    } catch (error) {
                        TAChatViewProvider.getOutputChannel().appendLine(`[Auth Sign-Out Error]: ${error}`);
                    }
                    break;
                }
                case 'authReset': {
                    try {
                        await this._authService.signOutEverywhere();
                        await this._authService.signIn();
                    } catch (error) {
                        TAChatViewProvider.getOutputChannel().appendLine(`[Auth Reset Error]: ${error}`);
                    }
                    break;
                }
                case 'askTA': {
                    await this._handleAskTA(data.text, data.mode, webviewView);
                    break;
                }
                case 'feedback': {
                    const reason = await vscode.window.showInputBox({
                        prompt: `Optional reason for ${data.rating === 'up' ? 'positive' : 'negative'} feedback:`,
                        placeHolder: "Tell us why..."
                    });

                    const feedbackUrl = `${resolveApiBaseUrl()}/api/feedback`;
                    await this._authService.fetch(feedbackUrl, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            session_id: this._sessionId,
                            rating: data.rating,
                            reason: reason || "",
                            message_index: data.messageIndex
                        })
                    }).catch(e => {
                        TAChatViewProvider.getOutputChannel().appendLine(`[Feedback Error]: ${e}`);
                    });
                    break;
                }
                case 'startTerminal': {
                    vscode.commands.executeCommand('coding-rabbit.startTerminal');
                    break;
                }
                case 'modeChanged': {
                    this._currentMode = data.mode;
                    if (data.mode === 'Study Assist') {
                        // Close the terminal/panel area
                        vscode.commands.executeCommand('workbench.action.closePanel');
                        // Close all editors so the focus is entirely on the chat
                        vscode.commands.executeCommand('workbench.action.closeAllEditors');
                    }
                    break;
                }
                case 'exportChat': {
                    this._exportChat();
                    break;
                }
                case 'toggleStopwatch': {
                    if (!data.isPaused) {
                        this._recordActivity('chat'); // Manual resume triggers activity
                    }
                    break;
                }
                case 'webviewReady': {
                    this._restoreChatHistory(webviewView.webview);
                    this._prewarmModel();
                    break;
                }
            }
        });
    }

    private async _prewarmModel() {
        if (this._hasSentWakeup) return;
        this._hasSentWakeup = true;
        try {
            const apiUrl = resolveChatApiUrl();
            const modelName = vscode.workspace.getConfiguration('codingRabbit').get('modelName') || 'codingrabbit-ta';
            
            TAChatViewProvider.getOutputChannel().appendLine("[Telemetry] Sending background wakeup ping to pre-warm SageMaker instance...");
            
            // Fire and forget - we don't care about the response, we just want to wake up the instance
            void this._authService.fetch(apiUrl as string, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model: modelName,
                    messages: [{ role: "user", content: "[SYSTEM_EVENT: Wakeup SageMaker Instance]" }],
                    stream: false,
                    options: { num_predict: 2 } // Keep it extremely short
                })
            }).catch(() => { /* ignore network errors on prewarm */ });
        } catch (e) {
            TAChatViewProvider.getOutputChannel().appendLine(`[Telemetry] Pre-warm failed: ${e}`);
        }
    }

    private async _restoreChatHistory(webview: vscode.Webview) {
        if (this._conversationHistory.length > 0) {
            webview.postMessage({ type: 'clearChat' });
            
            for (const msg of this._conversationHistory) {
                let content = msg.content;
                if (msg.role === 'user') {
                    if (content.startsWith('[IDE_EVENT:')) {
                        continue; // Do not show hidden IDE events in the chat history
                    }
                    const stateMatch = content.match(/\[State_Tracking\][\s\S]*?\[\/State_Tracking\]/);
                    if (stateMatch) {
                        content = content.replace(stateMatch[0], '').trim();
                    }
                    webview.postMessage({ type: 'addResponse', text: content, isHtml: false, isThinking: false, isUser: true });
                } else {
                    const thinkMatch = content.match(/<think>[\s\S]*?<\/think>/);
                    if (thinkMatch) {
                        content = content.replace(thinkMatch[0], '').trim();
                    }
                    const analysisMatch = content.match(/<analysis>[\s\S]*?<\/analysis>/);
                    if (analysisMatch) {
                        content = content.replace(analysisMatch[0], '').trim();
                    }
                    
                    const strayTags = [
                        '[CONCEPTUAL_HINT]', '[VISUAL_SCAFFOLD]', '[DIRECT_SYNTAX_SCAFFOLD]', 
                        '[ANALOGY_SCAFFOLD]', '[CONCEPTUAL_INTEGRATION]', '[DIRECT_THEORY_SCAFFOLD]',
                        '[HIDDEN CoT RATIONALE]', '[STYLE_NUDGE]', '[ADVERSARIAL_WARNING]',
                        '[DEBUG_IDEA_UNLOCKED]', '[END_CHAT]'
                    ];
                    for (const tag of strayTags) {
                        content = content.split(tag).join('').trim();
                    }
                    
                    const htmlContent = await marked.parse(content);
                    webview.postMessage({ type: 'addResponse', html: htmlContent, isHtml: true, isThinking: false });
                }
            }
        }
    }

    private async _exportChat() {
        if (this._conversationHistory.length === 0) {
            vscode.window.showInformationMessage("No chat history to export.");
            return;
        }

        let markdownContent = "# Coding Rabbit Chat Export\n\n";
        for (const msg of this._conversationHistory) {
            const role = msg.role === 'user' ? '**Student**' : '**Coding Rabbit**';
            let content = msg.content;
            
            if (msg.role === 'user' && content.startsWith('[IDE_EVENT:')) {
                continue; // Do not export hidden IDE events
            }
            
            // Strip out <think> and <analysis> tags if present in the TA's raw history
            const thinkMatch = content.match(/<think>[\s\S]*?<\/think>/);
            if (thinkMatch) {
                content = content.replace(thinkMatch[0], '').trim();
            }
            const analysisMatch = content.match(/<analysis>[\s\S]*?<\/analysis>/);
            if (analysisMatch) {
                content = content.replace(analysisMatch[0], '').trim();
            }
            
            // Strip structural tags
            const strayTags = [
                '[CONCEPTUAL_HINT]', '[VISUAL_SCAFFOLD]', '[DIRECT_SYNTAX_SCAFFOLD]', 
                '[ANALOGY_SCAFFOLD]', '[CONCEPTUAL_INTEGRATION]', '[DIRECT_THEORY_SCAFFOLD]',
                '[HIDDEN CoT RATIONALE]', '[STYLE_NUDGE]', '[ADVERSARIAL_WARNING]',
                '[DEBUG_IDEA_UNLOCKED]', '[END_CHAT]'
            ];
            for (const tag of strayTags) {
                content = content.split(tag).join('').trim();
            }

            // Strip the [State_Tracking] injection from user messages
            const stateMatch = content.match(/\[State_Tracking\][\s\S]*?\[\/State_Tracking\]/);
            if (stateMatch) {
                content = content.replace(stateMatch[0], '').trim();
            }

            markdownContent += `${role}:\n\n${content}\n\n---\n\n`;
        }

        const workspaceFolders = vscode.workspace.workspaceFolders;
        let defaultUri: vscode.Uri | undefined;
        if (workspaceFolders && workspaceFolders.length > 0) {
            const dateStr = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
            defaultUri = vscode.Uri.joinPath(workspaceFolders[0].uri, `chat_export_${dateStr}.md`);
        }

        const uri = await vscode.window.showSaveDialog({
            defaultUri,
            filters: { 'Markdown': ['md'] },
            title: 'Save Chat Export'
        });

        if (uri) {
            await vscode.workspace.fs.writeFile(uri, Buffer.from(markdownContent, 'utf8'));
            vscode.window.showInformationMessage("Chat exported successfully!");
        }
    }

    private async _handleAskTA(userMessage: string, mode: string, webviewView: any, isHidden: boolean = false) {
        this._recordActivity('chat');
        
        if (this._carrots <= 0 && mode !== 'Study Assist') {
            webviewView.webview.postMessage({ type: 'addResponse', text: "Coding Rabbit ate all the carrots and is full and needs a break - Check in with your Human TA if you have more questions before then.", isThinking: false });
            return;
        }

        // 0. Hard Mode Enforcement
        const copilot = vscode.extensions.getExtension('github.copilot');
        const copilotChat = vscode.extensions.getExtension('github.copilot-chat');
        if (copilot || copilotChat) {
            webviewView.webview.postMessage({ 
                type: 'addResponse', 
                text: `[Hard Mode Enforced]\\n\\nGitHub Copilot is currently active! To prevent AI-generated solutions from bypassing the learning process, I am disabling my assistance.\\n\\nPlease disable or uninstall GitHub Copilot for this workspace to continue using the CodingRabbit.`, 
                isThinking: false 
            });
            return;
        }

        // 1. Gather Context
        let editor = vscode.window.activeTextEditor;
        // If the student clicked the Chat window, the C++ editor loses active focus!
        // We must fallback to visible editors so the LLM doesn't receive an empty file.
        if (!editor || editor.document.uri.scheme !== 'file') {
            const visibleEditors = vscode.window.visibleTextEditors.filter(e => e.document.uri.scheme === 'file');
            if (visibleEditors.length > 0) {
                editor = visibleEditors[0];
            }
        }
        let rawCode = '';
        let astMetadata = 'AST_Metadata: (Hidden for local inference)';
        let likelyPasteDetected = false;
        let pastedCharCount = 0;
        
        // Hide code context in Study Assist mode to prevent the TA from aggressively pivoting back to debugging
        if (mode === 'Study Assist') {
            rawCode = '(Code hidden in Study Assist mode to focus on conceptual questions)';
        } else if (editor) {
            const document = editor.document;
            const text = document.getText();
            const lines = text.split('\n');
            const cursorLine = editor.selection.active.line;
            let startLine = 0;
            let endLine = lines.length;

            // Cap the code context to 200 lines to preserve token limits
            if (lines.length > 200) {
                startLine = Math.max(0, cursorLine - 100);
                endLine = Math.min(lines.length, cursorLine + 100);
            }
            
            rawCode = lines.slice(startLine, endLine).map((line, i) => `${startLine + i + 1}: ${line}`).join('\n');
            
            if (startLine > 0) rawCode = `... (code truncated above)\n` + rawCode;
            if (endLine < lines.length) rawCode = rawCode + `\n... (code truncated below)`;
            pastedCharCount = this._pasteStatusByUri.get(document.uri.toString()) || 0;
            likelyPasteDetected = pastedCharCount > 0;
            // Clear the paste status so the TA only interrogates them once per paste
            if (likelyPasteDetected) {
                this._pasteStatusByUri.set(document.uri.toString(), 0);
            }
            
            try {
                const parser = await this.getParser();
                const tree = parser.parse(text);
                const queryStr = `
                    (function_declarator declarator: (identifier) @func_name)
                    (identifier) @any_id
                    (pointer_declarator) @is_ptr
                    (reference_declarator) @is_ref
                    (new_expression) @new_op
                    (delete_expression) @delete_op
                    (call_expression function: (identifier) @call_id)
                    (null) @null_val
                    (for_statement) @loop
                    (for_range_loop) @range_loop
                    (while_statement) @loop
                    (return_statement) @return_stmt
                `;
                const query = this._cppLanguage!.query(queryStr);
                let focusScope = "global";
                const cursorPos = editor.selection.active;
                let cursorNode: any = tree.rootNode.descendantForPosition({ row: cursorPos.line, column: cursorPos.character });
                let targetNode = tree.rootNode;
                while (cursorNode) {
                    if (cursorNode.type === "function_definition") {
                        targetNode = cursorNode;
                        const decl = cursorNode.childForFieldName("declarator");
                        if (decl) {
                            const get_id = (n: any): string | null => {
                                if (n.type === 'destructor_name') return n.text.split('::').pop() || n.text;
                                if (n.type === 'identifier' || n.type === 'field_identifier') return n.text.split('::').pop() || n.text;
                                for (let i = 0; i < n.childCount; i++) {
                                    const res = get_id(n.child(i));
                                    if (res) return res;
                                }
                                return null;
                            };
                            const defName = get_id(decl);
                            if (defName) {
                                focusScope = `function::${defName}`;
                            }
                        }
                        break;
                    }
                    cursorNode = cursorNode.parent;
                }
                
                const targetVariables = new Set<string>();
                const features = {
                    Has_Loop: false,
                    Has_Pointer: false,
                    Has_Reference: false,
                    Has_New: false,
                    Has_Delete: false,
                    Has_Malloc: false,
                    Has_Free: false,
                    Has_Nullptr: false,
                    Has_Recursion: false,
                    Has_Early_Return: false,
                    Has_Iterator: false,
                    Has_STL_Algorithm: false,
                    Has_Smart_Pointer: false,
                    Has_Pass_By_Value: false
                };
                
                const matches = query.matches(targetNode);
                for (const match of matches) {
                    for (const capture of match.captures) {
                        const tag = capture.name;
                        const node = capture.node;
                        const text = node.text;
                        const cleanName = text.split("::").pop() || text;

                        if (tag === "call_id") {
                            if (cleanName === "malloc") features.Has_Malloc = true;
                            if (cleanName === "free") features.Has_Free = true;
                            if (["find", "sort", "accumulate", "transform", "copy", "remove_if"].includes(cleanName)) features.Has_STL_Algorithm = true;
                            if (["begin", "end", "cbegin", "cend", "rbegin", "rend"].includes(cleanName)) features.Has_Iterator = true;
                            
                            // Recursion check
                            let curr: any = node.parent;
                            while (curr) {
                                if (curr.type === "function_definition") {
                                    const decl = curr.childForFieldName("declarator");
                                    if (decl) {
                                        const get_id = (n: any): string | null => {
                                            if (n.type === 'destructor_name') return n.text.split('::').pop() || n.text;
                                            if (n.type === 'identifier' || n.type === 'field_identifier') return n.text.split('::').pop() || n.text;
                                            for (let i = 0; i < n.childCount; i++) {
                                                const res = get_id(n.child(i));
                                                if (res) return res;
                                            }
                                            return null;
                                        };
                                        const defName = get_id(decl);
                                        if (defName === cleanName) {
                                            features.Has_Recursion = true;
                                        }
                                    }
                                    break;
                                }
                                curr = curr.parent;
                            }
                        } else if (tag === "any_id") {
                            if (["unique_ptr", "shared_ptr", "weak_ptr"].includes(text)) features.Has_Smart_Pointer = true;
                            if (["iterator", "const_iterator"].includes(text)) features.Has_Iterator = true;
                            const ignoreList = ["main", "std", "cout", "endl", "printf", "malloc", "free", "nullptr", "NULL"];
                            if (!targetVariables.has(text) && !ignoreList.includes(text)) {
                                let parent: any = node.parent;
                                let isVar = false;
                                while (parent) {
                                    if (["declaration", "parameter_declaration", "init_declarator", "binary_expression", "assignment_expression"].includes(parent.type)) {
                                        isVar = true;
                                        break;
                                    }
                                    parent = parent.parent;
                                }
                                if (isVar) {
                                    targetVariables.add(text);
                                }
                            }
                        } else if (tag === "is_ptr") {
                            features.Has_Pointer = true;
                        } else if (tag === "is_ref") {
                            features.Has_Reference = true;
                        } else if (tag === "new_op") {
                            features.Has_New = true;
                        } else if (tag === "delete_op") {
                            features.Has_Delete = true;
                        } else if (tag === "null_val") {
                            features.Has_Nullptr = true;
                        } else if (tag === "loop") {
                            features.Has_Loop = true;
                        } else if (tag === "range_loop") {
                            features.Has_Loop = true;
                            features.Has_Iterator = true;
                        } else if (tag === "return_stmt") {
                            features.Has_Early_Return = true;
                        }
                    }
                }
                
                if (rawCode.includes("shared_ptr") || rawCode.includes("unique_ptr") || rawCode.includes("weak_ptr")) {
                    features.Has_Smart_Pointer = true;
                    features.Has_Pointer = true;
                }
                
                // Simple regex heuristic: look for vector/string/map followed by a variable name and a comma/paren, without an ampersand
                if (/\b(vector|string|map|set|list)(?:<[^>]+>)?\s+[a-zA-Z_]\w*\s*[,)]/.test(rawCode)) {
                    features.Has_Pass_By_Value = true;
                }
                
                if (/\bstd::(find|sort|accumulate|transform|copy|remove_if)\b/.test(rawCode)) {
                    features.Has_STL_Algorithm = true;
                }
                
                if (/\b(begin|end|cbegin|cend|rbegin|rend)\s*\(/.test(rawCode) || rawCode.includes(".begin(") || rawCode.includes(".end(")) {
                    features.Has_Iterator = true;
                }
                
                const variableTypes: Record<string, string> = {};
                const typeQueryStr = `
                    (declaration) @decl
                    (parameter_declaration) @decl
                    (field_declaration) @decl
                `;
                const typeQuery = this._cppLanguage!.query(typeQueryStr);
                const typeMatches = typeQuery.matches(targetNode);
                
                for (const match of typeMatches) {
                    const node = match.captures[0].node;
                    const typeNode = node.childForFieldName('type');
                    const declNode = node.childForFieldName('declarator');
                    
                    if (typeNode && declNode) {
                        let typeStr = typeNode.text;
                        
                        let curr: any = declNode;
                        let varName = "";
                        while (curr) {
                            if (curr.type === 'pointer_declarator') {
                                typeStr += '*';
                                curr = curr.childForFieldName('declarator');
                            } else if (curr.type === 'array_declarator') {
                                const sizeNode = curr.childForFieldName('size');
                                typeStr += '[' + (sizeNode ? sizeNode.text : '') + ']';
                                curr = curr.childForFieldName('declarator');
                            } else if (curr.type === 'init_declarator') {
                                curr = curr.childForFieldName('declarator');
                            } else if (curr.type === 'reference_declarator') {
                                typeStr += '&';
                                curr = curr.childForFieldName('declarator');
                            } else if (curr.type === 'identifier' || curr.type === 'field_identifier') {
                                varName = curr.text;
                                break;
                            } else {
                                // Default fallback: search descendants
                                const findId = (n: any): any => {
                                    if (n.type === 'identifier' || n.type === 'field_identifier') return n;
                                    for (let i = 0; i < n.childCount; i++) {
                                        const res = findId(n.child(i));
                                        if (res) return res;
                                    }
                                    return null;
                                };
                                const idNode = findId(curr);
                                if (idNode) {
                                    varName = idNode.text;
                                }
                                break;
                            }
                        }
                        
                        // We only care about variables the LLM actually targets
                        if (varName && targetVariables.has(varName)) {
                            variableTypes[varName] = typeStr;
                        }
                    }
                }
                
                // Also check for array as requested before
                const arrayQuery = this._cppLanguage!.query(`(array_declarator) @is_array`);
                if (arrayQuery.matches(targetNode).length > 0) {
                    // Not officially in python script's Features block, but mentioned in prompt rules.
                    // We'll leave it out of Features to strictly match python, but we can add it if needed.
                }
                
                // Extract STL algorithms +/- 1 line from cursor
                const cursorLine = editor.selection.active.line;
                const narrowStartLine = Math.max(0, cursorLine - 1);
                const narrowEndLine = Math.min(document.lineCount - 1, cursorLine + 1);
                const narrowCode = document.getText(new vscode.Range(narrowStartLine, 0, narrowEndLine + 1, 0));
                
                const nearCursorStl: string[] = [];
                const stlRegex = /\bstd::([a-zA-Z0-9_]+)\b/g;
                let matchRegex;
                while ((matchRegex = stlRegex.exec(narrowCode)) !== null) {
                    const funcName = matchRegex[1];
                    // Filter out common types/objects to focus on algorithms/containers
                    if (['cout', 'cin', 'endl', 'string'].indexOf(funcName) === -1) {
                        if (!nearCursorStl.includes(funcName)) {
                            nearCursorStl.push(funcName);
                        }
                    }
                }
                
                astMetadata = `AST_Metadata:\n- Focus_Scope: "${focusScope}"\n- Target_Variables: ${JSON.stringify(variableTypes)}\n- Near_Cursor_STL: ${JSON.stringify(nearCursorStl)}\n- Features: ${JSON.stringify(features)}`;
            } catch (err) {
                TAChatViewProvider.getOutputChannel().appendLine(`AST Parsing Error: ${err}`);
                astMetadata = 'AST_Metadata: (Error Parsing AST)';
            }
        }

        const rawTerminalOutput = terminalBuffer.join('').trim();
        // Strip ANSI escape codes (colors, cursor movements, etc.) so the LLM can read the plain text history
        let terminalOutput = rawTerminalOutput.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
        
        // Massive GCC errors can easily blow out the LLM context window. 
        // In C++, the first error is often the most important, while the last lines contain final status.
        const outputLines = terminalOutput.split('\n');
        
        // Find the most recent command prompt to anchor the truncation
        let promptIndex = -1;
        for (let i = outputLines.length - 1; i >= 0; i--) {
            if (/[$#%>]\s+[a-zA-Z0-9.\-\/]/.test(outputLines[i])) {
                promptIndex = i;
                break;
            }
        }
        
        if (promptIndex !== -1) {
            const relevantLines = outputLines.slice(promptIndex);
            if (relevantLines.length > 20) {
                const first10 = relevantLines.slice(0, 10).join('\n');
                const last10 = relevantLines.slice(-10).join('\n');
                terminalOutput = first10 + "\n\n...[Middle terminal output truncated due to length]...\n\n" + last10;
            } else {
                terminalOutput = relevantLines.join('\n');
            }
        } else {
            if (outputLines.length > 20) {
                const first10 = outputLines.slice(0, 10).join('\n');
                const last10 = outputLines.slice(-10).join('\n');
                terminalOutput = first10 + "\n\n...[Middle terminal output truncated due to length]...\n\n" + last10;
            }
        }
        
        const exitCode = lastExitCode ?? 'N/A';

        // State updates for Frustration_Index
        if (lastExitCode !== 0 && lastExitCode !== null) {
            this._consecutiveTerminalErrors += 1;
        } else if (lastExitCode === 0) {
            this._consecutiveTerminalErrors = 0;
        }

        const activeEditor = vscode.window.activeTextEditor;
        const currentVersion = activeEditor ? activeEditor.document.version : -1;
        if (currentVersion === this._lastDocumentVersion) {
            this._chatRequestsSinceLastEdit += 1;
        } else {
            this._chatRequestsSinceLastEdit = 0;
            this._lastDocumentVersion = currentVersion;
        }

        let calculatedFrustration = 1;
        if (this._consecutiveTerminalErrors >= 3) calculatedFrustration += 1;
        if (this._consecutiveTerminalErrors >= 6) calculatedFrustration += 1;
        if (this._chatRequestsSinceLastEdit >= 3) calculatedFrustration += 1;
        calculatedFrustration = Math.min(calculatedFrustration, 3);
        
        // Mock Syllabus Matrix, but could be loaded from configuration
        const syllabusMatrix = `[SYLLABUS_MATRIX]
- Topic: Control Flow & Pointers
- Banned_Keywords: None
- Required_Keywords: while, new, delete`;

        let modeSpecificRule = mode === 'Homework Assist'
            ? `17. CONCEPTUAL QUESTIONS (HOMEWORK ASSIST ONLY): If \`Mode: Homework Assist\` is active and a student asks a valid conceptual or syntax question about C++ or the course material, you MAY answer it briefly using the \`[Vector_Database_Results]\`. When doing so, you MUST explicitly append a markdown citation \`[1](URL)\` referencing the provided source. However, you MUST explicitly invite them to use the Study Assist feature using varied phrasing (e.g., "If you want to dive deeper into this theory, toggle 'Study Assist' mode"). Crucially, you MUST NOT ask any follow-up conceptual questions. Your final sentence MUST be a direct question about the specific C++ code actively open in their editor, aggressively pivoting the conversation back to debugging their current file.`
            : `17. STUDY ASSIST MODE: If \`Mode: Study Assist\` is present in the context block, the student is in Study Mode. You may answer deep conceptual or syntax questions using the \`[Vector_Database_Results]\` without requiring them to open a C++ file. When doing so, you MUST explicitly append a markdown citation \`[1](URL)\` referencing the provided source. You MUST NOT generate practice problems from scratch; firmly refer them back to official course materials. You still MUST NOT provide code solutions or answer out-of-scope (non-C++) questions.`;

        let rule1 = mode === 'Homework Assist'
            ? `1. PEDAGOGICAL BREVITY (HOMEWORK ASSIST): Be extremely concise (1-2 sentences). If using a [CONCEPTUAL_HINT] or [VISUAL_SCAFFOLD], end with a guiding question. If using a [DIRECT_SYNTAX_SCAFFOLD], end with clear direction. (EXCEPTION: If terminating the chat using [END_CHAT], do NOT ask any questions).`
            : `1. PEDAGOGICAL ESCALATION (STUDY ASSIST): Adjust your conceptual scaffolding based on the turn and ZPD_Boundary.
   - Turn 1: Use an [ANALOGY_SCAFFOLD]. Anchor the new C++ concept to a real-world analogy. Ask a guiding question.
   - Turn 2: Use [CONCEPTUAL_INTEGRATION]. Bridge the analogy to a previously mastered C++ concept.
   - Turn 3+: Use a [DIRECT_THEORY_SCAFFOLD]. Provide the formal, rigorous definition using the [Vector_Database_Results] with markdown citations.`;

        let dynamicContext = `[State_Tracking]
Mode: ${mode}
${likelyPasteDetected ? "Likely_Paste_Detected: true\nPasted_Char_Count: " + pastedCharCount : "Likely_Paste_Detected: false"}
Session_Style_Nudged: ${this._hasGivenStyleNudge}
Session_Adversarial_Warnings: ${this._adversarialWarningCount}
Active_Editor_Time_Sec: ${mode === 'Study Assist' ? this._studyDeltaEditorSeconds : this._homeworkDeltaEditorSeconds}
Active_Shell_Time_Sec: ${mode === 'Study Assist' ? this._studyDeltaShellSeconds : this._homeworkDeltaShellSeconds}
Active_Chat_Time_Sec: ${mode === 'Study Assist' ? this._studyDeltaChatSeconds : this._homeworkDeltaChatSeconds}`;

        // Reset delta timers immediately after capturing them for the payload
        if (mode === 'Study Assist') {
            this._studyDeltaEditorSeconds = 0;
            this._studyDeltaShellSeconds = 0;
            this._studyDeltaChatSeconds = 0;
        } else {
            this._homeworkDeltaEditorSeconds = 0;
            this._homeworkDeltaShellSeconds = 0;
            this._homeworkDeltaChatSeconds = 0;
        }

        if (mode !== 'Study Assist') {
            dynamicContext += `\n\n[Code_Context]
Raw_Code:
${rawCode}
${astMetadata}
[Terminal_Context]
Exit_Code: ${exitCode}
Output:
${terminalOutput}`;
        }

        // We should send the message to the webview that we're thinking
        webviewView.webview.postMessage({ type: 'addResponse', text: "...", isThinking: true });

        // Add pure user message to history
        this._conversationHistory.push({ role: "user", content: userMessage });
        
        // 1. Sliding Window: Keep only the last 6 messages (3 user/assistant pairs)
        let windowedHistory = this._conversationHistory;
        if (windowedHistory.length > 6) {
            windowedHistory = windowedHistory.slice(windowedHistory.length - 6);
        }

        // Prepare API messages
        const apiMessages = windowedHistory.map(msg => {
            let content = msg.content;
            // If in Study Assist mode, aggressively blindfold the LLM from its past thoughts about the code
            if (mode === 'Study Assist' && msg.role === 'assistant') {
                const thinkMatch = content.match(/<think>[\s\S]*?<\/think>/);
                if (thinkMatch) {
                    content = content.replace(thinkMatch[0], '').trim();
                }
                const analysisMatch = content.match(/<analysis>[\s\S]*?<\/analysis>/);
                if (analysisMatch) {
                    content = content.replace(analysisMatch[0], '').trim();
                }
            }
            return { role: msg.role, content: content };
        });
        
        // Inject dynamic context into the very last user message for perfect KV caching
        apiMessages[apiMessages.length - 1].content = `${dynamicContext}\n\n[Student_Question]\n${userMessage}`;

        // 3. Call the configured chat backend.
        try {
            const outputChannel = TAChatViewProvider.getOutputChannel();
            outputChannel.appendLine(`\n--- NEW REQUEST (${new Date().toLocaleTimeString()}) ---`);
            outputChannel.appendLine(`[Code_Context]`);
            outputChannel.appendLine(`Mode: ${mode}`);
            outputChannel.appendLine(`Likely_Paste_Detected: ${likelyPasteDetected}, Char_Count: ${pastedCharCount}`);
            outputChannel.appendLine(`Raw_Code:\n${rawCode}`);
            outputChannel.appendLine(`${astMetadata}`);
            outputChannel.appendLine(`[Terminal_Context]\nExit_Code: ${exitCode}\nOutput:\n${terminalOutput}`);
            outputChannel.appendLine(`---------------------------------------------------`);

            const apiUrl = resolveChatApiUrl();
            const modelName = vscode.workspace.getConfiguration('codingRabbit').get('modelName') || 'codingrabbit-ta';
            
            outputChannel.appendLine(`Model Requested: ${modelName}`);
            
            const requestBody = {
                model: modelName,
                messages: apiMessages,
                stream: false,
                options: {
                    temperature: 0.7,
                    top_p: 0.9,
                    num_ctx: 8192,
                    num_predict: 2048
                }
            };

            // Using dynamic import for fetch since node-fetch isn't bundled
            // VSCode extensions in Node 18+ have global fetch
            const response = await this._authService.fetch(apiUrl as string, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });

            if (!response.ok) {
                let errBody = "";
                try { errBody = await response.text(); } catch(e) {}
                throw new Error(`API error: ${response.statusText} - ${errBody}`);
            }

            const data: any = await response.json();
            let rawTaResponse = data.message?.content || "No response generated.";
            
            let displayResponse = rawTaResponse;
            
            // Extract just the Style_Violation_Check block to prevent false positive matches
            const styleCheckMatch = rawTaResponse.match(/- Style_Violation_Check:.*?(?=\n\s*-|$)/is);
            if (styleCheckMatch && styleCheckMatch[0].toLowerCase().includes("nudge") && !this._hasGivenStyleNudge) {
                if (!displayResponse.includes('[STYLE_NUDGE]')) {
                    displayResponse += " [STYLE_NUDGE]";
                    rawTaResponse += " [STYLE_NUDGE]";
                }
            }
            
            // If the LLM successfully generated an analysis block but the student isn't supposed to see it
            if (displayResponse.includes('<think>')) {
                if (!displayResponse.includes('</think>')) {
                    displayResponse = displayResponse.substring(0, displayResponse.indexOf('<think>')) + '\n\n*(Coding Rabbit is thinking...)*';
                } else {
                    displayResponse = displayResponse.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
                }
            }
            if (displayResponse.includes('<analysis>')) {
                if (!displayResponse.includes('</analysis>')) {
                    displayResponse = displayResponse.substring(0, displayResponse.indexOf('<analysis>')) + '\n\n*(Coding Rabbit is analyzing code...)*';
                } else {
                    displayResponse = displayResponse.replace(/<analysis>[\s\S]*?<\/analysis>/g, '').trim();
                }
            }
            
            // Clean up accidental markdown code block wrappers generated by the 14B model
            if (displayResponse.startsWith('```\n') && displayResponse.endsWith('\n```')) {
                displayResponse = displayResponse.substring(4, displayResponse.length - 4).trim();
            }
            
            // Strip hallucinated pedagogical tags and residual CoT headers
            const strayTags = [
                '[CONCEPTUAL_HINT]', '[VISUAL_SCAFFOLD]', '[DIRECT_SYNTAX_SCAFFOLD]', 
                '[ANALOGY_SCAFFOLD]', '[CONCEPTUAL_INTEGRATION]', '[DIRECT_THEORY_SCAFFOLD]',
                '[HIDDEN CoT RATIONALE]'
            ];
            for (const tag of strayTags) {
                if (displayResponse.includes(tag)) {
                    // Use split/join to remove all occurrences safely
                    displayResponse = displayResponse.split(tag).join('').trim();
                }
            }
            
            if (displayResponse.includes('[STYLE_NUDGE]')) {
                this._hasGivenStyleNudge = true;
                if (mode === 'Study Assist') {
                    this._studyDeltaStyleNudges += 1;
                } else {
                    this._homeworkDeltaStyleNudges += 1;
                }
                displayResponse = displayResponse.replace(/\[STYLE_NUDGE\]/g, '').trim();
            }

            if (displayResponse.includes('[ADVERSARIAL_WARNING]')) {
                this._adversarialWarningCount += 1;
                displayResponse = displayResponse.replace(/\[ADVERSARIAL_WARNING\]/g, '').trim();
            }
            
            if (displayResponse.includes('[END_CHAT]')) {
                displayResponse = displayResponse.replace(/\[END_CHAT\]/g, '').trim();
                this._conversationHistory = [];
                if (mode !== 'Study Assist') {
                    this._carrots = Math.max(0, this._carrots - 5);
                    displayResponse += `\n\n*(Session ended. Coding Rabbit was sad and ate 5 carrots. 🥕 You have ${this._carrots} carrots remaining this hour.)*`;
                    webviewView.webview.postMessage({ type: 'updateCarrots', count: this._carrots });
                } else {
                    displayResponse += `\n\n*(Session ended.)*`;
                }
                const htmlContent = await marked.parse(displayResponse);
                webviewView.webview.postMessage({ type: 'addResponse', html: htmlContent, isHtml: true, isThinking: false });
            } else {
                if (displayResponse.includes('[DEBUG_IDEA_UNLOCKED]')) {
                    displayResponse = displayResponse.replace(/\[DEBUG_IDEA_UNLOCKED\]/g, '').trim();
                    if (mode !== 'Study Assist') {
                        this._homeworkDeltaRewardsGiven += 1;
                        this._carrots -= 1;
                        if (this._carrots <= 0) {
                            displayResponse += `\n\n*(Coding Rabbit ate all the carrots and is full and needs a break - Check in with your Human TA if you have more questions before then. 🥕)*`;
                        } else {
                            displayResponse += `\n\n*(Coding Rabbit got to eat a carrot! 🥕 You have ${this._carrots} carrots remaining this hour.)*`;
                        }
                        webviewView.webview.postMessage({ type: 'updateCarrots', count: this._carrots });
                    }
                }
                
                // Add the RAW TA response (INCLUDING the <analysis> block) to history so the LLM retains its Chain of Thought across turns!
                this._conversationHistory.push({ role: "assistant", content: rawTaResponse });
                if (this._conversationHistory.length > 10) {
                    this._conversationHistory = this._conversationHistory.slice(this._conversationHistory.length - 10);
                }
                
                // Parse markdown to HTML
                const htmlContent = await marked.parse(displayResponse);

                // Send the stripped HTML response to the UI
                webviewView.webview.postMessage({ type: 'addResponse', html: htmlContent, isHtml: true, isThinking: false });
            }
        } catch (err: any) {
            const outputChannel = TAChatViewProvider.getOutputChannel();
            outputChannel.appendLine(`\n[API ERROR]: ${err.message || err}`);
            
            // Critical Fix: Pop the user's message out of the history if the API request failed!
            // If we don't do this, multiple timeouts/errors will stack multiple {"role": "user"} messages
            // in a row without an intervening {"role": "assistant"} message, which causes Qwen to crash with a 500.
            if (this._conversationHistory.length > 0 && this._conversationHistory[this._conversationHistory.length - 1].role === "user") {
                this._conversationHistory.pop();
            }
            
            webviewView.webview.postMessage({ 
                type: 'addResponse', 
                text: "Uh oh, my circuits are a bit fried. Make sure the remote CodingRabbit backend is reachable from this workspace!",
                isThinking: false 
            });
        }
    }

    private _escapeHtml(value: string): string {
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    private _getSignedOutHtmlForWebview(
        snapshot: CognitoAuthSnapshot,
        authConfig: CognitoAuthConfig | null,
        webview: vscode.Webview,
    ) {
        const titleByStatus: Record<CognitoAuthSnapshot['status'], string> = {
            unconfigured: 'CodingRabbit sign-in is not configured',
            signed_out: 'Sign in to CodingRabbit',
            signing_in: 'Waiting for Cognito to finish',
            signed_in: 'Signed in',
            refreshing: 'Refreshing your session',
            error: 'Sign-in error',
        };

        const messageByStatus: Record<CognitoAuthSnapshot['status'], string> = {
            unconfigured: 'Set the Cognito auth settings in your VS Code workspace before signing in.',
            signed_out: 'Open the same Cognito login page the web app uses. Your browser will open externally and return you to VS Code.',
            signing_in: 'Finish signing in in your browser. This panel updates automatically when the callback returns.',
            signed_in: 'You are authenticated. Reopen the chat view if it does not refresh automatically.',
            refreshing: 'Wrapping up your session. If the browser callback already landed, this panel should update shortly.',
            error: snapshot.message || 'Cognito sign-in failed. Try again or inspect the output channel for details.',
        };

        const buttonLabelByStatus: Record<CognitoAuthSnapshot['status'], string> = {
            unconfigured: 'Configure Cognito',
            signed_out: 'Sign in with CodingRabbit',
            signing_in: 'Open login page again',
            signed_in: 'Continue',
            refreshing: 'Keep waiting',
            error: 'Try sign-in again',
        };

        const actionTypeByStatus: Record<CognitoAuthSnapshot['status'], string> = {
            unconfigured: 'authSignIn',
            signed_out: 'authSignIn',
            signing_in: 'authSignIn',
            signed_in: 'authSignIn',
            refreshing: 'authSignIn',
            error: 'authSignIn',
        };

        const title = this._escapeHtml(titleByStatus[snapshot.status]);
        const message = this._escapeHtml(messageByStatus[snapshot.status]);
        const redirectUri = authConfig ? this._escapeHtml(authConfig.redirectUri) : '';
        const logoutUri = authConfig ? this._escapeHtml(authConfig.logoutUri) : '';
        const showConfigDetails = Boolean(authConfig);
        const mascotUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'mascot.png')).toString();

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CodingRabbit Sign In</title>
    <style>
        body {
            margin: 0;
            padding: 20px;
            box-sizing: border-box;
            min-height: 100vh;
            font-family: var(--vscode-font-family);
            color: var(--vscode-editor-foreground);
            background:
                radial-gradient(circle at top left, rgba(255, 170, 0, 0.14), transparent 36%),
                radial-gradient(circle at bottom right, rgba(0, 150, 255, 0.12), transparent 28%),
                var(--vscode-editor-background);
        }
        .shell {
            max-width: 560px;
            margin: 0 auto;
            padding: 24px;
            border: 1px solid var(--vscode-widget-border);
            border-radius: 18px;
            background: var(--vscode-sideBar-background);
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.16);
        }
        .hero {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
        }
        .mascot {
            width: 112px;
            max-width: 40vw;
            height: auto;
            display: block;
            image-rendering: auto;
            filter: drop-shadow(0 8px 18px rgba(0, 0, 0, 0.14));
        }
        .badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 10px;
            border-radius: 999px;
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
            font-size: 12px;
            margin-bottom: 14px;
        }
        h1 {
            margin: 0 0 10px;
            font-size: 28px;
            line-height: 1.1;
        }
        p {
            margin: 0 0 18px;
            line-height: 1.5;
            color: var(--vscode-descriptionForeground);
        }
        button {
            width: 100%;
            padding: 12px 14px;
            border: none;
            border-radius: 12px;
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            font-weight: 600;
            cursor: pointer;
        }
        button.secondary {
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        button:hover {
            background: var(--vscode-button-hoverBackground);
        }
        .small {
            margin-top: 12px;
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
        }
        details {
            margin-top: 12px;
        }
        summary {
            cursor: pointer;
            color: var(--vscode-descriptionForeground);
            font-size: 12px;
        }
        .muted {
            margin-top: 10px;
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
            opacity: 0.9;
        }
        .waiting {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin: 8px 0 18px;
            padding: 10px 12px;
            border-radius: 12px;
            background: color-mix(in srgb, var(--vscode-button-background) 12%, transparent);
            border: 1px solid var(--vscode-widget-border);
            color: var(--vscode-descriptionForeground);
        }
        .spinner {
            width: 14px;
            height: 14px;
            border-radius: 50%;
            border: 2px solid var(--vscode-descriptionForeground);
            border-top-color: transparent;
            animation: spin 0.9s linear infinite;
        }
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        code {
            font-family: var(--vscode-editor-font-family);
        }
    </style>
</head>
<body>
    <div class="shell">
        <div class="hero">
            <img class="mascot" src="${mascotUri}" alt="CodingRabbit mascot" />
            <div class="badge">CodingRabbit Auth</div>
        </div>
        <h1>${title}</h1>
        ${snapshot.status === 'signing_in' ? '<div class="waiting"><span class="spinner"></span><span>Waiting for the browser callback from Cognito...</span></div>' : ''}
        <p>${message}</p>
        <button id="authBtn" class="${snapshot.status === 'signing_in' ? 'secondary' : ''}">${buttonLabelByStatus[snapshot.status]}</button>
        ${showConfigDetails ? `
        <details>
            <summary>Advanced connection details</summary>
            <div class="muted">
                Callback URI: <code>${redirectUri}</code><br />
                Logout URI: <code>${logoutUri}</code>
            </div>
        </details>` : ''}
        <div class="small">
            The extension uses the same branded Cognito Hosted UI as the web app.
        </div>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const btn = document.getElementById('authBtn');
        btn.addEventListener('click', () => {
            vscode.postMessage({ type: '${actionTypeByStatus[snapshot.status]}' });
        });
    </script>
</body>
</html>`;
    }

    private _getHtmlForWebview(webview: vscode.Webview, carrots: number, elapsed: number, isPaused: boolean, authState: CognitoAuthSnapshot) {
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TA Chat</title>
    <style>
        body { margin: 0; padding: 10px; box-sizing: border-box; height: 100vh; font-family: var(--vscode-font-family); color: var(--vscode-editor-foreground); background-color: var(--vscode-editor-background); }
        .chat-container { display: flex; flex-direction: column; height: 100%; box-sizing: border-box; padding-bottom: 10px; }
        .messages { flex-grow: 1; overflow-y: auto; margin-bottom: 10px; }
        .message { margin-bottom: 10px; padding: 8px; border-radius: 4px; }
        .user-message { background-color: var(--vscode-button-background); color: var(--vscode-button-foreground); align-self: flex-end; }
        .ta-message { background-color: var(--vscode-editorWidget-background); border: 1px solid var(--vscode-widget-border); }
        textarea { width: 100%; box-sizing: border-box; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border); padding: 8px; resize: vertical; min-height: 60px; font-family: inherit; }
        button, select { margin-top: 5px; width: 100%; padding: 8px; background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; cursor: pointer; }
        button:hover { background: var(--vscode-button-hoverBackground); }
        pre { background-color: var(--vscode-textCodeBlock-background); padding: 8px; border-radius: 4px; overflow-x: auto; font-family: var(--vscode-editor-font-family); }
        code { font-family: var(--vscode-editor-font-family); color: var(--vscode-textPreformat-foreground); }
        p { margin: 8px 0; line-height: 1.4; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div style="font-weight: bold; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--vscode-widget-border);">
            Coding Rabbit: TA Chat
            <button id="signOutBtn" title="Sign out locally from this extension" style="float: right; margin-left: 8px; width: auto;">Sign out</button>
            <span id="authStatus" style="float: right; margin-left: 8px;">${authState.status === 'refreshing' ? 'Refreshing session...' : 'Signed in'}</span>
            <span id="carrotCount" style="float: right;">🥕 ${carrots} Carrots</span>
        </div>
        <div class="messages" id="messages">
            <div class="message ta-message">Hello! I am your C++ CodingRabbit. What are you working on today?</div>
        </div>
        <div>
            <select id="modeSelect">
                <option value="Homework Assist">Mode: Homework Assist</option>
                <option value="Study Assist">Mode: Study Assist</option>
            </select>
            <textarea id="chatInput" placeholder="Ask a question... (Enter to send, Shift+Enter for new line)"></textarea>
            <div style="display: flex; gap: 4px; margin-top: 4px;">
                <button id="terminalBtn" style="background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); flex: 1;">Start Tracked Terminal</button>
                <button id="exportBtn" style="background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); flex: 1;">Export Chat</button>
                <button id="stopwatchBtn" style="background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); flex: 1;">⏸ Pause Time</button>
            </div>
        </div>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const input = document.getElementById('chatInput');
        const modeSelect = document.getElementById('modeSelect');
        const terminalBtn = document.getElementById('terminalBtn');
        const exportBtn = document.getElementById('exportBtn');
        const stopwatchBtn = document.getElementById('stopwatchBtn');
        const signOutBtn = document.getElementById('signOutBtn');
        const messages = document.getElementById('messages');
        
        let isPaused = ${isPaused};
        let elapsedSeconds = ${elapsed};
        let timerInterval = null;

        function formatTime(seconds) {
            const h = Math.floor(seconds / 3600).toString().padStart(2, '0');
            const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, '0');
            const s = (seconds % 60).toString().padStart(2, '0');
            return h + ':' + m + ':' + s;
        }

        function updateStopwatchUI() {
            if (isPaused) {
                stopwatchBtn.innerText = '▶ Resume (' + formatTime(elapsedSeconds) + ')';
            } else {
                stopwatchBtn.innerText = '⏸ Pause (' + formatTime(elapsedSeconds) + ')';
            }
        }

        function startTimer() {
            if (timerInterval) clearInterval(timerInterval);
            timerInterval = setInterval(() => {
                if (!isPaused) {
                    elapsedSeconds++;
                    updateStopwatchUI();
                }
            }, 1000);
        }

        updateStopwatchUI();
        startTimer();
        
        let thinkingElement = null;

        modeSelect.addEventListener('change', () => {
            vscode.postMessage({ type: 'modeChanged', mode: modeSelect.value });
        });

        terminalBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'startTerminal' });
        });

        signOutBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'authSignOut' });
        });
        
        exportBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'exportChat' });
        });
        
        stopwatchBtn.addEventListener('click', () => {
            // Manual toggle sends a fake activity burst if resuming, or force-sets state temporarily
            // Note: Auto-timer will naturally override this after 5s of inactivity
            isPaused = !isPaused;
            updateStopwatchUI();
            vscode.postMessage({ type: 'toggleStopwatch', isPaused, elapsedSeconds });
        });
        
        // Signal that the webview DOM is fully loaded and ready to receive messages
        vscode.postMessage({ type: 'webviewReady' });
        
        input.addEventListener('keydown', (event) => {
            // Typing is an activity
            vscode.postMessage({ type: 'toggleStopwatch', isPaused: false, elapsedSeconds });
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault(); // Prevent default newline
                const text = input.value.trim();
                const mode = modeSelect.value;
                if (text) {
                    addMessage(text, 'user-message');
                    vscode.postMessage({ type: 'askTA', text, mode });
                    input.value = '';
                }
            }
        });

        window.addEventListener('message', event => {
            const message = event.data;
            switch (message.type) {
                case 'syncStopwatch':
                    isPaused = message.isPaused;
                    elapsedSeconds = message.elapsedSeconds;
                    updateStopwatchUI();
                    break;
                case 'clearChat':
                    messages.innerHTML = '';
                    break;
                case 'addResponse':
                    if (message.isThinking) {
                        thinkingElement = addMessage(message.text, 'ta-message');
                    } else {
                        const content = message.isHtml ? message.html : message.text;
                        const msgClass = message.isUser ? 'user-message' : 'ta-message';
                        if (thinkingElement && !message.isUser) {
                            if (message.isHtml) {
                                thinkingElement.innerHTML = content;
                            } else {
                                thinkingElement.innerText = content;
                            }
                            appendFeedbackButtons(thinkingElement);
                            thinkingElement = null;
                        } else {
                            addMessage(content, msgClass, message.isHtml);
                        }
                    }
                    // Scroll to bottom
                    messages.scrollTop = messages.scrollHeight;
                    break;
                case 'updateCarrots':
                    const cc = document.getElementById('carrotCount');
                    if (cc) cc.innerText = \`🥕 \${message.count} Carrots\`;
                    break;
            }
        });

        function appendFeedbackButtons(div) {
            const msgIndex = document.querySelectorAll('.message').length;
            const feedbackDiv = document.createElement('div');
            feedbackDiv.style.marginTop = '0px';
            feedbackDiv.style.display = 'flex';
            feedbackDiv.style.gap = '8px';
            feedbackDiv.style.justifyContent = 'flex-end';
            feedbackDiv.style.opacity = '0.7';
            
            const upBtn = document.createElement('button');
            upBtn.innerText = '👍';
            upBtn.style.background = 'transparent';
            upBtn.style.width = 'auto';
            upBtn.style.padding = '4px 8px';
            upBtn.title = 'Good response';
            
            const downBtn = document.createElement('button');
            downBtn.innerText = '👎';
            downBtn.style.background = 'transparent';
            downBtn.style.width = 'auto';
            downBtn.style.padding = '4px 8px';
            downBtn.title = 'Bad response';
            
            upBtn.onclick = () => {
                vscode.postMessage({ type: 'feedback', rating: 'up', messageIndex: msgIndex });
                upBtn.style.background = 'var(--vscode-button-background)';
                downBtn.style.background = 'transparent';
            };
            
            downBtn.onclick = () => {
                vscode.postMessage({ type: 'feedback', rating: 'down', messageIndex: msgIndex });
                downBtn.style.background = 'var(--vscode-button-background)';
                upBtn.style.background = 'transparent';
            };
            
            feedbackDiv.appendChild(upBtn);
            feedbackDiv.appendChild(downBtn);
            div.appendChild(feedbackDiv);
        }

        function addMessage(content, className, isHtml = false) {
            const div = document.createElement('div');
            div.className = 'message ' + className;
            if (isHtml) {
                div.innerHTML = content;
            } else {
                div.innerText = content;
            }
            messages.appendChild(div);
            
            if (className.includes('ta-message')) {
                appendFeedbackButtons(div);
            }
            
            // Scroll to the bottom to ensure the user sees the latest response and carrot updates
            messages.scrollTop = messages.scrollHeight;
            return div;
        }
    </script>
</body>
</html>`;
    }
}
