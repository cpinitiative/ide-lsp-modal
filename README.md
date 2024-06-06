# Language Servers on Modal

This repo contains the code necessary to run language servers on [Modal](https://modal.com/), used by the [USACO Guide IDE](https://ide.usaco.guide/).

## Overview

Modal provides serverless function execution, allowing us to scale up or scale down the number of machines running these language servers. This previously was quite challenging to do without Modal -- we had to provision a large VM to handle peak traffic to the USACO Guide IDE, but this VM sat idle most of the time and frequently crashed, requiring a manual restart. Because language servers are typically memory-intensive and not CPU-intensive, and Modal bills per-second per-resource (ie. bills CPU and memory usage separately), running on Modal should be substantially cheaper. Additionally, Modal provides a far superior developer experience compared to managing our own servers.

One drawback of Modal is it will terminate WebSocket connections after one hour (I think, not sure). This probably isn't too bad -- the user can just reload the page, or we can implement an auto-reconnect system on the USACO Guide IDE.

Another concern is Modal does not guarantee where your functions will run. If the function ends up running on a server that's far away from the end user, the latency for the language server may be quite high, which is undesireable. In practice though, it doesn't seem too bad.

## Language Servers

Currently, pyright and clangd-18 are supported.

## Future Plans

- Add Java language server
- Add ability to configure compilation flags
- Add Rust / Kotlin language server?
