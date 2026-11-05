class LanguageServerAdapter:
    async def aenter(self) -> str:
        raise NotImplementedError

    async def aexit(self) -> None:
        return None

    async def ws_to_lsp(self, data: str) -> str:
        return data

    async def lsp_to_ws(self, data: str) -> str:
        return data
