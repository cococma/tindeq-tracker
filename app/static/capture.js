/* Capture page — drives the server-side BLE capture manager.
 *
 * Flow: open WebSocket first (so no events are missed), then POST /start.
 * The server broadcasts state / samples / phase / cue / result messages;
 * cues are spoken with the SpeechSynthesis API (replacing macOS `say`).
 */

const $ = (id) => document.getElementById(id);

const TIMER_EXERCISES = ["repeaters", "max_hang"];
const BASELINE_EXERCISES = ["mvc_test", "rfd_test"];
let ws = null;
let chartInit = false;
let handQueue = [];        // for "both": remaining hands after the current one
let lastCfg = null;

// ── Setup form ────────────────────────────────────────────────────────────────

function updateFieldVisibility() {
    const ex = $("exercise").value;
    const isTimer = TIMER_EXERCISES.includes(ex);
    const isBaseline = BASELINE_EXERCISES.includes(ex);
    document.querySelectorAll(".timer-only").forEach(el => el.hidden = !isTimer);
    document.querySelectorAll(".repeaters-only").forEach(el => el.hidden = ex !== "repeaters");
    document.querySelectorAll(".baseline-only").forEach(el => el.hidden = !isBaseline);
    const d = window.EXERCISE_DEFAULTS[ex];
    if (d) {
        $("onoff").value = d.on_off.join("/");
        $("setsreps").value = d.sets_reps.join("/");
    }
    const b = window.BASELINE_DEFAULTS[ex];
    if (b) {
        $("attempts").value = b.attempts;
        $("attemptrest").value = b.rest_s;
    }
}
$("exercise").addEventListener("change", updateFieldVisibility);
updateFieldVisibility();

// /capture?plan=<id> arrives with the planned session's setup. Fill the form
// from it — after updateFieldVisibility(), which resets the protocol fields to
// the exercise's defaults.
function applyPrescription(rx) {
    if (!rx || !rx.exercise_type) return;
    $("exercise").value = rx.exercise_type;
    updateFieldVisibility();
    const set = (id, value) => { if (value !== undefined && value !== null) $(id).value = value; };
    set("grip", rx.grip_type);
    set("hand", rx.hand);
    set("edge", rx.edge_depth_mm);
    set("notes", rx.notes);
    if (TIMER_EXERCISES.includes(rx.exercise_type)) {
        if (rx.on_seconds != null && rx.off_seconds != null) $("onoff").value = `${rx.on_seconds}/${rx.off_seconds}`;
        if (rx.target_sets != null && rx.target_reps != null) $("setsreps").value = `${rx.target_sets}/${rx.target_reps}`;
        set("setrest", rx.set_rest_s);
        set("target", rx.target_weight_kg);
    }
    if (BASELINE_EXERCISES.includes(rx.exercise_type)) {
        // Baselines reuse target_sets/set_rest_s as attempts and rest between.
        set("attempts", rx.target_sets);
        set("attemptrest", rx.set_rest_s);
    }
}
applyPrescription(window.PLAN_PRESCRIPTION);

function parsePair(text, fallback) {
    const parts = text.split("/").map(s => parseInt(s.trim(), 10));
    return (parts.length === 2 && parts.every(Number.isFinite)) ? parts : fallback;
}

function buildConfig(hand) {
    const ex = $("exercise").value;
    const cfg = {
        exercise_type: ex,
        grip_type: $("grip").value,
        hand: hand,
        edge_depth_mm: parseInt($("edge").value, 10) || 20,
        target_weight_kg: 0,
        no_record: $("no_record").checked,
        notes: $("notes").value.trim() || null,
        set_rest_s: 180,
    };
    if (TIMER_EXERCISES.includes(ex)) {
        const d = window.EXERCISE_DEFAULTS[ex];
        const [on, off] = parsePair($("onoff").value, d.on_off);
        const [sets, reps] = parsePair($("setsreps").value, d.sets_reps);
        cfg.on_seconds = on; cfg.off_seconds = off;
        cfg.target_sets = sets; cfg.target_reps = reps;
        cfg.set_rest_s = parseInt($("setrest").value, 10) || 180;
    }
    if (BASELINE_EXERCISES.includes(ex)) {
        const b = window.BASELINE_DEFAULTS[ex];
        cfg.on_seconds = b.pull_s;
        cfg.target_sets = parseInt($("attempts").value, 10) || b.attempts;
        cfg.set_rest_s = parseInt($("attemptrest").value, 10) || b.rest_s;
    }
    if (ex === "repeaters") cfg.target_weight_kg = parseFloat($("target").value) || 0;
    return cfg;
}

// ── Speech cues ───────────────────────────────────────────────────────────────

function speak(text) {
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.15;
    speechSynthesis.speak(u);
}

