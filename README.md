# Language Servers on Modal

This repo contains the code necessary to run language servers on [Modal](https://modal.com/), used by the [USACO Guide IDE](https://ide.usaco.guide/).

## Overview

Modal provides serverless function execution, allowing us to scale up or scale down the number of machines running these language servers. This previously was quite challenging to do without Modal -- we had to provision a large VM to handle peak traffic to the USACO Guide IDE, but this VM sat idle most of the time and frequently crashed, requiring a manual restart. Additionally, Modal provides a far superior developer experience compared to managing our own servers.

One concern is that Modal does not guarantee where your functions will run. If the function ends up running on a server that's far away from the end user, the latency for the language server may be quite high, which is undesireable. In practice though, the latency seems to be very good.

Another concern is Modal could preempt the container while a user is connected. This isn't too bad -- the user can just reload the page, or we can implement an auto-reconnect system on the USACO Guide IDE.

## Language Servers

Currently, pyright and clangd-18 are supported. clangd-18 also supports compiler flags.

### Future Plans

- Add Java language server
- Add Rust / Kotlin language server?

## Setup

```bash
pip install -r requirements.txt
```

This pins the Modal client. Modal records the client version on each deploy and retires old ones, so deploy from an environment with these requirements installed.


## Development

```bash
modal serve lsp_server.py
```

## Deployment

```bash
MODAL_IMAGE_BUILDER_VERSION=2025.06 modal deploy lsp_server.py
```

The `thecodingwizard` workspace still defaults to Modal's 2023.12 image builder, whose Debian 11 base can no longer install apt packages. Setting `MODAL_IMAGE_BUILDER_VERSION=2025.06` builds this app on Debian 12 instead. It can be dropped once the workspace's image builder is updated in the Modal dashboard.
