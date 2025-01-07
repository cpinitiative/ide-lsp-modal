import asyncio
from contextlib import AbstractAsyncContextManager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import time
import signal
import os
import tempfile

from modal import Image, App, asgi_app

web_app = FastAPI()
app = App("lsp-server")

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
        # Note: clangd requires $(dirname $(which clangd))/../lib/clang to exist
        "mv clangd_18.1.3/bin/clangd /usr/bin",
        "mv clangd_18.1.3/lib/clang /usr/lib/clang",
    )
)

PYTHON_LANGSERVER = "/node-v20.14.0-linux-x64/bin/pyright-langserver --stdio"
CLANGD_LANGSERVER = "clangd --log=error --background-index=false --malloc-trim"


class LSPExited(Exception):
    pass


class LanguageServerProcess(AbstractAsyncContextManager):
    """Async context manager wrapper around a langauge server process.

    Implements a (very basic) JSON-RPC / Microsoft Language Server protocol
    through the process's stdin/stdout.

    See: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/
    """

    _proc: asyncio.subprocess.Process
    _tmpdir: tempfile.TemporaryDirectory | None

    def __init__(self, command: str, compiler_options: str | None = None):
        self._command = command
        self._compiler_options = compiler_options
        self._tmpdir = None

    async def __aenter__(self):
        if self._compiler_options is not None:
            self._tmpdir = tempfile.TemporaryDirectory()
            assert self._command == CLANGD_LANGSERVER, "Only clangd language server supports compile flags right now!"
            with open(self._tmpdir.name + "/compile_flags.txt", "w") as f:
                f.write("\n".join(self._compiler_options.split()))
            self._command = self._command + " --compile-commands-dir=" + self._tmpdir.name

        self._proc = await asyncio.create_subprocess_shell(
            self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            preexec_fn=os.setsid,  # We want to set a session ID to kill child processes too
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._tmpdir is not None:
            self._tmpdir.cleanup()

        if self._proc.returncode is None:
            print("Process hasn't exited yet, killing")
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                # The process probably died between the "if" statement and os.getpgid
                pass
            returncode = await self._proc.wait()
            print(f"Process killed with exit code {returncode}")
        else:
            print("Process has already exited, not killing")

    async def read_msg(self) -> str:
        assert self._proc.stdout is not None

        # Read Content-Length: ...\r\n
        output = await self._proc.stdout.readline()
        if output == b"":
            raise LSPExited()
        output = output.decode("ascii")
        if not output.startswith("Content-Length: "):
            raise Exception(
                f"Error: Expected output to start with `Content-Length: `, but got `{output.encode('ascii')}`"
            )
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
        self._proc.stdin.write(bytes(f"Content-Length: {len(data)}\r\n\r\n", "ascii"))

        # Write data
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()

    async def connect_ws(self, websocket: WebSocket):
        ws_read = asyncio.create_task(websocket.receive_text())
        proc_read = asyncio.create_task(self.read_msg())

        last_log_time = time.time()
        n_messages_from_ws = 0
        n_messages_from_lsp = 0

        try:
            while True:
                done, _pending = await asyncio.wait(
                    [ws_read, proc_read],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=5 * 60,
                )

                if len(done) == 0:
                    # no activity for 5 minutes -- timeout
                    print("No activity after 5 minutes, closing connection")
                    await websocket.close(
                        reason="Inactive for 5 minutes, please refresh"
                    )
                    break

                if ws_read in done:
                    data = ws_read.result()
                    await self.send_msg(data)
                    n_messages_from_ws += 1
                    ws_read = asyncio.create_task(websocket.receive_text())

                if proc_read in done:
                    output = proc_read.result()
                    await websocket.send_text(output)
                    n_messages_from_lsp += 1
                    proc_read = asyncio.create_task(self.read_msg())

                if last_log_time + 60 < time.time():
                    # Every 60 seconds, log how many messages were sent
                    print(
                        f"In the last minute, {n_messages_from_lsp} messages were sent from the LSP and {n_messages_from_ws} messages were received from the websocket."
                    )
                    n_messages_from_lsp = 0
                    n_messages_from_ws = 0
                    last_log_time = time.time()
        except WebSocketDisconnect:
            pass
        except LSPExited:
            pass
        except KeyboardInterrupt:
            # preempted -- just disconnect the user
            print("Server preempted -- closing connection")
            await websocket.close(reason="Server closed, please refresh")
        finally:
            ws_read.cancel()
            proc_read.cancel()


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
async def clangd_endpoint(websocket: WebSocket, compiler_options: str | None = None):
    await websocket.accept()

    async with LanguageServerProcess(CLANGD_LANGSERVER, compiler_options=compiler_options) as lsp:
        print(f"Got clangd connection with options `{compiler_options}`")
        await lsp.connect_ws(websocket)
        print("Clangd websocket disconnected, stopping language server")


@app.function(
    image=image,
    timeout=60 * 60 * 4,
    allow_concurrent_inputs=20,
)
@asgi_app()
def main():
    return web_app
