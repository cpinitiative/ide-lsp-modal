import asyncio
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


@web_app.websocket("/pyright")
async def pyright_endpoint(websocket: WebSocket):
    await websocket.accept()

    proc = await asyncio.create_subprocess_shell(
        "/node-v20.14.0-linux-x64/bin/pyright-langserver --stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )

    # Read first two initialization messages
    for _ in range(2):
        output = (await proc.stdout.readline()).decode("utf-8")
        assert output.startswith("Content-Length: ")
        content_len = int(output[len("Content-Length: ") :])
        await proc.stdout.readexactly(2)  # read \r\n
        output = await proc.stdout.readexactly(content_len)

    ws_read = asyncio.create_task(websocket.receive_text())
    proc_read = asyncio.create_task(proc.stdout.readline())
    print("Got connection!")
    try:
        while True:
            done, _pending = await asyncio.wait(
                [ws_read, proc_read], return_when=asyncio.FIRST_COMPLETED
            )

            if ws_read in done:
                data = ws_read.result()
                # print(
                #     "writing header",
                #     bytes(f"Content-Length: {len(bytes(data, 'utf-8'))}\r\n\r\n", "utf-8"),
                # )
                # print("writing data", bytes(data, "utf-8"))
                proc.stdin.write(
                    bytes(f"Content-Length: {len(bytes(data, 'utf-8'))}\r\n\r\n", "utf-8")
                )
                proc.stdin.write(bytes(data, "utf-8"))
                await proc.stdin.drain()
                ws_read = asyncio.create_task(websocket.receive_text())

            if proc_read in done:
                output = proc_read.result().decode("utf-8")
                assert output.startswith("Content-Length: ")
                content_len = int(output[len("Content-Length: ") :])
                await proc.stdout.readexactly(2)  # read \r\n
                output = await proc.stdout.readexactly(content_len)
                await websocket.send_text(output.decode("utf-8"))
                proc_read = asyncio.create_task(proc.stdout.readline())
    except WebSocketDisconnect:
        print("Websocket disconnected, stopping language server")
        proc.terminate()


@app.function(
    image=image,
    timeout=60 * 60 * 24,  # Note: I think Modal has an internal limit of 1 hour.
)
@asgi_app()
def fastapi_app():
    return web_app
