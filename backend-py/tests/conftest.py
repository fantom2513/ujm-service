from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

# Comfortably longer than any client-side timeout_ms used in delay_forever
# tests (they use 50ms), short enough not to slow the suite down noticeably.
_DELAY_FOREVER_SECONDS = 2


class _MockLLMHandler(BaseHTTPRequestHandler):
    response_body: dict = {}
    status_code: int = 200
    delay_forever: bool = False
    reset_connection: bool = False
    call_counter: list[int] | None = None

    def do_POST(self):  # noqa: N802 (stdlib naming)
        if self.call_counter is not None:
            self.call_counter[0] += 1
        if self.reset_connection:
            # Close the socket without writing any response bytes — the
            # client already finished sending its request by this point, so
            # it sees the connection die while waiting for a reply (a broken
            # connection), not a timeout. Distinct failure mode from
            # delay_forever below (server alive but never answers).
            self.connection.close()
            return
        if self.delay_forever:
            # Bounded sleep, not `while True: pass` — a busy-spin pegs a CPU
            # core at 100% for the rest of the test session (shutdown() can't
            # interrupt a handler stuck inside a request), which starves
            # other tests and causes spurious timeouts elsewhere. The client
            # has already given up by the time this returns, so there's
            # nothing to send back.
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
def mock_llm_server():
    servers: list[HTTPServer] = []

    def _make(
        response_body: dict,
        status_code: int = 200,
        delay_forever: bool = False,
        reset_connection: bool = False,
        call_counter: list[int] | None = None,
    ) -> str:
        handler = type(
            "Handler",
            (_MockLLMHandler,),
            {
                "response_body": response_body,
                "status_code": status_code,
                "delay_forever": delay_forever,
                "reset_connection": reset_connection,
                "call_counter": call_counter,
            },
        )
        server = HTTPServer(("127.0.0.1", 0), handler)
        servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        return f"http://127.0.0.1:{port}"

    yield _make

    for server in servers:
        # server.shutdown() blocks until serve_forever() notices the flag and
        # exits its loop. HTTPServer handles one request at a time on that
        # same thread, so a handler mid-sleep (delay_forever=True, used to
        # exercise client-side timeouts) can't return control to the loop
        # until its sleep finishes — a direct call here would block teardown
        # for up to that long. Run it on a bounded side thread instead and
        # close the socket regardless.
        shutdown_thread = threading.Thread(target=server.shutdown, daemon=True)
        shutdown_thread.start()
        shutdown_thread.join(timeout=1)
        server.server_close()


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
