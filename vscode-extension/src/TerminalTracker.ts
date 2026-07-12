import * as vscode from 'vscode';
import { spawn } from 'child_process';

export let terminalBuffer: string[] = [];
export let lastExitCode: number | null = null;

export function trackTerminal(onActivity?: () => void) {
    const writeEmitter = new vscode.EventEmitter<string>();
    
    const customEnv = Object.assign({}, process.env as { [key: string]: string });
    // Inject the invisible ANSI hook to report the exact exit code of the last command
    customEnv['PROMPT_COMMAND'] = 'echo -ne "\\033]999;$?\\007"';

    // Create a bash process using child_process instead of node-pty to avoid native binding crashes
    const bashProcess = spawn('bash', ['-i'], {
        cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.env.HOME || '',
        env: customEnv
    });

    const handleData = (data: Buffer) => {
        if (onActivity) onActivity();
        let str = data.toString();
        // Intercept our custom invisible hook for the exit code
        const exitCodeMatch = str.match(/\x1b\]999;(\d+)\x07/);
        if (exitCodeMatch) {
            lastExitCode = parseInt(exitCodeMatch[1], 10);
            
            // Keep only the last 5 chunks of the buffer on a successful command
            if (lastExitCode === 0 && terminalBuffer.length > 5) {
                terminalBuffer.splice(0, terminalBuffer.length - 5);
            }
            // Strip the invisible code so it doesn't end up in the buffer or VS Code's renderer
            str = str.replace(/\x1b\]999;\d+\x07/g, '');
        }

        terminalBuffer.push(str);
        if (terminalBuffer.length > 50) terminalBuffer.shift();
        
        // Convert LFs to CRLFs for VS Code's xterm.js terminal
        const formatted = str.replace(/\r?\n/g, '\r\n');
        writeEmitter.fire(formatted);
    };

    bashProcess.stdout.on('data', handleData);
    bashProcess.stderr.on('data', handleData);

    bashProcess.on('exit', (code) => {
        // Fallback for when the shell actually terminates
        lastExitCode = code;
        writeEmitter.fire(`\r\n[Process exited with code ${code}]\r\n`);
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
            if (onActivity) onActivity();
            if (data === '\r') {
                if (currentInput.trim() === 'clear') {
                    terminalBuffer.length = 0; // Wipe the LLM's terminal memory!
                }
                currentInput = '';
                bashProcess.stdin.write('\n'); // Bash expects \n
            } else if (data === '\x7f') { // Backspace
                currentInput = currentInput.slice(0, -1);
            } else {
                currentInput += data;
            }
            
            if (data !== '\r') {
                bashProcess.stdin.write(data);
            }
        }
    };

    const terminal = vscode.window.createTerminal({ name: 'TA Console', pty: pseudoterminal });
    terminal.show();
}
