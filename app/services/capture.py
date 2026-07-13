"""Tindeq capture manager — owns the BLE connection for the web app.

One Tindeq, one user: a singleton async state machine that the capture REST
endpoints drive and the capture WebSocket observes.

States: idle → scanning → connecting → recording → saving → done | error
(done/error are restartable; a new start() resets to scanning).

Broadcast messages (JSON dicts pushed to every subscriber queue):
    {type: "state",   state, detail}
    {type: "samples", t: [...], force: [...], peak}       ~10 Hz batches
    {type: "phase",   phase, countdown, rep, set, total_reps, total_sets}
    {type: "cue",     text}                                browser speaks these
    {type: "result",  saved, session_id?, peak, n_samples, message}
"""

import asyncio

from bleak import BleakClient

from app.constants import BASELINE_DEFAULTS, BASELINE_EXERCISES, TIMER_EXERCISES
from app.db import get_db_connection
from app.repos.tindeq import (
    close_session, create_session, insert_measurements_batch, save_baseline,
)
from app.tindeq.analysis import calculate_rfd
from app.tindeq.protocol import (
    CMD_START_WEIGHT_MEAS, CMD_STOP_WEIGHT_MEAS, CMD_TARE_SCALE,
    NOTIFY_CHAR_UUID, WRITE_CHAR_UUID,
    find_progressor, parse_weight_frame,
)

BROADCAST_INTERVAL_S = 0.1


class CaptureBusy(Exception):
    pass


