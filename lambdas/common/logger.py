"""The `curbside` logger. Fields passed via `extra=` become JSON keys under Lambda's
JSON log format. Never pass request bodies, headers or exception messages."""

from __future__ import annotations

import logging
import os

log = logging.getLogger("curbside")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
