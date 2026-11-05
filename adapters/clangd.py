import tempfile
from .base import LanguageServerAdapter


class ClangdAdapter(LanguageServerAdapter):
    def __init__(self, command: str, compiler_options: str | None = None):
        self._command = command
        self._compiler_options = compiler_options
        self._tmpdir: tempfile.TemporaryDirectory | None = None

    async def aenter(self) -> str:
        if self._compiler_options is None:
            return self._command
        self._tmpdir = tempfile.TemporaryDirectory()
        with open(self._tmpdir.name + "/compile_flags.txt", "w") as f:
            f.write("\n".join(self._compiler_options.split()))
        return self._command + " --compile-commands-dir=" + self._tmpdir.name

    async def aexit(self) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None
