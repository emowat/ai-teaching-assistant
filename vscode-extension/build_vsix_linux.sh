#!/bin/bash
# Builds the VSCode Extension with Linux binaries via Docker
# Run this from the host machine (Mac/Windows)

set -e

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "Usage: $0 <EXTENSION_DIR> <DEST_DIR> [API_URL]"
    echo "Example: $0 /path/to/vscode-extension /path/to/assignment5/.devcontainer"
    exit 1
fi

# Ensure destination directory exists and resolve absolute paths
EXTENSION_DIR=$(cd "$1" && pwd)
mkdir -p "$2"
DEST_DIR=$(cd "$2" && pwd)
ASSIGNMENT_ROOT=$(dirname "$DEST_DIR")

if [ -z "${3:-}" ]; then
    echo "No API_URL supplied. Attempting to discover the AWS ELB URL automatically..."
    if ! aws sts get-caller-identity >/dev/null 2>&1; then
        echo "ERROR: Not connected to AWS. Please login via AWS SSO."
        exit 1
    fi
    ELB_DNS=$(aws elbv2 describe-load-balancers --query 'LoadBalancers[?contains(LoadBalancerName, `codingrabbit-rag-eng`)].DNSName' --output text)
    if [ -z "$ELB_DNS" ] || [ "$ELB_DNS" = "None" ]; then
        echo "ERROR: Could not find the codingrabbit-rag-eng load balancer in AWS."
        exit 1
    fi
    API_BASE_URL="http://${ELB_DNS}"
    echo "Found AWS ELB URL: $API_BASE_URL"
else
    API_BASE_URL="$3"
fi

# Automatically initialize assignment directory with templates if missing
echo "Updating assignment directory with CodingRabbit templates..."
mkdir -p "$ASSIGNMENT_ROOT/.vscode"
cp "$EXTENSION_DIR/assignment_template/.devcontainer/devcontainer.json" "$DEST_DIR/"
cp "$EXTENSION_DIR/assignment_template/.devcontainer/Dockerfile" "$DEST_DIR/"
cp "$EXTENSION_DIR/assignment_template/.vscode/extensions.json" "$ASSIGNMENT_ROOT/.vscode/"
cp "$EXTENSION_DIR/assignment_template/.vscode/settings.json" "$ASSIGNMENT_ROOT/.vscode/"

if [ -n "$API_BASE_URL" ]; then
    echo "Injecting custom API URL into package.json: $API_BASE_URL"
    # Create backup and replace default API URL using | as delimiter
    sed -i.bak "s|\"default\": \"http://127.0.0.1:8001\"|\"default\": \"$API_BASE_URL\"|g" "$EXTENSION_DIR/package.json"
    
    echo "Injecting custom API URL into .vscode/settings.json: $API_BASE_URL"
    sed -i.bak "s|\"codingRabbit.apiBaseUrl\": \".*\"|\"codingRabbit.apiBaseUrl\": \"$API_BASE_URL\"|g" "$ASSIGNMENT_ROOT/.vscode/settings.json"
    rm -f "$ASSIGNMENT_ROOT/.vscode/settings.json.bak"
    
    echo "Injecting custom API URL into devcontainer.json: $API_BASE_URL"
    sed -i.bak "s|\"codingRabbit.apiBaseUrl\": \".*\"|\"codingRabbit.apiBaseUrl\": \"$API_BASE_URL\"|g" "$DEST_DIR/devcontainer.json"
    rm -f "$DEST_DIR/devcontainer.json.bak"
fi

echo "Spawning headless Linux Docker container to cross-compile native dependencies and fetch WASM binaries..."
docker run --rm -v "$EXTENSION_DIR:/ext" node:18-bullseye /bin/bash -c "cd /ext && rm -rf node_modules && npm install && mkdir -p media/wasm && cp node_modules/web-tree-sitter/tree-sitter.wasm media/wasm/ || true && curl -sSL -o media/wasm/tree-sitter-cpp.wasm https://unpkg.com/tree-sitter-wasms/out/tree-sitter-cpp.wasm"

echo "Compiling TypeScript natively on host..."
cd "$EXTENSION_DIR"
npm run compile

echo "Packaging .vsix..."
rm -f coding-rabbit-*.vsix
npx vsce package --allow-missing-repository --allow-star-activation

if [ -n "$API_BASE_URL" ]; then
    echo "Restoring original package.json..."
    mv "$EXTENSION_DIR/package.json.bak" "$EXTENSION_DIR/package.json"
fi

echo "Copying to Dev Container directory..."
cp coding-rabbit-*.vsix "$DEST_DIR/"

echo "Updating assignment_template..."
rm -f "$EXTENSION_DIR/assignment_template/.devcontainer/"coding-rabbit-*.vsix
cp coding-rabbit-*.vsix "$EXTENSION_DIR/assignment_template/.devcontainer/"

echo "Done! Reinstall the VSIX in VS Code to apply changes."
