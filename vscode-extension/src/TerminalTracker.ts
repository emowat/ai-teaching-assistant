import * as vscode from 'vscode';
import * as pty from 'node-pty';

export let terminalBuffer: string[] = [];
export let lastExitCode: number | null = null;

export function trackTerminal() {
    const writeEmitter = new vscode.EventEmitter<string>();
    
    const customEnv = Object.assign({}, process.env as { [key: string]: string });
    // Inject the invisible ANSI hook to report the exact exit code of the last command
    customEnv['PROMPT_COMMAND'] = 'echo -ne "\\033]999;$?\\007"';

    // Create a real bash PTY instead of a fragile child_process pipe
    const bashProcess = pty.spawn('bash', [], {
        name: 'xterm-color',
        cols: 80,
        rows: 30,
        cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.env.HOME || '',
        env: customEnv
    });

    bashProcess.onData((data) => {
        // Intercept our custom invisible hook for the exit code
        const exitCodeMatch = data.match(/\x1b\]999;(\d+)\x07/);
        if (exitCodeMatch) {
            lastExitCode = parseInt(exitCodeMatch[1], 10);
            
            // Keep only the last 5 chunks of the buffer on a successful command
            if (lastExitCode === 0 && terminalBuffer.length > 5) {
                terminalBuffer.splice(0, terminalBuffer.length - 5);
            }
            // Strip the invisible code so it doesn't end up in the buffer or VS Code's renderer
            data = data.replace(/\x1b\]999;\d+\x07/g, '');
        }

        terminalBuffer.push(data);
        if (terminalBuffer.length > 50) terminalBuffer.shift();
        writeEmitter.fire(data);
    });

    bashProcess.onExit((e) => {
        // Fallback for when the shell actually terminates
        lastExitCode = e.exitCode;
        writeEmitter.fire(`\r\n[Process exited with code ${e.exitCode}]\r\n`);
    });

    let currentInput = '';
    const pseudoterminal: vscode.Pseudoterminal = {
        onDidWrite: writeEmitter.event,
        open: () => {
            writeEmitter.fire('CodingRabbit Tracked Console Started.\r\n');
        },
        close: () => {
            bashProcess.kill();
        },
        handleInput: (data: string) => {
            if (data === '\r') {
                if (currentInput.trim() === 'clear') {
                    terminalBuffer.length = 0; // Wipe the LLM's terminal memory!
                }
                currentInput = '';
            } else if (data === '\x7f') { // Backspace
                currentInput = currentInput.slice(0, -1);
            } else {
                currentInput += data;
            }
            bashProcess.write(data);
        }
    };

    const terminal = vscode.window.createTerminal({ name: 'TA Console', pty: pseudoterminal });
    terminal.show();
}
