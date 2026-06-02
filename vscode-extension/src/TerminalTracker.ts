import * as vscode from 'vscode';
import * as pty from 'node-pty';

export let terminalBuffer: string[] = [];
export let lastExitCode: number | null = null;

export function trackTerminal() {
    const writeEmitter = new vscode.EventEmitter<string>();
    
    // Create a real bash PTY instead of a fragile child_process pipe
    const bashProcess = pty.spawn('bash', [], {
        name: 'xterm-color',
        cols: 80,
        rows: 30,
        cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.env.HOME || '',
        env: process.env as { [key: string]: string }
    });

    bashProcess.onData((data) => {
        terminalBuffer.push(data);
        if (terminalBuffer.length > 50) terminalBuffer.shift();
        writeEmitter.fire(data);
    });

    bashProcess.onExit((e) => {
        lastExitCode = e.exitCode;
        writeEmitter.fire(`\r\n[Process exited with code ${e.exitCode}]\r\n`);
    });

    const pseudoterminal: vscode.Pseudoterminal = {
        onDidWrite: writeEmitter.event,
        open: () => {
            writeEmitter.fire('CodingRabbit Tracked Console Started.\r\n');
        },
        close: () => {
            bashProcess.kill();
        },
        handleInput: (data: string) => {
            // No manual echoing! The real PTY handles it natively.
            bashProcess.write(data);
        }
    };

    const terminal = vscode.window.createTerminal({ name: 'TA Console', pty: pseudoterminal });
    terminal.show();
}
