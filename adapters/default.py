from .base import LanguageServerAdapter


class DefaultAdapter(LanguageServerAdapter):
    def __init__(self, command: str):
        self._command = command

    async def aenter(self) -> str:
        return self._command