class CaptureManager:
    def __init__(self):
        self.state = "idle"
        self.detail = ""
        self.cfg = None
        self.result = None
        self._subscribers = set()   # of asyncio.Queue
        self._task = None
        self._stop_event = None     # asyncio.Event while a run is active
        self._samples = []          # (force_kg, device_ts_us)
        self._pending = []          # (t_rel_s, force_kg) awaiting broadcast
        self._t0 = None
        self._peak = 0.0
        self._attempt_peaks = []    # per-attempt peaks for baseline tests
        self._attempt_rfds = []     # per-attempt RFD for the RFD test
        self._disconnected = False

    # ── Subscription ─────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    def _broadcast(self, msg: dict):
        for q in list(self._subscribers):
            q.put_nowait(msg)

    def _set_state(self, state: str, detail: str = ""):
        self.state = state
        self.detail = detail
        self._broadcast({"type": "state", "state": state, "detail": detail})

    def _cue(self, text: str):
        self._broadcast({"type": "cue", "text": text})

    def status(self) -> dict:
        return {"state": self.state, "detail": self.detail, "cfg": self.cfg, "result": self.result}

    # ── Control ──────────────────────────────────────────────────────────────

    def start(self, cfg: dict):
        if self.state not in ("idle", "done", "error"):
            raise CaptureBusy(f"capture is {self.state}")
        self.cfg = cfg
        self.result = None
        self._samples = []
        self._pending = []
        self._t0 = None
        self._peak = 0.0
        self._attempt_peaks = []
        self._attempt_rfds = []
        self._disconnected = False
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(cfg))

    def request_stop(self):
        if self._stop_event is not None:
            self._stop_event.set()

    # ── BLE session ──────────────────────────────────────────────────────────

    def _ingest(self, force_kg: float, ts: int):
        if self._t0 is None:
            self._t0 = ts
        self._samples.append((force_kg, ts))
        self._pending.append((round((ts - self._t0) / 1_000_000, 3), round(force_kg, 3)))
        if force_kg > self._peak:
            self._peak = force_kg

    def _on_notify(self, _sender, data: bytearray):
        for force_kg, ts in parse_weight_frame(data):
            self._ingest(force_kg, ts)

    def _on_disconnect(self, _client):
        if self.state == "recording":
            self._disconnected = True
            self._stop_event.set()

    async def _run(self, cfg: dict):
        try:
            if cfg.get("simulate"):
                await self._run_simulated(cfg)
                return
            self._set_state("scanning", "Scanning for Progressor...")
            device = await find_progressor()
            if device is None:
                self._set_state("error", "No Progressor found — power it on and retry.")
                return

            self._set_state("connecting", f"Found {device.name} — connecting...")
            async with BleakClient(device.address, disconnected_callback=self._on_disconnect) as client:
                await client.write_gatt_char(WRITE_CHAR_UUID, CMD_TARE_SCALE, response=False)
                await asyncio.sleep(0.5)

                session_id = None
                if self._should_record(cfg):
                    session_id = await asyncio.to_thread(self._create_session_row, cfg)

                await client.start_notify(NOTIFY_CHAR_UUID, self._on_notify)
                await client.write_gatt_char(WRITE_CHAR_UUID, CMD_START_WEIGHT_MEAS, response=False)
                self._set_state("recording", "Recording")

                tasks = [asyncio.create_task(self._broadcast_loop())]
                tasks += self._protocol_tasks(cfg)

                await self._stop_event.wait()
                for t in tasks:
                    t.cancel()

                if not self._disconnected:
                    try:
                        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_STOP_WEIGHT_MEAS, response=False)
                        await client.stop_notify(NOTIFY_CHAR_UUID)
                    except Exception:
                        pass  # device may have dropped between wait and stop

            self._set_state("saving", "Saving...")
            result = await asyncio.to_thread(self._save, cfg, session_id)
            if self._disconnected:
                result["message"] += "  (device disconnected mid-session)"
            self.result = result
            self._broadcast({"type": "result", **result})
            self._set_state("done", result["message"])
        except Exception as e:
            self._set_state("error", f"{type(e).__name__}: {e}")

    async def _run_simulated(self, cfg: dict):
        """No-hardware source for testing the full pipeline (dev only)."""
        import math
        import random

        session_id = None
        if self._should_record(cfg):
            session_id = await asyncio.to_thread(self._create_session_row, cfg)

        self._set_state("recording", "Recording (SIMULATED)")
        tasks = [asyncio.create_task(self._broadcast_loop())]
        tasks += self._protocol_tasks(cfg)

        async def source():
            ts = 0
            while not self._stop_event.is_set():
                for _ in range(8):  # 80 Hz in 100ms batches
                    ts += 12_500
                    force = max(0.0, 18 * math.sin(ts / 1e6 * 0.7) ** 2 + random.uniform(-0.4, 0.4))
                    self._ingest(round(force, 3), ts)
                await asyncio.sleep(0.1)

        tasks.append(asyncio.create_task(source()))
        await self._stop_event.wait()
        for t in tasks:
            t.cancel()

        self._set_state("saving", "Saving...")
        result = await asyncio.to_thread(self._save, cfg, session_id)
        self.result = result
        self._broadcast({"type": "result", **result})
        self._set_state("done", result["message"])

    def _protocol_tasks(self, cfg):
        if cfg["exercise_type"] in TIMER_EXERCISES:
            return [asyncio.create_task(self._timer_loop(cfg))]
        if cfg["exercise_type"] in BASELINE_EXERCISES:
            return [asyncio.create_task(self._baseline_loop(cfg))]
        return []

    @staticmethod
    def _should_record(cfg) -> bool:
        return (
            not cfg.get("no_record")
            and cfg["exercise_type"] != "force_test"
            and cfg["exercise_type"] not in BASELINE_EXERCISES
        )

    def _create_session_row(self, cfg) -> int:
        conn = get_db_connection()
        try:
            return create_session(conn, cfg)
        finally:
            conn.close()

    def _save(self, cfg, session_id) -> dict:
        n = len(self._samples)
        peak = round(self._peak, 2)
        if cfg.get("no_record") or cfg["exercise_type"] == "force_test":
            return {"saved": False, "peak": peak, "n_samples": n,
                    "message": f"Peak {peak} kg · not saved"}

        conn = get_db_connection()
        try:
            if cfg["exercise_type"] in BASELINE_EXERCISES:
                # Best attempt only — force between attempts (racking the
                # handle, early grabs) must not count toward the baseline.
                best_peak = max(self._attempt_peaks) if self._attempt_peaks else self._peak
                rfd = None
                if cfg["exercise_type"] == "rfd_test":
                    if self._attempt_rfds:
                        rfd = max(self._attempt_rfds)
                    elif n > 1:
                        rfd = calculate_rfd(self._samples)
                save_baseline(conn, cfg, best_peak, rfd_kg_per_s=rfd)
                msg = f"Baseline saved · peak {round(best_peak, 2)} kg"
                if rfd:
                    msg += f" · RFD {rfd:.1f} kg/s"
                if self._attempt_peaks:
                    msg += " · attempts " + " / ".join(f"{p:g}" for p in self._attempt_peaks) + " kg"
                return {"saved": True, "peak": round(best_peak, 2), "n_samples": n, "message": msg}

            if self._samples:
                insert_measurements_batch(conn, session_id, self._samples)
            close_session(conn, session_id)
            return {"saved": True, "session_id": session_id, "peak": peak, "n_samples": n,
                    "message": f"Session saved · {n} samples · peak {peak} kg"}
        finally:
            conn.close()

    # ── Live sample broadcast ────────────────────────────────────────────────

    async def _broadcast_loop(self):
        while True:
            await asyncio.sleep(BROADCAST_INTERVAL_S)
            if self._pending:
                batch, self._pending = self._pending, []
                self._broadcast({
                    "type": "samples",
                    "t": [p[0] for p in batch],
                    "force": [p[1] for p in batch],
                    "peak": round(self._peak, 2),
                })

    # ── Timer engine (repeaters / max hang) ──────────────────────────────────

    def _phase(self, phase, countdown=0, rep=0, set_num=0, total_reps=0, total_sets=0):
        self._broadcast({
            "type": "phase", "phase": phase, "countdown": countdown,
            "rep": rep, "set": set_num, "total_reps": total_reps, "total_sets": total_sets,
        })

    async def _tick(self, seconds, phase, rep, set_num, total_reps, total_sets,
                    announce=(), count_last=3):
        for remaining in range(seconds, 0, -1):
            if self._stop_event.is_set():
                return
            self._phase(phase, remaining, rep, set_num, total_reps, total_sets)
            if remaining in announce:
                self._cue(f"{remaining} seconds")
            elif remaining <= count_last:
                self._cue(str(remaining))
            await asyncio.sleep(1)

    async def _timer_loop(self, cfg):
        on_s     = cfg.get("on_seconds") or 7
        off_s    = cfg.get("off_seconds") or 3
        sets     = cfg.get("target_sets") or 1
        reps     = cfg.get("target_reps") or 1
        set_rest = cfg.get("set_rest_s") or 180

        self._phase("READY", 3, 0, 0, reps, sets)
        self._cue("Starting in")
        await self._tick(3, "READY", 0, 0, reps, sets)

        for set_num in range(1, sets + 1):
            for rep_num in range(1, reps + 1):
                if self._stop_event.is_set():
                    return
                self._cue("Hang")
                await self._tick(on_s, "HANG", rep_num, set_num, reps, sets)
                if rep_num < reps:
                    self._cue("Rest")
                    await self._tick(off_s, "REST", rep_num, set_num, reps, sets)

            if set_num < sets:
                self._cue(f"Set {set_num} complete. Rest.")
                announce = tuple(cp for cp in (60, 30, 10) if cp < set_rest)
                await self._tick(set_rest, "SET REST", 0, set_num, reps, sets, announce=announce)

        self._phase("DONE", 0, reps, sets, reps, sets)
        self._cue("Session complete")
        self._stop_event.set()

    # ── Baseline protocol (MVC / RFD tests) ──────────────────────────────────

    async def _baseline_loop(self, cfg):
        ex = cfg["exercise_type"]
        d = BASELINE_DEFAULTS[ex]
        attempts = cfg.get("target_sets") or d["attempts"]
        pull_s   = cfg.get("on_seconds") or d["pull_s"]
        rest_s   = cfg.get("set_rest_s") or d["rest_s"]
        explosive = ex == "rfd_test"

        self._phase("READY", 3, 0, 0, 0, attempts)
        self._cue("Starting in")
        await self._tick(3, "READY", 0, 0, 0, attempts)

        for attempt in range(1, attempts + 1):
            if self._stop_event.is_set():
                return
            start = len(self._samples)
            self._cue("Pull! Fast and hard" if explosive else "Pull! Build to max")
            # No mid-pull countdown for explosive pulls — the point is to
            # release at peak, not to hold until the timer runs out.
            await self._tick(pull_s, "PULL", 0, attempt, 0, attempts,
                             count_last=0 if explosive else 3)
            if self._stop_event.is_set():
                return
            self._cue("Release")
            window = self._samples[start:]
            peak = round(max((f for f, _ in window), default=0.0), 2)
            self._attempt_peaks.append(peak)
            if explosive and len(window) > 1:
                rfd = calculate_rfd(window)
                self._attempt_rfds.append(rfd)
                self._cue(f"Attempt {attempt}: {rfd:.0f} kilos per second")
            else:
                self._cue(f"Attempt {attempt}: {peak:.1f} kilos")
            if attempt < attempts:
                self._cue("Rest")
                announce = tuple(cp for cp in (60, 30, 10) if cp < rest_s)
                await self._tick(rest_s, "REST", 0, attempt, 0, attempts, announce=announce)

        self._phase("DONE", 0, 0, attempts, 0, attempts)
        self._cue("Test complete")
        self._stop_event.set()


manager = CaptureManager()
