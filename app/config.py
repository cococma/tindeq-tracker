"""Application settings loaded from .env / environment."""

import os

from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", 5432))
DB_NAME     = os.getenv("DB_NAME", "tindeq")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# ── AI coach ──────────────────────────────────────────────────────────────────
# Backend: "cli" runs the local Claude Code CLI on your claude.ai subscription
# (no API key, no per-token billing); "api" uses the Anthropic API with
# ANTHROPIC_API_KEY. "auto" picks api if a key is set, else cli.
COACH_BACKEND = os.getenv("COACH_BACKEND", "auto").strip().lower()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# CLI backend options. The CLI normally reads your login from the macOS
# Keychain; CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) overrides that
# so the server never depends on Keychain state. COACH_CLI_MODEL is an alias
# like "opus"/"sonnet" — empty means your account's default model.
CLAUDE_CLI_PATH         = os.getenv("CLAUDE_CLI_PATH", "")
CLAUDE_CODE_OAUTH_TOKEN = os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
COACH_CLI_MODEL         = os.getenv("COACH_CLI_MODEL", "")

# ── Renpho sync ───────────────────────────────────────────────────────────────
RENPHO_EMAIL    = os.getenv("RENPHO_EMAIL")
RENPHO_PASSWORD = os.getenv("RENPHO_PASSWORD")
