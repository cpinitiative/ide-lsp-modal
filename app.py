import asyncio
from contextlib import AbstractAsyncContextManager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from modal import Image, App, asgi_app

web_app = FastAPI()
app = App()

image = (
    Image.debian_slim()
    .apt_install("wget", "unzip")
    .run_commands(
        "wget -nv https://nodejs.org/dist/v20.14.0/node-v20.14.0-linux-x64.tar.xz",
        "tar -xf node-v20.14.0-linux-x64.tar.xz",
        "rm node-v20.14.0-linux-x64.tar.xz",
        *[
            f"ln -s /node-v20.14.0-linux-x64/bin/{binary} /bin/{binary}"
            for binary in ("node", "npm")
        ],
        "npm install -g pyright",
    )
    .run_commands(
        "wget -nv https://github.com/clangd/clangd/releases/download/18.1.3/clangd-linux-18.1.3.zip",
        "unzip -q clangd-linux-18.1.3.zip",
        "rm clangd-linux-18.1.3.zip",
        # Note: clangd requires $(which clangd)/../lib/clang to exist
        "mv clangd_18.1.3/bin/clangd /usr/bin",
        "mv clangd_18.1.3/lib/clang /usr/lib/clang",
    )
)
PYTHON_LANGSERVER = "/node-v20.14.0-linux-x64/bin/pyright-langserver --stdio"
CLANGD_LANGSERVER = "clangd --log=error"


class LanguageServerProcess(AbstractAsyncContextManager):
    """Async context manager wrapper around a langauge server process.

    Implements a (very basic) JSON-RPC / Microsoft Language Server protocol
    through the process's stdin/stdout.

    See: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/
    """

    _proc: asyncio.subprocess.Process

    def __init__(self, command: str):
        self._command = command


    async def __aenter__(self):
        self._proc = await asyncio.create_subprocess_shell(
            self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        return self
    

    async def __aexit__(self, exc_type, exc, tb):
        self._proc.terminate()
        await self._proc.wait()
    

    async def read_msg(self) -> str:
        assert self._proc.stdout is not None

        # Read Content-Length: ...\r\n
        output = (await self._proc.stdout.readline()).decode("ascii")
        assert output.startswith("Content-Length: ")
        content_len = int(output[len("Content-Length: ") :])

        # Read \r\n
        await self._proc.stdout.readexactly(2)

        # Read message
        output = await self._proc.stdout.readexactly(content_len)
        return output.decode("utf-8")
    

    async def send_msg(self, msg: str):
        assert self._proc.stdin is not None

        # Write Header
        data = bytes(msg, "utf-8")
        self._proc.stdin.write(
            bytes(f"Content-Length: {len(data)}\r\n\r\n", "ascii")
        )

        # Write data
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()
    

    async def connect_ws(self, websocket: WebSocket):
        ws_read = asyncio.create_task(websocket.receive_text())
        proc_read = asyncio.create_task(self.read_msg())
        try:
            while True:
                done, _pending = await asyncio.wait(
                    [ws_read, proc_read], return_when=asyncio.FIRST_COMPLETED
                )

                if ws_read in done:
                    data = ws_read.result()
                    await self.send_msg(data)
                    ws_read = asyncio.create_task(websocket.receive_text())

                if proc_read in done:
                    output = proc_read.result()
                    await websocket.send_text(output)
                    proc_read = asyncio.create_task(self.read_msg())
        except WebSocketDisconnect:
            pass


@web_app.websocket("/pyright")
async def pyright_endpoint(websocket: WebSocket):
    await websocket.accept()

    async with LanguageServerProcess(PYTHON_LANGSERVER) as lsp:
        # read first two initialization messages
        for _ in range(2):
            await lsp.read_msg()

        print("Got pyright connection!")
        await lsp.connect_ws(websocket)
        print("Pyright websocket disconnected, stopping language server")


@web_app.websocket("/clangd")
async def clangd_endpoint(websocket: WebSocket):
    await websocket.accept()

    async with LanguageServerProcess(CLANGD_LANGSERVER) as lsp:
        print("Got clangd connection!")
        await lsp.connect_ws(websocket)
        print("Clangd websocket disconnected, stopping language server")


@app.function(
    image=image,
    timeout=60 * 60 * 4,  # Note: I think Modal has an internal limit of 1 hour.
    allow_concurrent_inputs=10,
)
@asgi_app()
def fastapi_app():
    return web_app
