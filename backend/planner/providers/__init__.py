class ProviderError(Exception):
    """An external service (routing/geocoding/weather) failed or returned unusable data."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status
