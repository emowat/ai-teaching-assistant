#!/bin/bash
# Builds the VSCode Extension with Linux binaries via Docker
# Run this from the host machine (Mac/Windows)

set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <EXTENSION_DIR> <DEST_DIR>"
    echo "Example: $0 /path/to/vscode-extension /path/to/assignment5/.devcontainer"
    exit 1
fi

# Convert paths to absolute paths for Docker volume mounting
EXTENSION_DIR=$(cd "$1" && pwd)
DEST_DIR=$(cd "$2" && pwd)

echo "Spawning headless Linux Docker container to cross-compile native dependencies..."
docker run --rm -v "$EXTENSION_DIR:/ext" node:18-bullseye /bin/bash -c "cd /ext && rm -rf node_modules && npm install"

echo "Compiling TypeScript natively on host..."
cd "$EXTENSION_DIR"
npm run compile

echo "Packaging .vsix..."
npx vsce package --allow-missing-repository

echo "Copying to Dev Container directory..."
cp socratic-ta-*.vsix "$DEST_DIR/"

echo "Done! Reinstall the VSIX in VS Code to apply changes."
