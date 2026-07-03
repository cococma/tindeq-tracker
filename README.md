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
| `ANTHROPIC_API_KEY` | The AI coach (Claude API) |
| `RENPHO_EMAIL` / `RENPHO_PASSWORD` | Renpho cloud sync (CSV import works without) |

## Run

```sh
./venv/bin/uvicorn app.main:app --port 8000
```

Open http://localhost:8000.

| Page | What it does |
|---|---|
| Dashboard | Weekly tiles + recent sessions |
| Capture | Live Tindeq session: setup → connect → force chart + timer + spoken cues → save |
| Sessions | Recorded hangboard sessions with force–time traces |
| Journal | Climbing sessions, workouts, notes, daily wellness check-in |
| Climbing | Volume-by-grade and max-grade trends |
| Body | Renpho weight / body-fat / muscle charts, cloud sync + CSV import |
| Trends | MVC/RFD baselines and session peak force per grip × hand |
| Load | Weekly session counts, soreness/fatigue heat-strip, sleep |
| Coach | "What should I do today?" + chat, grounded in your recent training data |

## Notes

- **Capture** drives the Tindeq over BLE from the server process (bleak), so run
  the server on the machine with Bluetooth. Cues use the browser's speech
  synthesis. A `simulate: true` flag on `/api/capture/start` generates synthetic
  force data for testing without hardware.
- **Migrations** are plain numbered SQL files in `app/migrations/`, applied by
  `python -m app.migrate` (tracked in `schema_migrations`, additive only).
- **Renpho cloud sync** uses the reverse-engineered API (same approach as the
  Home Assistant integrations) and may break if Renpho changes it — CSV import
  from the Renpho app is the reliable fallback.
- **Body metrics schema** is source/metric/value/time, so Oura (sleep, HRV,
  readiness) can land in the same table later with a new `source`.
- `tracker.py` / `ui.py` are the legacy terminal capture tools, kept until the
  web Capture page is verified against the real device.
