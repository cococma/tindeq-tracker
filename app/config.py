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
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── Renpho sync ───────────────────────────────────────────────────────────────
RENPHO_EMAIL    = os.getenv("RENPHO_EMAIL")
RENPHO_PASSWORD = os.getenv("RENPHO_PASSWORD")
