#!/bin/bash
# Builds the VSCode Extension with Linux binaries via Docker
# Run this from the host machine (Mac/Windows)

set -e

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "Usage: $0 <EXTENSION_DIR> <DEST_DIR> [API_URL]"
    echo "Example: $0 /path/to/vscode-extension /path/to/assignment5/.devcontainer http://host.docker.internal:8001/api/chat"
    exit 1
fi

# Ensure destination directory exists and resolve absolute paths
EXTENSION_DIR=$(cd "$1" && pwd)
mkdir -p "$2"
DEST_DIR=$(cd "$2" && pwd)
ASSIGNMENT_ROOT=$(dirname "$DEST_DIR")
API_URL=${3:-"http://host.docker.internal:8001/api/chat"}

# Automatically initialize assignment directory with templates if missing
echo "Updating assignment directory with CodingRabbit templates..."
mkdir -p "$ASSIGNMENT_ROOT/.vscode"
cp "$EXTENSION_DIR/assignment_template/.devcontainer/devcontainer.json" "$DEST_DIR/"
cp "$EXTENSION_DIR/assignment_template/.devcontainer/Dockerfile" "$DEST_DIR/"
cp "$EXTENSION_DIR/assignment_template/.vscode/extensions.json" "$ASSIGNMENT_ROOT/.vscode/"
cp "$EXTENSION_DIR/assignment_template/.vscode/settings.json" "$ASSIGNMENT_ROOT/.vscode/"

if [ -n "$API_URL" ]; then
    echo "Injecting custom API URL into package.json: $API_URL"
    # Create backup and replace default API URL using | as delimiter
    sed -i.bak "s|\"default\": \"http://127.0.0.1:8001/api/chat\"|\"default\": \"$API_URL\"|g" "$EXTENSION_DIR/package.json"
fi

echo "Spawning headless Linux Docker container to cross-compile native dependencies and fetch WASM binaries..."
docker run --rm -v "$EXTENSION_DIR:/ext" node:18-bullseye /bin/bash -c "cd /ext && rm -rf node_modules && npm install && mkdir -p media/wasm && cp node_modules/web-tree-sitter/tree-sitter.wasm media/wasm/ || true && curl -sSL -o media/wasm/tree-sitter-cpp.wasm https://unpkg.com/tree-sitter-wasms/out/tree-sitter-cpp.wasm"

echo "Compiling TypeScript natively on host..."
cd "$EXTENSION_DIR"
npm run compile

echo "Packaging .vsix..."
rm -f coding-rabbit-*.vsix
npx vsce package --allow-missing-repository --allow-star-activation

if [ -n "$API_URL" ]; then
    echo "Restoring original package.json..."
    mv "$EXTENSION_DIR/package.json.bak" "$EXTENSION_DIR/package.json"
fi

echo "Copying to Dev Container directory..."
cp coding-rabbit-*.vsix "$DEST_DIR/"

echo "Updating assignment_template..."
rm -f "$EXTENSION_DIR/assignment_template/.devcontainer/"coding-rabbit-*.vsix
cp coding-rabbit-*.vsix "$EXTENSION_DIR/assignment_template/.devcontainer/"

echo "Done! Reinstall the VSIX in VS Code to apply changes."
