"""Request context: honour or create X-Request-ID, and write one access log line per request."""

import logging
import re
import time
import uuid

from fastapi import Request
from fastapi.responses import Response

from app.core.logging import log_event, request_id_var

access_log = logging.getLogger("rxd.access")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


async def request_context(request: Request, call_next) -> Response:
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
    token = request_id_var.set(request_id)
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log_event(
            access_log,
            "request_failed",
            level=logging.ERROR,
            method=request.method,
            path=request.url.path,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    log_event(
        access_log,
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return response
