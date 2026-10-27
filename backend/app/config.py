"""Runtime configuration, read from environment variables.

Everything has a sensible local default so `uvicorn app.main:app` just works,
while a hosting provider (Render/Railway/etc.) can override via env vars
without code changes.
"""
import os

ECOURTS_BASE_URL = os.getenv(
    "ECOURTS_BASE_URL", "https://services.ecourts.gov.in/ecourtindia_v6/"
)

# The portal is slow to *respond* (searches can take 20s+) but a healthy one
# accepts a TCP connection in well under a second. So we use a generous read
# timeout and a short connect timeout: if the connection itself hangs (e.g.
# the portal refusing traffic from this server's network), fail in seconds
# rather than leaving the user staring at a spinner for 45s.
ECOURTS_TIMEOUT = float(os.getenv("ECOURTS_TIMEOUT", "45"))
ECOURTS_CONNECT_TIMEOUT = float(os.getenv("ECOURTS_CONNECT_TIMEOUT", "10"))

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