// ── Live chart ────────────────────────────────────────────────────────────────

function initChart(targetKg) {
    const el = $("live-chart");
    const layout = TJ.layout({
        xaxis: TJ.axis({ title: "seconds" }),
        yaxis: TJ.axis({ title: "kg", rangemode: "tozero" }),
        showlegend: false,
        margin: { l: 55, r: 20, t: 10, b: 45 },
    });
    if (targetKg > 0) {
        layout.shapes = [{
            type: "line", xref: "paper", x0: 0, x1: 1, y0: targetKg, y1: targetKg,
            line: { color: TJ.amber, width: 1, dash: "dot" },
        }];
    }
    Plotly.newPlot(el, [{
        x: [], y: [], mode: "lines", name: "Force",
        type: "scattergl",
        line: { color: TJ.hero, width: 2 },
        hovertemplate: "%{y:.1f} kg · %{x:.1f}s<extra></extra>",
    }], layout, TJ.config);
    chartInit = true;
}

// ── Session control ───────────────────────────────────────────────────────────

async function startSession(cfg) {
    lastCfg = cfg;
    $("setup").hidden = true;
    $("result").hidden = true;
    $("live").hidden = false;
    $("stop").disabled = false;
    $("force-now").firstChild.textContent = "0.0";
    $("force-peak").firstChild.textContent = "0.0";
    $("phase").textContent = "READY";
    $("countdown").textContent = "";
    $("progress").textContent = "";
    $("live-header").textContent =
        `${cfg.exercise_type.replace(/_/g, " ").toUpperCase()} · ${cfg.grip_type.replace(/_/g, " ")}` +
        ` · ${cfg.edge_depth_mm}mm · ${cfg.hand} hand` + (cfg.no_record ? " · NOT RECORDING" : "");
    initChart(cfg.target_weight_kg);

    openSocket();
    const res = await fetch("/api/capture/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        $("live-status").textContent = `Could not start: ${err.detail || res.status}`;
    }
}

function openSocket() {
    if (ws && ws.readyState <= WebSocket.OPEN) return;
    ws = new WebSocket(`ws://${location.host}/api/capture/ws`);
    ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
    ws.onclose = () => { ws = null; };
}

function handleMessage(msg) {
    switch (msg.type) {
        case "state":
            $("live-status").textContent = msg.detail || msg.state;
            if (msg.state === "error") $("stop").disabled = true;
            break;
        case "samples": {
            if (!chartInit) break;
            Plotly.extendTraces($("live-chart"), { x: [msg.t], y: [msg.force] }, [0]);
            const last = msg.force[msg.force.length - 1];
            $("force-now").firstChild.textContent = last.toFixed(1);
            $("force-peak").firstChild.textContent = msg.peak.toFixed(1);
            break;
        }
        case "phase":
            $("phase").textContent = msg.phase;
            $("phase").style.color = ["HANG", "PULL"].includes(msg.phase) ? "#8aaa3a" : "#d4b896";
            $("countdown").textContent = msg.countdown > 0 ? `${msg.countdown}s` : "";
            $("progress").textContent = msg.total_reps
                ? `REP ${msg.rep}/${msg.total_reps} · SET ${msg.set}/${msg.total_sets}`
                : msg.total_sets ? `ATTEMPT ${msg.set}/${msg.total_sets}` : "";
            break;
        case "cue":
            speak(msg.text);
            break;
        case "result":
            showResult(msg);
            break;
    }
}

function showResult(msg) {
    $("live").hidden = true;
    $("result").hidden = false;
    $("result-message").textContent = msg.message;
    const link = $("result-link");
    link.hidden = !msg.session_id;
    if (msg.session_id) link.href = `/sessions/${msg.session_id}`;

    const nextBtn = $("next-hand");
    if (handQueue.length) {
        const next = handQueue[0];
        nextBtn.hidden = false;
        nextBtn.textContent = `▶  START ${next.toUpperCase()} HAND`;
    } else {
        nextBtn.hidden = true;
    }
}

// ── Buttons ───────────────────────────────────────────────────────────────────

$("start").addEventListener("click", () => {
    const hand = $("hand").value;
    handQueue = hand === "both" ? ["left"] : [];
    startSession(buildConfig(hand === "both" ? "right" : hand));
});

$("stop").addEventListener("click", async () => {
    $("stop").disabled = true;
    await fetch("/api/capture/stop", { method: "POST" });
});

$("next-hand").addEventListener("click", () => {
    const next = handQueue.shift();
    speak(`Switch to ${next} hand`);
    startSession({ ...lastCfg, hand: next });
});

$("again").addEventListener("click", () => {
    $("result").hidden = true;
    $("live").hidden = true;
    $("setup").hidden = false;
});
