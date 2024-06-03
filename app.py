from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
import asyncio

from modal import Image, App, asgi_app

web_app = FastAPI()
app = App()  # Note: prior to April 2024, "app" was called "stub"

image = Image.debian_slim().apt_install("curl").run_commands(
    "curl -o node.tar.xz https://nodejs.org/dist/v20.14.0/node-v20.14.0-linux-x64.tar.xz",
    "tar -xf node.tar.xz",
    *[f"ln -s /node-v20.14.0-linux-x64/bin/{binary} /bin/{binary}" for binary in ("node", "npx", "corepack", "npm")],
    "npm install -g pyright"
).pip_install("boto3")


@web_app.websocket("/pyright")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    proc = await asyncio.create_subprocess_shell(
        '/node-v20.14.0-linux-x64/bin/pyright-langserver --stdio',
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )

    for i in range(2):
        output = (await proc.stdout.readline()).decode("ascii")
        assert output.startswith("Content-Length: ")
        content_len = int(output[len("Content-Length: "):])
        await proc.stdout.readexactly(2) # read \r\n
        output = await proc.stdout.readexactly(content_len)

    ws_read = asyncio.create_task(websocket.receive_text())
    proc_read = asyncio.create_task(proc.stdout.readline())
    while True:
        done, pending = await asyncio.wait(
            [ws_read, proc_read],
            return_when=asyncio.FIRST_COMPLETED
        )

        if ws_read in done:
            data = ws_read.result()
            print("writing header", bytes(f"Content-Length: {len(bytes(data, 'ascii'))}\r\n\r\n", "ascii"))
            print("writing data", bytes(data, "ascii"))
            proc.stdin.write(bytes(f"Content-Length: {len(bytes(data, 'ascii'))}\r\n\r\n", "ascii"))
            proc.stdin.write(bytes(data, "ascii"))
            await proc.stdin.drain()
            ws_read = asyncio.create_task(websocket.receive_text())

        if proc_read in done:
            output = proc_read.result().decode("ascii")
            assert output.startswith("Content-Length: ")
            content_len = int(output[len("Content-Length: "):])
            await proc.stdout.readexactly(2) # read \r\n
            output = await proc.stdout.readexactly(content_len)
            await websocket.send_text(output.decode("ascii"))
            proc_read = asyncio.create_task(proc.stdout.readline())


@app.function(image=image)
@asgi_app()
def fastapi_app():
    return web_app