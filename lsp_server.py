from fastapi import FastAPI, WebSocket
import modal
from modal import Image, App, asgi_app
from adapters.clangd import ClangdAdapter
from adapters.default import DefaultAdapter
from adapters.jdtls import JdtlsAdapter
from lsp_process import LanguageServerProcess

web_app = FastAPI()
app = App("lsp-server")

image = (
    Image.debian_slim()
    .apt_install("wget", "unzip", "tar")
    .pip_install("fastapi[standard]")
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
    .run_commands(
        "mkdir -p /opt/java",
        "wget -nv https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.10%2B7/OpenJDK21U-jdk_x64_linux_hotspot_21.0.10_7.tar.gz -O /tmp/jdk21.tar.gz",
        "tar -xzf /tmp/jdk21.tar.gz -C /opt/java",
        "rm /tmp/jdk21.tar.gz",
        "ln -sf /opt/java/jdk-21*/bin/java /usr/local/bin/java",
        "ln -sf /opt/java/jdk-21*/bin/javac /usr/local/bin/javac",
        "mkdir -p /opt/jdtls",
        "wget -nv https://download.eclipse.org/jdtls/snapshots/jdt-language-server-latest.tar.gz -O /tmp/jdtls.tar.gz",
        "tar -xzf /tmp/jdtls.tar.gz -C /opt/jdtls",
        "rm /tmp/jdtls.tar.gz",
    )
    .add_local_dir("adapters", remote_path="/root/adapters")
    .add_local_file("lsp_process.py", remote_path="/root/lsp_process.py")
    .add_local_file("jdtls_templates.py", remote_path="/root/jdtls_templates.py")
)

PYTHON_LANGSERVER = "/node-v20.14.0-linux-x64/bin/pyright-langserver --stdio"
CLANGD_LANGSERVER = "clangd --log=error --background-index=false --malloc-trim"
JDTLS_BASE = (
    "java "
    "-Declipse.application=org.eclipse.jdt.ls.core.id1 "
    "-Declipse.product=org.eclipse.jdt.ls.core.product "
    "-jar /opt/jdtls/plugins/org.eclipse.equinox.launcher_*.jar "
    "-configuration /opt/jdtls/config_linux"
)


@web_app.websocket("/pyright")
async def pyright_endpoint(websocket: WebSocket):
    await websocket.accept()

    async with LanguageServerProcess(DefaultAdapter(PYTHON_LANGSERVER)) as lsp:
        # read first two initialization messages
        for _ in range(2):
            await lsp.read_msg()

        print("Got pyright connection!")
        await lsp.connect_ws(websocket)
        print("Pyright websocket disconnected, stopping language server")


@web_app.websocket("/clangd")
async def clangd_endpoint(websocket: WebSocket, compiler_options: str | None = None):
    await websocket.accept()

    async with LanguageServerProcess(
        ClangdAdapter(CLANGD_LANGSERVER, compiler_options=compiler_options)
    ) as lsp:
        print(f"Got clangd connection with options `{compiler_options}`")
        await lsp.connect_ws(websocket)
        print("Clangd websocket disconnected, stopping language server")


@web_app.websocket("/jdtls")
async def jdtls_endpoint(websocket: WebSocket):
    await websocket.accept()
    async with LanguageServerProcess(JdtlsAdapter(JDTLS_BASE)) as lsp:
        print("Got jdtls connection!")
        await lsp.connect_ws(websocket)
        print("JDTLS websocket disconnected, stopping language server")


@app.function(
    image=image,
    timeout=60*60*4
)
@modal.concurrent(max_inputs=20)
@asgi_app()
def main():
    return web_app
