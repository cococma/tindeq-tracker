"""AI coach — Claude behind two interchangeable backends.

"cli": runs the local Claude Code CLI headless (`claude -p`) on the user's
       claude.ai subscription login — no API key, no per-token billing.
"api": the Anthropic API via the official SDK with ANTHROPIC_API_KEY.

COACH_BACKEND=auto (default) uses the API when a key is set, else the CLI.
"""

import json
import os
import shutil
import subprocess

from app import config

MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000
CLI_TIMEOUT_S = 600

SYSTEM_PROMPT = """You are a climbing and strength training coach embedded in the athlete's \
personal training journal. You see their recent hangboard sessions (Tindeq force data), \
climbing sessions, workouts, daily wellness check-ins, body composition trends, and \
MVC/RFD finger-strength baselines.

Coaching principles:
- Reason explicitly about fatigue and supercompensation: weigh recent training load, \
session RPE, soreness, sleep, and force-output trends against each other.
- Flag overtraining signals plainly: rising fatigue + falling peak force + poor sleep \
means back off, and say so.
- Respect connective-tissue timescales: fingers recover slower than muscles; heavy \
finger loading (max hangs, hard crimping) usually wants 48h+ between sessions.
- Be concrete. Name the protocol, grip, edge depth, sets × reps, intensity relative to \
their own recorded numbers, and rest times — not generic advice.
- When data is missing or thin, say what you'd want logged rather than guessing.
- Keep recommendations to the point: today's call first, one or two sentences of \
reasoning, then the concrete session plan (or rest plan).

The athlete's training context (auto-generated from their database) is provided at the \
start of the conversation.

Calendar proposals:
The athlete keeps a training calendar of planned items and training blocks; the current \
plan appears in the context under "Upcoming plan". When you want to add to or change that \
calendar (e.g. lay out next week, or a multi-week block), end your reply with exactly one \
fenced code block tagged calendar-proposal containing JSON in this shape:

```calendar-proposal
{"summary": "one-line description of the change",
 "items": [
   {"action": "add", "date": "YYYY-MM-DD", "type": "hangboard", "title": "Max hangs 20mm", "details": "5x7s half crimp @ 90% MVC"},
   {"action": "update", "id": 14, "date": "YYYY-MM-DD", "type": "climbing", "title": "...", "details": "..."},
   {"action": "delete", "id": 15}],
 "blocks": [
   {"action": "add", "name": "Strength block", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "focus": "max finger strength"}]}
```

Rules: item "type" must be one of hangboard, climbing, workout, rest, other. Only propose \
changes for today or future dates — past days are the historical record and can never be \
edited. For update/delete, reference item ids from the "Upcoming plan" context. The \
athlete reviews each proposal and applies it with a click — never claim a change has \
already been made. Omit the block entirely when you aren't proposing calendar changes."""


class CoachNotConfigured(Exception):
    pass


# ── Backend selection ─────────────────────────────────────────────────────────

