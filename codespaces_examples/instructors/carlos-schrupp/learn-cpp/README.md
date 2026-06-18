# Carlos Schrupp / Learn C++ Example

This tracked example mirrors the app's `instructor / class / week` organization for
Codespaces testing.

Purpose:
- provide a realistic week-based workspace tree for the student launcher
- seed the example with starter files from `carlos-schrupp/learn-cpp`
- give the team a place to add `.devcontainer` files and pinned `.vsix` builds

Source curriculum:
- https://github.com/carlos-schrupp/learn-cpp/tree/master

Current structure:
- `week-01/` -> starter from `1-hello-world/hello.cpp`
- `week-02/` -> starter from `2-variables/temperature1.cpp`
- `week-03/` -> starter from `3-conditionals-and-logic/coinflip.cpp`
- `week-04/` -> starter from `4-loops/enter_pin.cpp`
- `.devcontainer/` -> controlled Codespaces environment scaffold
- `.vscode/` -> workspace defaults that disable Copilot and point the extension
  at the TA backend

Codespaces note:
- This folder is a content scaffold inside the current repository.
- GitHub Codespaces launches against repositories, not arbitrary folders, so this
  example is for testing organization and devcontainer packaging before the week
  workspaces are broken out into their own repos or branches.
- The `.devcontainer` here mirrors the short-term target: install a pinned
  CodingRabbit `.vsix` from the repo and boot into a controlled C++ environment.
