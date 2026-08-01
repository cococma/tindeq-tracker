# TrainingJournal

A personal climbing-training app: Tindeq Progressor force capture, a training
journal (climbing / workouts / daily wellness), Renpho smart-scale body metrics,
strength trends, and an AI coach that reads your training data.

Everything runs locally: FastAPI + PostgreSQL on your machine, charts in the
browser, BLE capture through the server (the browser never touches Bluetooth).

## Setup

```sh
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env        # fill in DB credentials (+ optional keys below)
createdb tindeq             # if it doesn't exist yet
./venv/bin/python -m app.migrate
```

Optional `.env` keys:

| Key | Enables |
|---|---|
| `ANTHROPIC_API_KEY` | AI coach via the Anthropic API (not needed if the Claude Code CLI is installed — see below) |
| `RENPHO_EMAIL` / `RENPHO_PASSWORD` | Renpho cloud sync (CSV import works without) |

**AI coach backends.** The coach runs on whichever Claude access you have:

- **Claude Code CLI (default)** — if the `claude` CLI is installed and signed
  in, the coach uses your claude.ai subscription: no API key, no per-token
  billing. Install with `curl -fsSL https://claude.ai/install.sh | bash` and
  sign in once (`claude` → `/login`). Optionally run `claude setup-token` and
  put the result in `.env` as `CLAUDE_CODE_OAUTH_TOKEN` so the server never
  depends on the Keychain login. `COACH_CLI_MODEL=opus` (or `sonnet`) picks a
  model; empty uses your account default.
- **Anthropic API** — set `ANTHROPIC_API_KEY` (pay-per-token). When a key is
  set it takes precedence; force a choice with `COACH_BACKEND=cli` or `api`.

## Run

```sh
./venv/bin/uvicorn app.main:app --port 8000
```

Open http://localhost:8000.

## Run as an app (macOS)

The repo lives in `~/Documents`, which macOS gates behind a per-app privacy
prompt — a bare launchd agent gets silently denied, so the server is started
by a tiny **TrainingJournal.app** instead (an app can show the prompt once and
keep the permission):

1. Build it (already done on this machine):
   `osacompile -o /Applications/TrainingJournal.app` with a one-line script
   that calls `scripts/serve` — which starts uvicorn only if it isn't running.
2. Add the app to **Login Items** (hidden) so the server starts at login.
   Postgres already autostarts via `brew services`.
3. In Safari, open http://localhost:8000 → **File → Add to Dock**. That dock
   icon is the "app" you actually click — its window is the web UI.

Day-to-day management: `scripts/app start|stop|restart|status|logs`
(logs land in `~/Library/Logs/TrainingJournal/server.log`). After a
`git pull`, run `scripts/app restart`.

| Page | What it does |
|---|---|
| Dashboard | Weekly + body tiles, Renpho sync/import, training-load and body-trend charts |
| Capture | Live Tindeq session: setup → connect → force chart + timer + spoken cues → save. Previous sessions (with force–time traces) live in a drop-down here |
| Journal | Daily wellness check-in + climbing logging and volume/max-grade trends; workouts and notes too |
| Calendar | Month grid of everything recorded per day, plus planned items and training blocks (editable; the coach can propose changes to today/future only) |
| Trends | MVC/RFD baselines and session peak force per grip × hand |
| Coach | "What should I do today?" + chat, grounded in your recent training data; can propose calendar updates you apply with one click |

## Notes

- **Capture** drives the Tindeq over BLE from the server process (bleak), so run
  the server on the machine with Bluetooth. Cues use the browser's speech
  synthesis. A `simulate: true` flag on `/api/capture/start` generates synthetic
  force data for testing without hardware.
- **Migrations** are plain numbered SQL files in `app/migrations/`, applied by
  `python -m app.migrate` (tracked in `schema_migrations`, additive only).
- **Renpho cloud sync** targets the **Renpho Health** app's backend
  (cloud.renpho.com, reverse-engineered — credit danvaneijck/renpho-api) and
  may break if Renpho changes it — CSV import from the app is the reliable
  fallback. Classic-app (renpho.qnclouds.com) accounts are not supported.
- **Body metrics schema** is source/metric/value/time, so Oura (sleep, HRV,
  readiness) can land in the same table later with a new `source`.
