from __future__ import annotations


class CurbsideError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class ValidationError(CurbsideError):
    status = 400
    code = "invalid_request"


class AuthError(CurbsideError):
    status = 401
    code = "unauthorized"


class NotFoundError(CurbsideError):
    status = 404
    code = "not_found"


class ConflictError(CurbsideError):
    status = 409
    code = "version_conflict"


class PayloadTooLargeError(CurbsideError):
    status = 413
    code = "payload_too_large"


class RateLimitError(CurbsideError):
    status = 429
    code = "rate_limited"


class BadGatewayError(CurbsideError):
    status = 502
    code = "bad_gateway"


class UnavailableError(CurbsideError):
    status = 503
    code = "unavailable"
