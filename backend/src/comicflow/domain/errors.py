from comicflow.domain.models import JsonObject


class DomainError(Exception):
    """A business rule refusal carrying a stable code and optional caller detail.

    ``detail`` is merged into the API error body so a refusal can name what is
    missing (for example which shots still lack assets) instead of forcing the
    caller to re-derive it.
    """

    def __init__(self, code: str, detail: JsonObject | None = None) -> None:
        self.code = code
        self.detail: JsonObject = detail or {}
        super().__init__(code)
