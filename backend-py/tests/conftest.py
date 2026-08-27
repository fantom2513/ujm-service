from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _MockLLMHandler(BaseHTTPRequestHandler):
    response_body: dict = {}
    status_code: int = 200
    delay_forever: bool = False

    def do_POST(self):  # noqa: N802 (stdlib naming)
        if self.delay_forever:
            # Never respond — used to exercise client-side timeout handling.
            while True:
                pass
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

    def _make(response_body: dict, status_code: int = 200, delay_forever: bool = False) -> str:
        handler = type(
            "Handler",
            (_MockLLMHandler,),
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
        # server.shutdown() blocks until serve_forever() notices the flag and
        # exits its loop. A handler stuck in a busy loop (delay_forever=True,
        # used to exercise client-side timeouts) never returns control to that
        # loop, so a direct call here would hang teardown forever. Run it on a
        # bounded side thread instead and close the socket regardless.
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
            # Never respond — used to exercise client-side timeout handling.
            while True:
                pass
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
