"""Start Snacky: MCP on one port, the web UI on another, one process."""

import asyncio
import contextlib
import logging
import os
import signal
from pathlib import Path

import uvicorn

from snacky import config
from snacky.lookup import Lookup
from snacky.mcp_server import create_mcp, create_mcp_app
from snacky.sources.bls import BlsIndex
from snacky.sources.off import OffClient
from snacky.sources.opengym import OpenGymClient
from snacky.sources.tandoor import TandoorClient
from snacky.store import Store

log = logging.getLogger("snacky")


def _server(app, host: str, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    # Each uvicorn server would install its own signal handlers and the second
    # would replace the first, so main() installs one handler for both.
    server.capture_signals = contextlib.nullcontext  # type: ignore[method-assign]
    return server


async def run() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    mcp_port = int(os.environ.get("SNACKY_MCP_PORT", "8000"))
    web_port = int(os.environ.get("SNACKY_WEB_PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104

    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    store = Store(config.DB_PATH)

    bls = None
    if Path(config.BLS_PATH).is_file():
        bls = BlsIndex(config.BLS_PATH)
    else:
        log.warning("BLS index not found at %s; searches skip BLS", config.BLS_PATH)

    off = OffClient(config.OFF_USER_AGENT)
    tandoor = (
        TandoorClient(config.TANDOOR_URL, config.TANDOOR_TOKEN)
        if config.TANDOOR_URL and config.TANDOOR_TOKEN
        else None
    )
    opengym = (
        OpenGymClient(config.OPENGYM_URL, config.OPENGYM_TOKEN)
        if config.OPENGYM_URL and config.OPENGYM_TOKEN
        else None
    )

    lookup = Lookup(store, bls, off)
    servers = [_server(create_mcp_app(create_mcp(store, lookup, tandoor, opengym)), host, mcp_port)]
    try:
        from snacky.web import create_app

        servers.append(_server(create_app(store, opengym=opengym), host, web_port))
    except NotImplementedError:
        log.warning("The web UI is not implemented yet; serving MCP only")

    def stop() -> None:
        for server in servers:
            server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)

    try:
        tasks = [asyncio.create_task(s.serve()) for s in servers]
        # If one server stops on its own (for example its port is taken), stop the other too.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        stop()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await off.aclose()
        if tandoor:
            await tandoor.aclose()
        if opengym:
            await opengym.aclose()
        if bls:
            bls.close()
        store.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
