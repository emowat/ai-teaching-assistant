#!/usr/bin/env bash
set -euo pipefail

IMAGE="${RUNNER_IMAGE:-codingrabbit-cpp-runner:0.1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

docker build -t "$IMAGE" "$ROOT/runner"
echo "Built $IMAGE"
echo "Run: docker images | grep codingrabbit-cpp-runner"
