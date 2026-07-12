#!/bin/bash
# Remove real copilot if it managed to install in the mounted volume
chmod -R 777 /home/student/.vscode-remote/extensions/github.copilot-* 2>/dev/null || true
chmod -R 777 /home/student/.vscode-server/extensions/github.copilot-* 2>/dev/null || true
rm -rf /home/student/.vscode-remote/extensions/github.copilot-*
rm -rf /home/student/.vscode-server/extensions/github.copilot-*

# Plant dummy copilot in .vscode-remote (Codespaces)
mkdir -p /home/student/.vscode-remote/extensions/github.copilot-999.0.0
echo '{"name": "copilot", "publisher": "github", "version": "999.0.0", "engines": {"vscode": "^1.0.0"}, "main": "index.js"}' > /home/student/.vscode-remote/extensions/github.copilot-999.0.0/package.json
chmod -R 0555 /home/student/.vscode-remote/extensions/github.copilot-999.0.0

mkdir -p /home/student/.vscode-remote/extensions/github.copilot-chat-999.0.0
echo '{"name": "copilot-chat", "publisher": "github", "version": "999.0.0", "engines": {"vscode": "^1.0.0"}, "main": "index.js"}' > /home/student/.vscode-remote/extensions/github.copilot-chat-999.0.0/package.json
chmod -R 0555 /home/student/.vscode-remote/extensions/github.copilot-chat-999.0.0

# Same for .vscode-server (Local Dev Containers)
mkdir -p /home/student/.vscode-server/extensions/github.copilot-999.0.0
echo '{"name": "copilot", "publisher": "github", "version": "999.0.0", "engines": {"vscode": "^1.0.0"}, "main": "index.js"}' > /home/student/.vscode-server/extensions/github.copilot-999.0.0/package.json
chmod -R 0555 /home/student/.vscode-server/extensions/github.copilot-999.0.0

mkdir -p /home/student/.vscode-server/extensions/github.copilot-chat-999.0.0
echo '{"name": "copilot-chat", "publisher": "github", "version": "999.0.0", "engines": {"vscode": "^1.0.0"}, "main": "index.js"}' > /home/student/.vscode-server/extensions/github.copilot-chat-999.0.0/package.json
chmod -R 0555 /home/student/.vscode-server/extensions/github.copilot-chat-999.0.0
