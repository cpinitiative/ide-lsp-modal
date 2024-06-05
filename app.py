import asyncio
from contextlib import AbstractAsyncContextManager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from modal import Image, App, asgi_app

web_app = FastAPI()
app = App()

image = (
    Image.debian_slim()
    .apt_install("curl")
    .run_commands(
        "curl -o node.tar.xz https://nodejs.org/dist/v20.14.0/node-v20.14.0-linux-x64.tar.xz",
        "tar -xf node.tar.xz",
        *[
            f"ln -s /node-v20.14.0-linux-x64/bin/{binary} /bin/{binary}"
            for binary in ("node", "npm")
        ],
        "npm install -g pyright",
    )
)
PYTHON_LANGSERVER = "/node-v20.14.0-linux-x64/bin/pyright-langserver --stdio"


class LanguageServerProcess(AbstractAsyncContextManager):
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

        output = (await self._proc.stdout.readline()).decode("utf-8")
        assert output.startswith("Content-Length: ")
        content_len = int(output[len("Content-Length: ") :])

        await self._proc.stdout.readexactly(2)  # read \r\n

        output = await self._proc.stdout.readexactly(content_len)
        return output.decode("utf-8")
    
    async def send_msg(self, msg: str):
        assert self._proc.stdin is not None

        data = bytes(msg, "utf-8")
        self._proc.stdin.write(
            bytes(f"Content-Length: {len(data)}\r\n\r\n", "utf-8")
        )
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
        # Read first two initialization messages
        for _ in range(2):
            await lsp.read_msg()

        print("Got connection!")
        await lsp.connect_ws(websocket)
        print("Websocket disconnected, stopping language server")


@app.function(
    image=image,
    timeout=60 * 60 * 4,  # Note: I think Modal has an internal limit of 1 hour.
    allow_concurrent_inputs=10,
)
@asgi_app()
def fastapi_app():
    return web_app
