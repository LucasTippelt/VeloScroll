"""Subprocess probe for the startup-matrix e2e tier.

Imports veloscroll (which runs the config load/check/apply startup block) with
VELOSCROLL_CONFIG set by the caller, then prints every effective daemon key as JSON:

    VALUES {"NAME_MATCH": "Fallback", ...}

DEVICE_MATCH tuples are serialized as lists for JSON. Exits 1 via the daemon's own
startup block when the config is broken (before any thread or device access)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root
import veloscroll as v  # noqa: E402  (import runs the config load/check/apply startup block)


def _jsonable(key):
    val = getattr(v, key)
    return list(val) if isinstance(val, tuple) else val


print("VALUES " + json.dumps({k: _jsonable(k) for k in v.DAEMON_KEYS}))
