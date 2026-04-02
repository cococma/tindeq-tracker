"""
Tindeq Tracker — Textual Terminal UI
Forest green / amber aesthetic, live force monitoring.
"""

from __future__ import annotations

import asyncio
import struct
from typing import Optional

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static, Button, Input, Rule, Checkbox
from textual.containers import Vertical, Horizontal, Container, VerticalScroll
from textual.reactive import reactive
from textual import work
from textual.message import Message
from rich.text import Text

from bleak import BleakScanner, BleakClient

from tracker import (
    PROGRESSOR_SERVICE_UUID, WRITE_CHAR_UUID, NOTIFY_CHAR_UUID,
    CMD_TARE_SCALE, CMD_START_WEIGHT_MEAS, CMD_STOP_WEIGHT_MEAS,
    RESP_WEIGHT_MEASUREMENT,
    get_db_connection, create_session, close_session,
    insert_measurements_batch, save_baseline, _calculate_rfd,
)


# ── Theme ─────────────────────────────────────────────────────────────────────

THEME = """
Screen {
    background: #1a1208;
    color: #d4b896;
}

/* ── Setup screen ── */

#setup_scroll {
    padding: 0 4;
}

#app_title {
    color: #8aaa3a;
    text-style: bold;
    text-align: center;
    padding: 1 0;
}

.form-row {
    height: 3;
    margin: 0;
}

.form-label {
    width: 20;
    color: #7a6040;
    padding: 1 2 0 0;
    text-align: right;
}

.form-unit {
    width: 6;
    color: #4a3820;
    padding: 1 0 0 1;
}

/* ── Shared ── */

.panel {
    background: #221a0a;
    border: solid #3d5228;
    margin: 1 2;
    padding: 1 2;
}

.title {
    color: #8aaa3a;
    text-style: bold;
}

.muted {
    color: #7a6040;
}

.status {
    color: #c8a84b;
    text-align: center;
    height: 1;
}

Button {
    background: #2a1e0e;
    color: #d4b896;
    border: solid #3d5228;
    margin: 1 0;
    width: 100%;
}

Button:hover {
    background: #3d5228;
    color: #d4c8a0;
}

Button:focus {
    border: solid #8aaa3a;
}

Input {
    background: #1a1208;
    border: solid #3d5228;
    color: #d4b896;
    margin: 0;
}

Input:focus {
    border: solid #8aaa3a;
}

Rule {
    color: #3d5228;
    margin: 1 0;
}
"""


# ── Force bar widget ──────────────────────────────────────────────────────────

class ForceBar(Widget):
    """Renders current force + peak force bars with optional target marker."""

    DEFAULT_CSS = """
    ForceBar {
        height: 7;
        width: 100%;
    }
    """

    force  = reactive(0.0)
    peak   = reactive(0.0)
    target = reactive(0.0)
    MAX_KG = 100.0

    def _bar(self, value: float, width: int, fill: str, empty: str) -> str:
        filled = max(0, min(int((value / self.MAX_KG) * width), width))
        return f"[{fill}]{'█' * filled}[/{fill}][{empty}]{'░' * (width - filled)}[/{empty}]"

    def render(self) -> Text:
        w = max(self.size.width - 8, 10)

        # Target marker line
        target_line = ""
        if self.target > 0:
            pos = int((self.target / self.MAX_KG) * w)
            target_line = " " * pos + "▼"

        lines = [
            f"  [bold #d4b896]{self.force:6.2f} kg[/bold #d4b896]",
        ]
        if self.target > 0:
            lines.append(f"  [#7a6040]{target_line:<{w}}  {self.target:.1f} kg target[/#7a6040]")
        lines.append(f"  {self._bar(self.force, w, '#4a7228', '#2a1e0e')}")
        lines.append("")
        lines.append(f"  [#7a6040]PEAK  {self.peak:6.2f} kg[/#7a6040]")
        lines.append(f"  {self._bar(self.peak, w, '#8aaa3a', '#2a1e0e')}")

        return Text.from_markup("\n".join(lines))


# ── Phase display widget ──────────────────────────────────────────────────────

