class VideoError(Exception):
    """Error with a user-facing (Chinese) message."""


class NoSubtitles(VideoError):
    """No downloadable tracks; safe to offer explicit ASR."""


class EmptySubtitles(VideoError):
    """Track downloaded successfully but contained no text."""


class AccountError(Exception):
    """Account/auth failure with a user-facing (Chinese) message and HTTP status."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class TranscriptionError(VideoError):
    def __init__(self, code: str, message: str, retryable: bool = False, status: int = 400):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status = status
