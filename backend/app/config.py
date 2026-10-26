"""Runtime configuration, read from environment variables.

Everything has a sensible local default so `uvicorn app.main:app` just works,
while a hosting provider (Render/Railway/etc.) can override via env vars
without code changes.
"""
import os

ECOURTS_BASE_URL = os.getenv(
    "ECOURTS_BASE_URL", "https://services.ecourts.gov.in/ecourtindia_v6/"
)

# The portal is slow and occasionally hangs; a hard timeout keeps a stuck
# upstream call from tying up a worker thread forever.
ECOURTS_TIMEOUT = float(os.getenv("ECOURTS_TIMEOUT", "45"))

# A portal session (cookie + rotating app_token) is only useful for a few
# minutes. We drop idle sessions after this many seconds to bound memory.
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "900"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "500"))

# When set, the raw HTML the portal returns is saved here. Invaluable when the
# portal changes its markup and the parser needs re-tuning.
DEBUG_DUMP_DIR = os.getenv("ECOURTS_DEBUG_DUMP_DIR", "")

# Comma-separated list of allowed frontend origins for CORS. "*" is fine for
# a public demo; lock it down to the deployed frontend URL in production.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
