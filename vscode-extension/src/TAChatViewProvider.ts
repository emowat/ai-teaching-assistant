import * as vscode from 'vscode';
import { terminalBuffer, lastExitCode } from './TerminalTracker';
import * as Parser from 'web-tree-sitter';

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
    private _adversarialWarningCount: number = 0;

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
        private readonly _pasteStatusByUri: Map<string, boolean>,
        private readonly _context: vscode.ExtensionContext
    ) {}

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

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._extensionUri]
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview, this._carrots);

        webviewView.webview.onDidReceiveMessage(async (data) => {
            switch (data.type) {
                case 'askTA': {
                    await this._handleAskTA(data.text, data.mode, webviewView);
                    break;
                }
                case 'startTerminal': {
                    vscode.commands.executeCommand('coding-rabbit.startTerminal');
                    break;
                }
                case 'modeChanged': {
                    if (data.mode === 'Study Assist') {
                        // Close the terminal/panel area
                        vscode.commands.executeCommand('workbench.action.closePanel');
                        // Close all editors so the focus is entirely on the chat
                        vscode.commands.executeCommand('workbench.action.closeAllEditors');
                    }
                    break;
                }
            }
        });
    }

    private async _handleAskTA(userMessage: string, mode: string, webviewView: vscode.WebviewView) {
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
            likelyPasteDetected = this._pasteStatusByUri.get(document.uri.toString()) || false;
            // Clear the paste status so the TA only interrogates them once per paste
            if (likelyPasteDetected) {
                this._pasteStatusByUri.set(document.uri.toString(), false);
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
                    (while_statement) @loop
                `;
                const query = this._cppLanguage!.query(queryStr);
                const matches = query.matches(tree.rootNode);
                
                let focusScope = "global";
                const cursorPos = editor.selection.active;
                let cursorNode: any = tree.rootNode.descendantForPosition({ row: cursorPos.line, column: cursorPos.character });
                while (cursorNode) {
                    if (cursorNode.type === "function_definition") {
                        const decl = cursorNode.childForFieldName("declarator");
                        if (decl) {
                            const get_id = (n: any): string | null => {
                                if (n.type === 'identifier') return n.text.split('::').pop() || n.text;
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
                    Has_Recursion: false
                };
                
                for (const match of matches) {
                    for (const capture of match.captures) {
                        const tag = capture.name;
                        const node = capture.node;
                        const text = node.text;
                        const cleanName = text.split("::").pop() || text;

                        if (tag === "call_id") {
                            if (cleanName === "malloc") features.Has_Malloc = true;
                            if (cleanName === "free") features.Has_Free = true;
                            
                            // Recursion check
                            let curr: any = node.parent;
                            while (curr) {
                                if (curr.type === "function_definition") {
                                    const decl = curr.childForFieldName("declarator");
                                    if (decl) {
                                        const get_id = (n: any): string | null => {
                                            if (n.type === 'identifier') return n.text.split('::').pop() || n.text;
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
                        }
                    }
                }
                
                const variableTypes: Record<string, string> = {};
                const typeQueryStr = `
                    (declaration) @decl
                    (parameter_declaration) @decl
                    (field_declaration) @decl
                `;
                const typeQuery = this._cppLanguage!.query(typeQueryStr);
                const typeMatches = typeQuery.matches(tree.rootNode);
                
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
                if (arrayQuery.matches(tree.rootNode).length > 0) {
                    // Not officially in python script's Features block, but mentioned in prompt rules.
                    // We'll leave it out of Features to strictly match python, but we can add it if needed.
                }
                
                astMetadata = `AST_Metadata:\n- Focus_Scope: "${focusScope}"\n- Variable_Types: ${JSON.stringify(variableTypes)}\n- Features: ${JSON.stringify(features)}`;
            } catch (err) {
                TAChatViewProvider.getOutputChannel().appendLine(`AST Parsing Error: ${err}`);
                astMetadata = 'AST_Metadata: (Error Parsing AST)';
            }
        }

        const rawTerminalOutput = terminalBuffer.join('').trim();
        // Strip ANSI escape codes (colors, cursor movements, etc.) so the LLM can read the plain text history
        const terminalOutput = rawTerminalOutput.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
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

        // The dynamic context that changes on every turn
        const pasteContext = likelyPasteDetected ? "Likely_Paste_Detected: true\n" : "Likely_Paste_Detected: false\n";
        const dynamicContext = `[State_Tracking]
Session_Style_Nudged: ${this._hasGivenStyleNudge}
Session_Adversarial_Warnings: ${this._adversarialWarningCount}
[Code_Context]
Mode: ${mode}
${pasteContext}Raw_Code:
${rawCode}
${astMetadata}
[Terminal_Context]
Exit_Code: ${exitCode}
Output:
${terminalOutput}`;

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
        const apiMessages = windowedHistory.map(msg => ({ role: msg.role, content: msg.content }));
        
        // Inject dynamic context into the very last user message for perfect KV caching
        apiMessages[apiMessages.length - 1].content = `${dynamicContext}\n\n[Student_Question]\n${userMessage}`;

        // 3. Call Ollama API
        try {
            const outputChannel = TAChatViewProvider.getOutputChannel();
            outputChannel.appendLine(`\n--- NEW REQUEST (${new Date().toLocaleTimeString()}) ---`);
            outputChannel.appendLine(`[Code_Context]`);
            outputChannel.appendLine(`Mode: ${mode}`);
            outputChannel.appendLine(`Likely_Paste_Detected: ${likelyPasteDetected}`);
            outputChannel.appendLine(`Raw_Code:\n${rawCode}`);
            outputChannel.appendLine(`${astMetadata}`);
            outputChannel.appendLine(`[Terminal_Context]\nExit_Code: ${exitCode}\nOutput:\n${terminalOutput}`);
            outputChannel.appendLine(`---------------------------------------------------`);

            const apiUrl = vscode.workspace.getConfiguration('codingRabbit').get('apiUrl') || 'http://host.docker.internal:8000/api/chat';
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
            const response = await fetch(apiUrl as string, {
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
            const rawTaResponse = data.message?.content || "No response generated.";
            
            let displayResponse = rawTaResponse;
            
            // Strip the <analysis> block out of the text displayed to the user UI
            const analysisMatch = displayResponse.match(/<analysis>[\s\S]*?<\/analysis>/);
            if (analysisMatch) {
                displayResponse = displayResponse.replace(analysisMatch[0], '').trim();
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
                webviewView.webview.postMessage({ type: 'addResponse', text: displayResponse, isThinking: false });
            } else {
                if (displayResponse.includes('[DEBUG_IDEA_UNLOCKED]')) {
                    displayResponse = displayResponse.replace(/\[DEBUG_IDEA_UNLOCKED\]/g, '').trim();
                    if (mode !== 'Study Assist') {
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
                
                // Send the stripped response to the UI
                webviewView.webview.postMessage({ type: 'addResponse', text: displayResponse, isThinking: false });
            }
        } catch (err: any) {
            const outputChannel = TAChatViewProvider.getOutputChannel();
            outputChannel.appendLine(`\n[API ERROR]: ${err.message || err}`);
            
            webviewView.webview.postMessage({ 
                type: 'addResponse', 
                text: "Uh oh, my circuits are a bit fried. Make sure Ollama is running locally and the API URL is reachable!", 
                isThinking: false 
            });
        }
    }

    private _getHtmlForWebview(webview: vscode.Webview, carrots: number) {
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
    </style>
</head>
<body>
    <div class="chat-container">
        <div style="font-weight: bold; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--vscode-widget-border);">
            Coding Rabbit: TA Chat
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
            <button id="terminalBtn" style="background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); margin-top: 4px;">Start Tracked Terminal</button>
        </div>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const input = document.getElementById('chatInput');
        const modeSelect = document.getElementById('modeSelect');
        const terminalBtn = document.getElementById('terminalBtn');
        const messages = document.getElementById('messages');
        
        let thinkingElement = null;

        modeSelect.addEventListener('change', () => {
            if (modeSelect.value === 'Study Assist') {
                vscode.postMessage({ type: 'modeChanged', mode: 'Study Assist' });
            }
        });

        terminalBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'startTerminal' });
        });
        
        input.addEventListener('keydown', (event) => {
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
                case 'addResponse':
                    if (message.isThinking) {
                        thinkingElement = addMessage(message.text, 'ta-message');
                    } else {
                        if (thinkingElement) {
                            thinkingElement.innerText = message.text;
                            thinkingElement = null;
                        } else {
                            addMessage(message.text, 'ta-message');
                        }
                    }
                    break;
                case 'updateCarrots':
                    const cc = document.getElementById('carrotCount');
                    if (cc) cc.innerText = \`🥕 \${message.count} Carrots\`;
                    break;
            }
        });

        function addMessage(text, className) {
            const div = document.createElement('div');
            div.className = 'message ' + className;
            div.innerText = text; // simple text rendering for now (no markdown parsing yet)
            messages.appendChild(div);
            // Scroll to the bottom to ensure the user sees the latest response and carrot updates
            messages.scrollTop = messages.scrollHeight;
            return div;
        }
    </script>
</body>
</html>`;
    }
}
