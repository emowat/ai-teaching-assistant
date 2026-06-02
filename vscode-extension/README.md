# CodingRabbit VS Code Extension

This extension provides an interactive, CodingRabbit Teaching Assistant directly inside VS Code to help students debug C++ code without leaking solutions.

## Features
- **CodingRabbit Chat UI**: A sidebar webview that interacts with the student. Now supports `Enter` to send and `Shift+Enter` for multiline formatting.
- **Study Assist Mode**: A specialized mode that aggressively closes all active editors and terminal panels (`closeAllEditors` / `closePanel`), visually hiding code context so students can focus purely on conceptual questions. Dynamically overrides the LLM's CodingRabbit rules to allow direct explanations.
- **Context Injection**: Automatically grabs the student's active C++ code (`[Code_Context]`) and the output of their latest terminal run (`[Terminal_Context]`) to feed to the LLM.
- **Anti-Cheat Tracking (MD5 Hashing)**: Detects large copy/paste events while smartly ignoring internal file restructuring via MD5 block hashing. It logs the unified diff to a local Output Channel ("TA Anti-Cheat Logs") and injects a `Likely_Paste_Detected: true` flag into the prompt so the TA can interrogate the student about pasted code.
- **Hard Mode (Copilot Kill Switch)**: Aggressively checks for `github.copilot` and `github.copilot-chat` upon activation. If a student bypasses the Dev Container settings and installs Copilot locally, the TA will completely block all prompts and return an un-ignorable error until Copilot is manually disabled. Note: For deployment, ensure `.vscode/extensions.json` contains `"unwantedRecommendations": ["github.copilot", "github.copilot-chat"]` to actively prompt students to disable them.
- **Gamified "Carrot" Tracking**: The UI maintains a dynamic "Carrot" token balance. Carrots are deducted when the student uses a `[DEBUG_IDEA_UNLOCKED]` hint or is penalized with an `[END_CHAT]` termination.
- **Terminal Tracker**: Hooks into the VS Code terminal to silently buffer the output and exit code of the last compiled/run C++ binary.

## AWS Migration Checklist (Production Architecture)

Currently, this extension functions as a "Thick Client" for local testing with an Ollama Dev Container. It contains the secret LLM System Prompt and makes HTTP calls directly to the local model API. 

When migrating to a cloud-based AWS infrastructure for production, the following architectural changes **MUST** be made:

### 1. Move the System Prompt to the Backend
**Why:** The `.vsix` file is a public asset that students can unzip. If the System Prompt remains in `TAChatViewProvider.ts`, students will read the hidden rules and adversarial defenses.
**Action:** Remove the `systemPrompt` constant from the extension. The extension should only act as a thin client, sending the user's message, `[Code_Context]`, and `[Terminal_Context]` as a JSON payload to the AWS API endpoint. The AWS backend will securely inject the System Prompt and handle the LLM call.

### 2. Implement Authentication & Rate Limiting
**Why:** To prevent abuse of the cloud infrastructure and token billing.
**Action:** The extension needs to retrieve an auth token (e.g., via OAuth or a Berkeley student portal login) and attach it to the `Authorization` header of the `fetch` request. The AWS API Gateway should enforce rate limits per student.

### 3. Update the API Endpoint
**Why:** The extension currently hardcodes a Docker Bridge IP (`http://192.168.65.254:11434/api/chat`) to reach the local Ollama instance.
**Action:** Update the `apiUrl` in `TAChatViewProvider.ts` (or the VS Code Workspace settings configuration) to point to the secure AWS load balancer or API Gateway endpoint (e.g., `https://api.cs210.berkeley.edu/v1/chat`).

### 4. Migrate RAG (VectorDB) Lookups
**Why:** The client extension should not manage heavy databases or web scraping.
**Action:** The AWS backend should handle all RAG document retrieval (e.g., searching an AWS OpenSearch or ChromaDB instance populated with `cppreference` docs) *before* appending it to the LLM prompt. The VS Code extension should not perform any RAG logic itself.

### 5. Centralize Anti-Cheat Telemetry
**Why:** The copy/paste diff patches currently log to a local VS Code Output Channel, which instructors cannot see.
**Action:** Modify the `PasteTracker` logic in `extension.ts` to push the unified diffs to a secure AWS telemetry/logging endpoint (e.g., CloudWatch or a DynamoDB table) so TAs and instructors can review flagged students asynchronously.

## Testing & Deployment (For Teammates)

We have provided an `assignment_template` directory containing the strict `.devcontainer` and `.vscode` configurations used to lock down the student environment and uninstall Copilot.

To test the extension locally:
1. Do **NOT** commit the `.vsix` binary to this source repository.
2. Run the build script to compile the `.vsix` and automatically inject it into the template's dev container directory:
   ```bash
   ./build_vsix_linux.sh . ./assignment_template/.devcontainer
   ```
3. Open the `assignment_template` folder in VS Code.
4. Click **"Reopen in Container"**. VS Code will automatically install the `.vsix` and apply the Hard Mode settings.
