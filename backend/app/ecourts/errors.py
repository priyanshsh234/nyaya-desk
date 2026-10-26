"""Typed errors so the API layer can map each failure to a precise HTTP status
and the frontend can react appropriately (e.g. refresh the captcha only when
the captcha was wrong, restart the session only when the session died).
"""


class EcourtsError(Exception):
    """Base class. `code` is a stable machine-readable identifier."""

    code = "portal_error"
    http_status = 502

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


class InvalidInput(EcourtsError):
    # Caught before we spend a captcha on a request the portal would reject.
    code = "invalid_input"
    http_status = 400


class CaptchaError(EcourtsError):
    # securimage consumes the code on every attempt, right or wrong, so after
    # this error the client must fetch a fresh captcha image.
    code = "invalid_captcha"
    http_status = 422


class CaseNotFound(EcourtsError):
    code = "not_found"
    http_status = 404


class SessionExpired(EcourtsError):
    # Our own session id is unknown/expired, or the portal invalidated the
    # app_token chain. Either way the only fix is to start a new session.
    code = "session_expired"
    http_status = 440


class PortalUnavailable(EcourtsError):
    code = "portal_unavailable"
    http_status = 503
