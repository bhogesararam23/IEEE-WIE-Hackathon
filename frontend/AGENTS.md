# HerMediSafe — web app

React 19 + Vite 8 + TypeScript UI for the HerMediSafe API. Every screen reads and
writes through the real backend; there is no mock data layer.

## Layout

- `src/main.tsx` — mounts `App` inside `SessionProvider`
- `src/App.tsx` — signed-in shell: sidebar, header, screen switching, profile modal
- `src/lib/api.ts` — the only place that knows HTTP: one `api` object, the response
  types, token storage, and FastAPI error translation
- `src/lib/session.tsx` — `useSession()` auth context and `useAsync()` data hook
- `src/lib/navigation.ts` — sidebar items and the overview feature grid
- `src/lib/format.ts` — date/time/label helpers
- `src/components/` — `Icon` (inline SVG set) and small shared UI primitives
- `src/screens/` — one file per screen
- `src/index.css` — the whole visual system; screens use these class names

## Talking to the API

`api` sends `Authorization: Bearer <token>` from `localStorage`, and clears the token
on any 401 so the app falls back to the sign-in screen. The base URL comes from
`VITE_API_BASE_URL` (`frontend/.env`, default `http://localhost:8010`). The backend
allows every origin in development, so no Vite proxy is configured.

Add a new endpoint to `api` in `src/lib/api.ts` rather than calling `fetch` from a
screen — the token, error translation, and typing all live there.

## Styling

Tailwind v4 is installed and imported, but the design system is hand-written CSS in
`src/index.css` with flat, semantic class names (`.tool-main`, `.medicine-list`,
`.badge.high`, `.notice.error`). Follow that: reuse the existing classes and add to
`index.css` instead of introducing utility soup into JSX. New component CSS goes
above the `@media` blocks so the responsive overrides still win.

## Commands

```bash
pnpm install     # deps
pnpm dev         # http://localhost:5180 (5173/5174 belong to other projects)
pnpm typecheck   # tsc --noEmit
pnpm build       # typecheck + production bundle into dist/
```

The API must be running for anything past the sign-in screen. See the repository
README for `docker compose up -d db`, migrations, and `seed_demo.py`.

## Conventions

- Screens own their own loading/error state through `useAsync`; they don't throw.
- Screens with no backend endpoint say so in the UI instead of faking a result
  (`src/screens/LocalTools.tsx`).
- No router: the shell switches screens with one `useState` value from
  `src/lib/navigation.ts`. Add a `ScreenId` there, then a branch in `App.tsx`.
