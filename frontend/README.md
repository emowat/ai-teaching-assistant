# codingrabbit.dev — Frontend

React 18 + Vite 8 + TypeScript SPA. Authenticates via AWS Cognito (OIDC), connects to the `rag_eng` FastAPI backend.

## Stack

| Layer | Library |
|---|---|
| Framework | React 18, Vite 8 |
| Language | TypeScript (strict) |
| Auth | `react-oidc-context`, `oidc-client-ts` |
| Editor | `@monaco-editor/react` (lazy-loaded) |
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
│   ├── CodeEditor.tsx    Monaco wrapper (C++, VS Dark, line decorations)
│   ├── ConsolePanel.tsx  Compiler output display (stdout/stderr/exit code)
│   ├── FileExplorer.tsx  Collapsible file tree with add/delete
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
│   └── StudentInterface.tsx  IDE: file explorer + Monaco + console + Socratic chat
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

`StudentInterface` maintains a `Record<string, string>` of filenames → content:
- **FileExplorer** (left panel, 188 px, collapsible to 36 px): add files with `+`, delete with hover `×` + confirmation click. Clicking a file in collapsed mode auto-expands.
- **Tab bar**: dynamically generated from the files map, scrollable for many open tabs.
- **Monaco editor**: `key={activeFile}` forces a fresh instance per file; language is inferred from extension.
- **ConsolePanel**: shows compile stdout/stderr, exit code, and elapsed time.

## Admin Gradio tab

The "RAG Query Console" tab in `AdminDashboard` probes `VITE_API_BASE_URL/gradio` every 30 seconds:
- Enabled → embeds Gradio in an `<iframe>`.
- Disabled or unreachable → tab is greyed out with a tooltip.