def find_cli():
    """Path to the claude binary, or None."""
    candidates = [
        config.CLAUDE_CLI_PATH,
        shutil.which("claude"),
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.claude/local/claude"),
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def backend():
    """Resolve the active backend: 'api' or 'cli'."""
    choice = config.COACH_BACKEND
    if choice == "api":
        if not config.ANTHROPIC_API_KEY:
            raise CoachNotConfigured("COACH_BACKEND=api but ANTHROPIC_API_KEY is not set.")
        return "api"
    if choice == "cli":
        if not find_cli():
            raise CoachNotConfigured(
                "COACH_BACKEND=cli but the Claude Code CLI was not found — "
                "install it (https://claude.ai/install.sh) or set CLAUDE_CLI_PATH."
            )
        return "cli"
    # auto
    if config.ANTHROPIC_API_KEY:
        return "api"
    if find_cli():
        return "cli"
    raise CoachNotConfigured(
        "No coach backend available — install the Claude Code CLI and sign in "
        "(uses your claude.ai subscription), or set ANTHROPIC_API_KEY in .env."
    )


def active_model_label():
    if backend() == "api":
        return MODEL
    return "claude-code:{}".format(config.COACH_CLI_MODEL or "default")


# ── CLI backend ───────────────────────────────────────────────────────────────

def _cli_cmd(output_format):
    cmd = [
        find_cli(), "-p",
        "--tools", "",              # coach is pure text: no file/shell access
        "--setting-sources", "",    # don't load user/project settings or CLAUDE.md
        "--system-prompt", SYSTEM_PROMPT,
        "--output-format", output_format,
    ]
    if output_format == "stream-json":
        cmd += ["--include-partial-messages", "--verbose"]
    if config.COACH_CLI_MODEL:
        cmd += ["--model", config.COACH_CLI_MODEL]
    return cmd


def _cli_env():
    env = dict(os.environ)
    # Make sure the CLI bills the subscription login, never a stray API key.
    env.pop("ANTHROPIC_API_KEY", None)
    if config.CLAUDE_CODE_OAUTH_TOKEN:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = config.CLAUDE_CODE_OAUTH_TOKEN
    return env


def _cli_run(prompt):
    """One-shot CLI call; returns the response text."""
    proc = subprocess.run(
        _cli_cmd("json"),
        input=prompt,
        capture_output=True, text=True,
        env=_cli_env(),
        timeout=CLI_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "claude CLI failed (exit {}): {}".format(
                proc.returncode, (proc.stderr or proc.stdout).strip()[-500:]
            )
        )
    result = json.loads(proc.stdout)
    if result.get("is_error"):
        raise RuntimeError("claude CLI error: {}".format(result.get("result", "unknown")))
    return result.get("result", "")


def _cli_stream(prompt):
    """Yield text chunks from a streaming CLI call."""
    proc = subprocess.Popen(
        _cli_cmd("stream-json"),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
        env=_cli_env(),
    )
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
        yielded = False
        final_text = None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") == "stream_event":
                event = obj.get("event", {})
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yielded = True
                        yield delta["text"]
            elif obj.get("type") == "result":
                if obj.get("is_error"):
                    raise RuntimeError(
                        "claude CLI error: {}".format(obj.get("result", "unknown"))
                    )
                final_text = obj.get("result")
        proc.wait(timeout=30)
        if proc.returncode != 0:
            stderr = proc.stderr.read()
            raise RuntimeError(
                "claude CLI failed (exit {}): {}".format(proc.returncode, stderr.strip()[-500:])
            )
        # Partial events missing (older CLI / format change): fall back to the
        # complete result so the user still gets an answer.
        if not yielded and final_text:
            yield final_text
    finally:
        if proc.poll() is None:
            proc.kill()


def _cli_chat_prompt(context_md, history, user_message):
    """Flatten context + prior turns into one prompt (the CLI is stateless)."""
    parts = ["My training context:\n\n{}".format(context_md)]
    if history:
        turns = []
        for m in history:
            speaker = "Athlete" if m["role"] == "user" else "Coach (you)"
            turns.append("{}: {}".format(speaker, m["content"]))
        parts.append("Our conversation so far:\n\n" + "\n\n".join(turns))
    parts.append("Athlete: {}\n\nReply as the coach — reply text only, no speaker label.".format(user_message))
    return "\n\n---\n\n".join(parts)


# ── API backend ───────────────────────────────────────────────────────────────

def _client():
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _system():
    # cache_control is a no-op below the model's minimum cacheable prefix,
    # but harmless and correct if the prompt grows.
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


# ── Public interface ──────────────────────────────────────────────────────────

def get_recommendation(context_md, constraint=""):
    """One-shot 'what should I do today?' — non-streaming."""
    user = """Here is my current training context:

{}

What should I do today?""".format(context_md)
    if constraint.strip():
        user += "\n\nConstraints for today: {}".format(constraint.strip())

    if backend() == "cli":
        return _cli_run(user)

    response = _client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=_system(),
        messages=[{"role": "user", "content": user}],
    )
    return next(b.text for b in response.content if b.type == "text")


def stream_chat(context_md, history, user_message):
    """Yield text chunks for a chat turn. history: [{role, content}, ...]."""
    if backend() == "cli":
        for chunk in _cli_stream(_cli_chat_prompt(context_md, history, user_message)):
            yield chunk
        return

    messages = []
    for i, m in enumerate(history):
        content = m["content"]
        if i == 0 and m["role"] == "user":
            content = "My training context:\n\n{}\n\n---\n\n{}".format(context_md, content)
        messages.append({"role": m["role"], "content": content})

    new_content = user_message
    if not history:
        new_content = "My training context:\n\n{}\n\n---\n\n{}".format(context_md, user_message)
    messages.append({"role": "user", "content": new_content})

    with _client().messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=_system(),
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def count_context_tokens(context_md):
    """Exact count needs the API; unavailable on the CLI backend."""
    if not config.ANTHROPIC_API_KEY:
        raise CoachNotConfigured("token counting requires ANTHROPIC_API_KEY")
    return _client().messages.count_tokens(
        model=MODEL,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context_md}],
    ).input_tokens
