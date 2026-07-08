# codingrabbit.dev — Frontend

React 18 + Vite 8 + TypeScript SPA. Authenticates via AWS Cognito (OIDC), connects to the `rag_eng` FastAPI backend.

## Stack

| Layer | Library |
|---|---|
| Framework | React 18, Vite 8 |
| Language | TypeScript (strict) |
| Auth | `react-oidc-context`, `oidc-client-ts` |
| Editor | Legacy Monaco components kept only for fallback/demo use |
| Charts | `recharts` |
| Styling | Inline styles with design tokens (`src/design/tokens.ts`) |

## Project structure

```
src/
├── api/
│   ├── gradioApi.ts      Gradio availability probe + URL helper
│   └── runApi.ts         POST /run/compile client
├── auth/
│   ├── cognitoConfig.ts  OIDC config factory (WebStorageStateStore)
│   ├── roleAccess.ts     Role → allowed views mapping + utilities
│   ├── signOutCognito.ts Custom Cognito logout (logout_uri, not post_logout_redirect_uri)
│   └── validateCognitoConfig.ts  Startup env-var validation
├── components/
│   ├── CodeEditor.tsx    Legacy Monaco wrapper (fallback/demo only)
│   ├── ConsolePanel.tsx  Legacy compiler output display
│   ├── FileExplorer.tsx  Legacy browser file tree
│   ├── Sidebar.tsx       Tab sidebar (supports disabled + tooltip)
│   └── TopBar.tsx        App bar with role switcher + sign-out
├── demo/
│   └── linkedListCpp.ts  Starter C++ file with intentional bugs
├── design/
│   ├── atoms.tsx         Reusable atoms: Tag, Btn, Card, Stat, Avatar, ProgressBar
│   └── tokens.ts         Design tokens (colors, mono font shorthand)
├── pages/
│   ├── AdminDashboard.tsx    Metrics, AI models, RAG docs, RAG Query Console (Gradio)
│   ├── AuthCallbackPage.tsx  OIDC redirect handler
│   ├── LandingPage.tsx       Unauthenticated landing
│   ├── ProfessorDashboard.tsx Professor view
│   └── StudentInterface.tsx  Codespaces launch/status page for students
├── types/
│   └── navigation.ts     AppView union type
└── App.tsx               Auth-aware router
```

## Local development

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # production build → dist/
npm run lint
```

Requires a `.env` at the repo root with Cognito and API variables. See `.env.example`.
Vite is configured with `envDir: ..` in `frontend/vite.config.ts`, so the frontend reads the repo root `.env` rather than `frontend/.env`.
For production publishing, `deploy/deployment.yaml` supplies the CloudFront
callback and logout URLs that get baked into the static bundle. Keep the repo
root `.env` pointed at localhost for `npm run dev`.

## Authentication flow

1. Unauthenticated users see `LandingPage` with a "Sign in" button.
2. Clicking sign-in redirects to the Cognito Hosted UI.
3. Cognito redirects back to `/auth/callback`; `react-oidc-context` completes the OIDC handshake.
4. `App.tsx` reads `custom:role` from the ID token, calls `getDefaultView(role)`, and renders the appropriate dashboard.
5. Sign-out calls `signOutCognito`, which clears local session state then redirects to Cognito's `/logout?logout_uri=…`.

## Role-based navigation

`src/auth/roleAccess.ts` defines the hierarchy:

```
admin     → [admin, professor, student]
professor → [professor, student]
student   → [student]
```

`TopBar` renders a switcher button for each view in `allowedViews`. Dashboards receive `allowedViews` and `onSignOut` as props.

## Student workspace

The student route is now a Codespaces launch page instead of a browser IDE:
- It points students to the GitHub repo or assignment template configured in the repo root `.env` via `VITE_CODESPACES_TEMPLATE_URL` or `VITE_CODESPACES_REPO_URL` as a fallback.
- The professor dashboard can override those values per section, including the default branch, and the student can pick the active section before launching Codespaces.
- Launch opens GitHub Codespaces in a new browser tab so the student does not lose the CodingRabbit launcher page.
- The launch configuration now comes from the backend bootstrap payload and section launch configs instead of browser `localStorage`.
- It explains that the VS Code extension, terminal, file tree, and compiler all live inside Codespaces.
- It no longer renders the Monaco editor, browser file explorer, or compile panel as the primary workflow.

The Monaco/file-explorer/console components still exist in the codebase as legacy fallback/demo pieces, but they are no longer the default student path.

## Admin Gradio tab

The "RAG Query Console" tab in `AdminDashboard` probes `VITE_API_BASE_URL/gradio/` every 30 seconds:
- Enabled → embeds Gradio in an `<iframe>`.
- Disabled or unreachable → tab is greyed out with a tooltip.

Inside the embedded backend console, the SageMaker, Guardrail, and Pipeline
tabs expose the runtime diagnostics used for model and RAG tuning:
- SageMaker Console: endpoint health, direct invoke, and traffic lights
- Guardrail Console: direct V1 + V2 review of a draft answer before release
- Pipeline Console: retrieval presets, routing / trace overrides, and the
  guardrailed answer path

The AI Models panel in the admin dashboard can route RAG and chat through
Cohere, OpenAI, Bedrock, Ollama, or SageMaker. Under Bedrock, the available
model options include Amazon Nova 2 Lite, Anthropic Claude Sonnet 4.6, and
Anthropic Claude Haiku 4.5. For Haiku 4.5, use the Bedrock inference profile
ID `us.anthropic.claude-haiku-4-5-20251001-v1:0` (or the global profile ID).

The Pipeline tab exposes the retrieval presets used for RAG tuning:
- experiment baseline at `K=8` with `similarity` reranking
- MMR presets at `lambda=0.5`, `0.7`, and `0.9`
- manual overrides for `Top K / Final Results` and `Rerank Strategy`
- course / trace overrides for admin diagnostics