class PhaseDisplay(Widget):
    """Shows current phase (HANG / REST / SET REST), countdown, rep + set progress."""

    DEFAULT_CSS = """
    PhaseDisplay {
        height: 3;
        width: 100%;
    }
    """

    phase      = reactive("READY")
    countdown  = reactive(0)
    rep        = reactive(0)
    total_reps = reactive(0)
    set_num    = reactive(0)
    total_sets = reactive(0)

    PHASE_COLORS = {
        "READY":    "#7a6040",
        "HANG":     "#8aaa3a",
        "REST":     "#d4b896",
        "SET REST": "#7a6040",
        "DONE":     "#8aaa3a",
    }

    def render(self) -> Text:
        color = self.PHASE_COLORS.get(self.phase, "#c8a84b")
        phase_str  = f"[bold {color}]{self.phase:<10}[/bold {color}]"
        timer_str  = f"[bold #c8a84b]{self.countdown:>3}s[/bold #c8a84b]" if self.countdown > 0 else "     "
        rep_str    = f"[#6b5d2e]REP {self.rep}/{self.total_reps}  SET {self.set_num}/{self.total_sets}[/#6b5d2e]" if self.total_sets > 0 else ""
        return Text.from_markup(f"  {phase_str}  {timer_str}    {rep_str}")


# ── Cycle selector widget ─────────────────────────────────────────────────────

