"""Frogless: check whether a crochet pattern works before you pick up your hook."""

from pathlib import Path

from dotenv import load_dotenv

# Machine-specific settings (API key, local paths) live in .env, never in code or config.
# Real environment variables win over .env.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
