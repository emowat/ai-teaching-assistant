import * as vscode from 'vscode';
import * as pty from 'node-pty';

export let terminalBuffer: string[] = [];
export let lastExitCode: number | null = null;

let activeTerminal: vscode.Terminal | null = null;

export function trackTerminal(onActivity?: () => void) {
    if (activeTerminal) {
        activeTerminal.show();
        return;
    }
    const writeEmitter = new vscode.EventEmitter<string>();

    const customEnv = Object.assign({}, process.env as { [key: string]: string });
    // Inject the invisible ANSI hook to report the exact exit code of the last command
    customEnv['PROMPT_COMMAND'] = 'echo -ne "\\033]999;$?\\007"';

    // A real PTY (not plain child_process pipes) gives us correct keystroke echo,
    // Backspace-erase, Ctrl-C/Ctrl-D, and raw-mode program support (vim, gdb, etc.)
    // for free via the kernel's own line discipline — none of that has to be
    // hand-rolled here. node-pty ships prebuilt binaries for macOS/Windows but not
    // Linux, so it compiles from source on install; that's why the devcontainer's
    // build-essential/python3 are there. Ship a Linux-x64 build in the .vsix, never
    // whatever platform the extension happened to be packaged on.
    const bashProcess = pty.spawn('bash', [], {
        name: 'xterm-256color',
        cols: 80,
        rows: 30,
        // An empty-string cwd here isn't "no preference" - node-pty passes it straight
        // through to chdir(), and an empty path silently keeps whatever cwd the
        // extension host itself launched with (e.g. "/" during container init), not
        // the workspace folder. Only ever hand it a real, non-empty path.
        cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.env.HOME || '/home/student',
        env: customEnv
    });

    bashProcess.onData((data) => {
        if (onActivity) onActivity();
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
        if (activeTerminal) activeTerminal = null;
        writeEmitter.fire(`\r\n[Process exited with code ${e.exitCode}]\r\n`);
    });

    // Only used to detect the "clear" keyword to wipe the LLM's terminal memory —
    // the PTY itself already handles real echo/backspace/line-editing, so this
    // doesn't need to track anything beyond "what's been typed since Enter".
    let currentInput = '';
    const pseudoterminal: vscode.Pseudoterminal = {
        onDidWrite: writeEmitter.event,
        open: () => {
            writeEmitter.fire('CodingRabbit Tracked Console Started.\r\n');
        },
        close: () => {
            bashProcess.kill();
        },
        setDimensions: (dimensions) => {
            bashProcess.resize(dimensions.columns, dimensions.rows);
        },
        handleInput: (data: string) => {
            if (onActivity) onActivity();
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
    activeTerminal = terminal;

    // Clear reference if the user manually kills it by pressing the trash can
    vscode.window.onDidCloseTerminal((closedTerminal) => {
        if (closedTerminal === activeTerminal) {
            activeTerminal = null;
        }
    });

    terminal.show();
}