class CycleSelect(Widget):
    """Compact ◀ OPTION ▶ selector — left/right arrows cycle through options."""

    DEFAULT_CSS = """
    CycleSelect {
        height: 3;
        width: 1fr;
        border: solid #3d5228;
        content-align: center middle;
        background: #1a1208;
    }
    CycleSelect:focus {
        border: solid #8aaa3a;
    }
    """

    class Changed(Message):
        def __init__(self, selector: "CycleSelect", value: str) -> None:
            super().__init__()
            self.selector = selector
            self.value    = value

    can_focus = True
    index     = reactive(0)

    def __init__(self, options: list, initial: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._options = options  # [(label, value), ...]
        self._initial = initial

    def on_mount(self) -> None:
        for i, (_, v) in enumerate(self._options):
            if v == self._initial:
                self.index = i
                break

    @property
    def value(self) -> str:
        return self._options[self.index][1]

    def render(self) -> Text:
        label = self._options[self.index][0]
        n     = len(self._options)
        dots  = "  ".join("●" if i == self.index else "·" for i in range(n))
        return Text.from_markup(
            f"[#4a3820]◀[/#4a3820]  [bold #d4b896]{label}[/bold #d4b896]  [#4a3820]▶[/#4a3820]\n"
            f"[#7a6040]{dots}[/#7a6040]"
        )

    def on_click(self, event) -> None:
        # Click left half = go left, right half = go right
        if event.x < self.size.width // 2:
            self.index = (self.index - 1) % len(self._options)
        else:
            self.index = (self.index + 1) % len(self._options)
        self.post_message(self.Changed(self, self.value))

    def on_key(self, event) -> None:
        if event.key == "left":
            self.index = (self.index - 1) % len(self._options)
            self.post_message(self.Changed(self, self.value))
        elif event.key == "right":
            self.index = (self.index + 1) % len(self._options)
            self.post_message(self.Changed(self, self.value))


# ── Setup screen ──────────────────────────────────────────────────────────────

class SetupScreen(Screen):

    EXERCISE_OPTIONS = [
        ("Repeaters",           "repeaters"),
        ("Max Hang",            "max_hang"),
        ("Recruitment Pull",    "recruitment_pull"),
        ("MVC Baseline Test",   "mvc_test"),
        ("RFD Baseline Test",   "rfd_test"),
        ("Force Test",          "force_test"),
    ]

    GRIP_OPTIONS = [
        ("Half Crimp",  "half_crimp"),
        ("Full Crimp",  "full_crimp"),
        ("Open Hand",   "open_hand"),
        ("Pinch",       "pinch"),
    ]

    HAND_OPTIONS = [
        ("Right", "right"),
        ("Left",  "left"),
        ("Both",  "both"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="setup_scroll"):
            yield Static(
                "╔══════════════════════════╗\n"
                "║   TINDEQ FORCE TRACKER   ║\n"
                "╚══════════════════════════╝",
                id="app_title"
            )

            with Horizontal(classes="form-row"):
                yield Static("EXERCISE", classes="form-label")
                yield CycleSelect(self.EXERCISE_OPTIONS, initial="repeaters", id="exercise")

            with Horizontal(classes="form-row"):
                yield Static("GRIP", classes="form-label")
                yield CycleSelect(self.GRIP_OPTIONS, initial="half_crimp", id="grip")

            with Horizontal(classes="form-row"):
                yield Static("HAND", classes="form-label")
                yield CycleSelect(self.HAND_OPTIONS, initial="right", id="hand")

            with Horizontal(classes="form-row"):
                yield Static("EDGE DEPTH", classes="form-label")
                yield Input(value="20", id="edge", type="integer")
                yield Static("mm", classes="form-unit")

            yield Rule(id="rep_rule")

            with Horizontal(classes="form-row", id="row_onoff"):
                yield Static("ON / OFF", classes="form-label")
                yield Input(value="7/3", id="onoff")
                yield Static("sec", classes="form-unit")

            with Horizontal(classes="form-row", id="row_setsreps"):
                yield Static("SETS / REPS", classes="form-label")
                yield Input(value="6/6", id="setsreps")

            with Horizontal(classes="form-row", id="row_setrest"):
                yield Static("SET REST", classes="form-label")
                yield Input(value="180", id="setrest", type="integer")
                yield Static("sec", classes="form-unit")

            with Horizontal(classes="form-row", id="row_target"):
                yield Static("TARGET FORCE", classes="form-label")
                yield Input(value="0", id="target", type="number")
                yield Static("kg", classes="form-unit")

            yield Rule()
            yield Checkbox("Don't record this session", id="no_record")
            yield Button("▶  START SESSION", id="start")

    def on_mount(self) -> None:
        self._update_visibility("repeaters")

    def on_cycle_select_changed(self, event: CycleSelect.Changed) -> None:
        if event.selector.id == "exercise":
            self._update_visibility(event.value)

    def _update_visibility(self, exercise: str) -> None:
        rep_ids    = ["rep_rule", "row_onoff", "row_setsreps", "row_setrest"]
        target_ids = ["row_target"]

        for wid in rep_ids:
            self.query_one(f"#{wid}").display = exercise in ("repeaters", "max_hang")
        for wid in target_ids:
            self.query_one(f"#{wid}").display = exercise == "repeaters"

        if exercise == "max_hang":
            self.query_one("#onoff", Input).value   = "7/53"
            self.query_one("#setsreps", Input).value = "3/3"
        elif exercise == "repeaters":
            self.query_one("#onoff", Input).value   = "7/3"
            self.query_one("#setsreps", Input).value = "6/6"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "start":
            return

        ex   = self.query_one("#exercise", CycleSelect).value
        grip = self.query_one("#grip", CycleSelect).value
        hand = self.query_one("#hand", CycleSelect).value
        edge = int(self.query_one("#edge", Input).value or 20)

        on_s = off_s = sets = reps = set_rest = None
        target_kg = 0.0

        if ex in ("repeaters", "max_hang"):
            try:
                on_s, off_s = [int(x) for x in self.query_one("#onoff", Input).value.split("/")]
            except Exception:
                on_s, off_s = (7, 3) if ex == "repeaters" else (7, 53)
            try:
                sets, reps = [int(x) for x in self.query_one("#setsreps", Input).value.split("/")]
            except Exception:
                sets, reps = 6, 6
            set_rest = int(self.query_one("#setrest", Input).value or 180)

        if ex == "repeaters":
            try:
                target_kg = float(self.query_one("#target", Input).value or 0)
            except ValueError:
                target_kg = 0.0

        next_hand = "left" if hand == "both" else None
        no_record = self.query_one("#no_record", Checkbox).value

        cfg = {
            "exercise_type":     ex,
            "grip_type":         grip,
            "hand":              "right" if hand == "both" else hand,
            "edge_depth_mm":     edge,
            "target_weight_kg":  target_kg,
            "on_seconds":        on_s,
            "off_seconds":       off_s,
            "target_reps":       reps,
            "target_sets":       sets,
            "set_rest_s":        set_rest or 180,
            "target_duration_s": None,
            "target_pull_reps":  None,
            "no_record":         no_record,
            "notes":             None,
        }

        self.app.push_screen(SessionScreen(cfg, next_hand=next_hand))


# ── Session screen ────────────────────────────────────────────────────────────

class SessionScreen(Screen):

    force         = reactive(0.0)
    peak          = reactive(0.0)
    status_msg    = reactive("Scanning for Progressor...")

    def __init__(self, cfg: dict, next_hand: Optional[str] = None) -> None:
        super().__init__()
        self.cfg            = cfg
        self._next_hand     = next_hand
        self._wait_to_start = False
        self.stop_event     = asyncio.Event()
        self._status_widget: Optional[Static] = None
        self._latest      = [0.0, 0]   # [force_kg, device_ts_us]
        self._all_samples: list        = []
        self._force_history: list      = []
        self._measurement_count        = 0
        self._peak                     = 0.0
        self._session_id: Optional[int] = None
        self._conn                     = None

    def compose(self) -> ComposeResult:
        ex   = self.cfg["exercise_type"].replace("_", " ").upper()
        grip = self.cfg["grip_type"].replace("_", " ").title()
        edge = self.cfg["edge_depth_mm"]
        hand = self.cfg.get("hand", "right").title()

        with Vertical(classes="panel"):
            yield Static(
                f"  {ex}  ·  {grip}  ·  {edge}mm  ·  {hand}",
                classes="title", id="header"
            )
            yield Rule()
            yield ForceBar(id="force_bar")
            yield Rule()
            yield PhaseDisplay(id="phase_display")
            yield Rule()
            self._status_widget = Static("", id="status", classes="status")
            yield self._status_widget
            yield Button("■  STOP SESSION", id="stop")

    def on_mount(self) -> None:
        fb = self.query_one("#force_bar", ForceBar)
        fb.target = self.cfg.get("target_weight_kg") or 0.0
        pd = self.query_one("#phase_display", PhaseDisplay)
        pd.total_sets = self.cfg.get("target_sets") or 0
        pd.total_reps = self.cfg.get("target_reps") or 0
        self._set_status("Scanning for Progressor...")
        self.run_session()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop":
            if self._wait_to_start:
                self._wait_to_start = False
                self.query_one("#stop", Button).label = "■  STOP SESSION"
                self.run_session()
            elif not self.stop_event.is_set():
                self.stop_event.set()
                self.query_one("#stop", Button).disabled = True
            elif self._next_hand:
                self._begin_next_hand()
            else:
                self.app.pop_screen()

    def _begin_next_hand(self) -> None:
        """Reset this screen in-place for the next hand."""
        self.cfg = {**self.cfg, "hand": self._next_hand}
        self._next_hand = None
        self.stop_event.clear()
        self._all_samples    = []
        self._force_history  = []
        self._measurement_count = 0
        self._peak           = 0.0
        self._session_id     = None
        self._conn           = None

        hand = self.cfg["hand"].title()
        self.query_one("#header", Static).update(
            f"  {self.cfg['exercise_type'].replace('_', ' ').upper()}"
            f"  ·  {self.cfg['grip_type'].replace('_', ' ').title()}"
            f"  ·  {self.cfg['edge_depth_mm']}mm  ·  {hand}"
        )
        self.query_one("#force_bar", ForceBar).peak = 0.0
        self._set_status(f"Switch to {hand} hand, then press START")
        btn = self.query_one("#stop", Button)
        btn.label    = "▶  START SESSION"
        btn.disabled = False
        self._wait_to_start = True

    @work(exclusive=True)
    async def run_session(self) -> None:
        is_baseline = self.cfg["exercise_type"] in ("mvc_test", "rfd_test")
        no_record   = self.cfg["exercise_type"] == "force_test" or self.cfg.get("no_record", False)
        use_timer   = self.cfg["exercise_type"] in ("repeaters", "max_hang")

        # ── DB setup ──────────────────────────────────────────────────────────
        self._conn = get_db_connection()
        if not is_baseline and not no_record:
            self._session_id = create_session(self._conn, self.cfg)

        # ── Find device ───────────────────────────────────────────────────────
        self._set_status("Scanning for Progressor...")
        devices = await BleakScanner.discover(
            timeout=10.0, service_uuids=[PROGRESSOR_SERVICE_UUID]
        )
        if not devices:
            self._set_status("No Progressor found — power it on and retry.")
            return

        address = devices[0].address
        self._set_status(f"Found {devices[0].name} — connecting...")

        def handle_notification(sender, data: bytearray) -> None:
            if data[0] != RESP_WEIGHT_MEASUREMENT:
                return
            n = (len(data) - 2) // 8
            for i in range(n):
                offset = 2 + i * 8
                force_kg, ts = struct.unpack_from("<fI", data, offset=offset)
                self._latest[0] = force_kg
                self._latest[1] = ts
                self._all_samples.append((force_kg, ts))
                self._force_history.append((force_kg, ts))
                if force_kg > self._peak:
                    self._peak = force_kg
                self._measurement_count += 1

        async with BleakClient(address) as client:
            self._set_status("Connected — taring...")
            await client.write_gatt_char(WRITE_CHAR_UUID, CMD_TARE_SCALE, response=False)
            await asyncio.sleep(0.5)

            await client.start_notify(NOTIFY_CHAR_UUID, handle_notification)
            await client.write_gatt_char(WRITE_CHAR_UUID, CMD_START_WEIGHT_MEAS, response=False)
            self._set_status("Recording  ·  press STOP when done")

            # Run UI refresh + optional timer concurrently
            tasks = [asyncio.create_task(self._ui_refresh_loop())]
            if use_timer:
                tasks.append(asyncio.create_task(self._timer_loop()))

            await self.stop_event.wait()
            for t in tasks:
                t.cancel()

            await client.write_gatt_char(WRITE_CHAR_UUID, CMD_STOP_WEIGHT_MEAS, response=False)
            await client.stop_notify(NOTIFY_CHAR_UUID)

        # ── Save ──────────────────────────────────────────────────────────────
        if no_record:
            msg = f"Force test complete — Peak: {self._peak:.2f} kg  ·  not saved"
        elif is_baseline:
            rfd = None
            if self.cfg["exercise_type"] == "rfd_test" and len(self._force_history) > 1:
                rfd = _calculate_rfd(self._force_history)
            save_baseline(self._conn, self.cfg, self._peak, rfd_kg_per_s=rfd)
            msg = f"MVC saved — Peak: {self._peak:.2f} kg" if self.cfg["exercise_type"] == "mvc_test" \
                else f"RFD saved — Peak: {self._peak:.2f} kg  RFD: {rfd:.1f} kg/s" if rfd \
                else f"RFD saved — Peak: {self._peak:.2f} kg"
        else:
            if self._all_samples:
                insert_measurements_batch(self._conn, self._session_id, self._all_samples)
            close_session(self._conn, self._session_id)
            msg = f"Session saved — {self._measurement_count} samples  ·  Peak: {self._peak:.2f} kg"

        self._conn.close()
        self._set_status(msg)

        # Re-enable stop button as "back" or "next hand" button
        btn = self.query_one("#stop", Button)
        btn.label = f"▶  START {self._next_hand.upper()} HAND" if self._next_hand else "◀  BACK TO SETUP"
        btn.disabled = False

    async def _ui_refresh_loop(self) -> None:
        """Update force bar at ~20Hz from latest BLE data."""
        fb = self.query_one("#force_bar", ForceBar)
        while True:
            fb.force = self._latest[0]
            fb.peak  = self._peak
            await asyncio.sleep(0.05)

    async def _timer_loop(self) -> None:
        """Drive phase announcements and update PhaseDisplay."""
        import subprocess

        def say(text: str) -> None:
            subprocess.Popen(["say", text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        async def tick(seconds: int, label: str) -> None:
            """Sleep `seconds`, updating countdown each second."""
            pd = self.query_one("#phase_display", PhaseDisplay)
            for remaining in range(seconds, 0, -1):
                if self.stop_event.is_set():
                    return
                pd.countdown = remaining
                if remaining <= 3:
                    say(str(remaining))
                await asyncio.sleep(1)
            pd.countdown = 0

        on_s      = self.cfg.get("on_seconds") or 7
        off_s     = self.cfg.get("off_seconds") or 3
        sets      = self.cfg.get("target_sets") or 1
        reps      = self.cfg.get("target_reps") or 1
        set_rest  = self.cfg.get("set_rest_s") or 180
        pd        = self.query_one("#phase_display", PhaseDisplay)

        # Lead-in
        pd.phase = "READY"
        say("Starting in")
        await tick(3, "READY")

        for set_num in range(1, sets + 1):
            pd.set_num = set_num
            for rep_num in range(1, reps + 1):
                if self.stop_event.is_set():
                    return
                pd.rep   = rep_num
                pd.phase = "HANG"
                say("Hang")
                await tick(on_s, "HANG")

                if rep_num < reps:
                    pd.phase = "REST"
                    say("Rest")
                    await tick(off_s, "REST")

            if set_num < sets:
                pd.phase = "SET REST"
                say(f"Set {set_num} complete. Rest.")

                checkpoints = [60, 30, 10]
                elapsed = 0
                for cp in checkpoints:
                    wait = set_rest - elapsed - cp
                    if wait > 0 and not self.stop_event.is_set():
                        pd.countdown = set_rest - elapsed
                        for _ in range(wait):
                            if self.stop_event.is_set():
                                return
                            pd.countdown -= 1
                            await asyncio.sleep(1)
                        say(f"{cp} seconds")
                        elapsed = set_rest - cp

                remaining = set_rest - elapsed
                await tick(remaining, "SET REST")

        pd.phase = "DONE"
        say("Session complete")
        self.stop_event.set()

    def _set_status(self, msg: str) -> None:
        if self._status_widget is not None:
            self._status_widget.update(msg)


# ── App ───────────────────────────────────────────────────────────────────────

class TindeqApp(App):
    CSS   = THEME
    TITLE = "Tindeq Force Tracker"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def on_mount(self) -> None:
        self.push_screen(SetupScreen())


if __name__ == "__main__":
    TindeqApp().run()
