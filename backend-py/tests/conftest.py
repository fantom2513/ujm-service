from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings


async def _is_db_reachable(database_url: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect():
            return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
def real_database_url() -> str:
    # DB integration tests can only run against a real Postgres — skip
    # gracefully rather than fail when none is reachable (e.g. Docker not
    # running locally), so `uv run pytest` stays green either way.
    settings = get_settings()
    if not asyncio.run(_is_db_reachable(settings.database_url)):
        pytest.skip(f"Postgres not reachable at {settings.database_url!r} — skipping DB integration test")
    return settings.database_url

# Comfortably longer than any client-side deadline used in delay_forever tests
# (they use 50ms), short enough not to slow the suite down noticeably.
_DELAY_FOREVER_SECONDS = 2


class _MockLLMHandler(BaseHTTPRequestHandler):
    response_body: dict = {}
    status_code: int = 200
    delay_forever: bool = False
    reset_connection: bool = False
    call_counter: list[int] | None = None
    stop_event: threading.Event | None = None

    def do_POST(self):  # noqa: N802 (stdlib naming)
        if self.call_counter is not None:
            self.call_counter[0] += 1

        # Drain the request body before responding or closing the connection.
        # On Windows, closing a TCP socket with unread inbound bytes commonly
        # sends an RST, which can make httpx lose an otherwise valid response
        # and report a nondeterministic ReadError.
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length:
            self.rfile.read(content_length)

        if self.reset_connection:
            # Close the socket without writing any response bytes — the
            # client already finished sending its request by this point, so
            # it sees the connection die while waiting for a reply (a broken
            # connection), not a timeout. Distinct failure mode from
            # delay_forever below (server alive but never answers).
            self.connection.close()
            return
        if self.delay_forever:
            # Wait until fixture teardown releases the handler. This still
            # makes the client hit its own timeout, but unlike sleep() it lets
            # teardown stop and join the server thread deterministically.
            assert self.stop_event is not None
            self.stop_event.wait(timeout=_DELAY_FOREVER_SECONDS)
            return
        body = json.dumps(self.response_body).encode("utf-8")
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, *args):  # silence stdlib's default request logging
        pass


@pytest.fixture
def mock_llm_server():
    servers: list[tuple[HTTPServer, threading.Thread, threading.Event]] = []

    def _make(
        response_body: dict,
        status_code: int = 200,
        delay_forever: bool = False,
        reset_connection: bool = False,
        call_counter: list[int] | None = None,
    ) -> str:
        stop_event = threading.Event()
        handler = type(
            "Handler",
            (_MockLLMHandler,),
            {
                "response_body": response_body,
                "status_code": status_code,
                "delay_forever": delay_forever,
                "reset_connection": reset_connection,
                "call_counter": call_counter,
                "stop_event": stop_event,
            },
        )
        server = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01),
            daemon=True,
        )
        thread.start()
        servers.append((server, thread, stop_event))
        port = server.server_address[1]
        return f"http://127.0.0.1:{port}"

    yield _make

    for server, thread, stop_event in servers:
        # Release a timeout handler before shutdown: HTTPServer handles the
        # request on its serve_forever thread, so shutdown cannot complete
        # while that handler is blocked. Then close and join in a strict order
        # so no old server thread or socket leaks into the next test.
        stop_event.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        if thread.is_alive():
            raise RuntimeError("Mock LLM server thread did not stop")


class _MockJiraHandler(BaseHTTPRequestHandler):
    response_body: dict = {}
    status_code: int = 200
    delay_forever: bool = False

    def do_GET(self):  # noqa: N802 (stdlib naming)
        if self.delay_forever:
            # See _MockLLMHandler.do_POST — bounded sleep, not a busy-spin.
            time.sleep(_DELAY_FOREVER_SECONDS)
            return
        body = json.dumps(self.response_body).encode("utf-8")
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence stdlib's default request logging
        pass


@pytest.fixture
def mock_jira_server():
    servers: list[HTTPServer] = []

    def _make(response_body: dict, status_code: int = 200, delay_forever: bool = False) -> str:
        handler = type(
            "Handler",
            (_MockJiraHandler,),
            {"response_body": response_body, "status_code": status_code, "delay_forever": delay_forever},
        )
        server = HTTPServer(("127.0.0.1", 0), handler)
        servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        return f"http://127.0.0.1:{port}"

    yield _make

    for server in servers:
        shutdown_thread = threading.Thread(target=server.shutdown, daemon=True)
        shutdown_thread.start()
        shutdown_thread.join(timeout=1)
        server.server_close()
