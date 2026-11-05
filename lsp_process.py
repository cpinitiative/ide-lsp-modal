import asyncio
import os
import signal
import time
from contextlib import AbstractAsyncContextManager
from fastapi import WebSocket, WebSocketDisconnect
from adapters.base import LanguageServerAdapter


class LSPExited(Exception):
    pass


class LanguageServerProcess(AbstractAsyncContextManager):
    """Async context manager wrapper around a langauge server process.

    Implements a (very basic) JSON-RPC / Microsoft Language Server protocol
    through the process's stdin/stdout.

    See: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/
    """

    _proc: asyncio.subprocess.Process

    def __init__(self, adapter: LanguageServerAdapter):
        self._adapter = adapter

    async def __aenter__(self):
        command = await self._adapter.aenter()
        self._proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if self._proc.returncode is None:
                print("Process hasn't exited yet, killing")
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                returncode = await self._proc.wait()
                print(f"Process killed with exit code {returncode}")
            else:
                print("Process has already exited, not killing")
        finally:
            await self._adapter.aexit()

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
                    print("No activity after 5 minutes, closing connection")
                    await websocket.close(reason="Inactive for 5 minutes, please refresh")
                    break

                if ws_read in done:
                    data = ws_read.result()
                    data = await self._adapter.ws_to_lsp(data)

                    await self.send_msg(data)
                    n_messages_from_ws += 1
                    ws_read = asyncio.create_task(websocket.receive_text())

                if proc_read in done:
                    output = proc_read.result()
                    output = await self._adapter.lsp_to_ws(output)

                    await websocket.send_text(output)
                    n_messages_from_lsp += 1
                    proc_read = asyncio.create_task(self.read_msg())

                if last_log_time + 60 < time.time():
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
