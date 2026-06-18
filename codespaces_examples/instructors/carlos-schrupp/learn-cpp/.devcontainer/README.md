# Devcontainer Scaffold

This directory now mirrors the short-term Codespaces contract:

- `devcontainer.json` installs the pinned CodingRabbit `.vsix`
- `Dockerfile` provides the C++ toolchain
- the repo-level `.vscode` files disable Copilot and keep the extension in
  CodingRabbit mode

Before using this as a real week repo:
- confirm the `.vsix` version matches the current extension build
- set `RAG_ENG_URL` in the repo or organization environment
- test the launch in a dedicated GitHub repo, since Codespaces launches per repo
