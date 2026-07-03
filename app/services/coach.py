"""AI coach — wraps the Claude API for recommendations and chat."""

import anthropic

from app import config

MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000

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
start of the conversation."""


class CoachNotConfigured(Exception):
    pass


def _client():
    if not config.ANTHROPIC_API_KEY:
        raise CoachNotConfigured(
            "ANTHROPIC_API_KEY is not set — add it to .env to enable the AI coach."
        )
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _system():
    # cache_control is a no-op below the model's minimum cacheable prefix,
    # but harmless and correct if the prompt grows.
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def get_recommendation(context_md: str, constraint: str = "") -> str:
    """One-shot 'what should I do today?' — non-streaming."""
    user = f"""Here is my current training context:

{context_md}

What should I do today?"""
    if constraint.strip():
        user += f"\n\nConstraints for today: {constraint.strip()}"

    client = _client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=_system(),
        messages=[{"role": "user", "content": user}],
    )
    return next(b.text for b in response.content if b.type == "text")


def stream_chat(context_md: str, history: list, user_message: str):
    """Yield text chunks for a chat turn. history: [{role, content}, ...]."""
    messages = []
    for i, m in enumerate(history):
        content = m["content"]
        if i == 0 and m["role"] == "user":
            content = f"My training context:\n\n{context_md}\n\n---\n\n{content}"
        messages.append({"role": m["role"], "content": content})

    new_content = user_message
    if not history:
        new_content = f"My training context:\n\n{context_md}\n\n---\n\n{user_message}"
    messages.append({"role": "user", "content": new_content})

    client = _client()
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=_system(),
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def count_context_tokens(context_md: str) -> int:
    client = _client()
    return client.messages.count_tokens(
        model=MODEL,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context_md}],
    ).input_tokens
