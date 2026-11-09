class OrderFlowError(Exception):
    """Business-rule error shared by REST views and the WebSocket consumer.

    ``code`` is a stable machine-readable identifier, ``fields`` carries
    per-field validation details and ``status_code`` maps to an HTTP status.
    """

    def __init__(self, message, *, code="invalid", fields=None, status_code=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.fields = fields or {}
        self.status_code = status_code

    def as_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "fields": self.fields,
        }
