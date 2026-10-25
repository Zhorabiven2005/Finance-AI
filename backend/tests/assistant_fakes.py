"""Фейковый сервер Ollama для тестов помощника.

Настоящий HTTP-сервер на 127.0.0.1 со случайным портом: клиент проходит
через реальный сетевой стек (urllib), но настоящий Ollama и модель не нужны.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "qwen3.5:4b-q4_K_M"


@dataclass
class Route:
    status: int = 200
    body: bytes = b"{}"
    delay: float = 0.0
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "application/json"})


def json_route(payload, status: int = 200, delay: float = 0.0) -> Route:
    return Route(status=status, body=json.dumps(payload).encode(), delay=delay)


def healthy_routes(models: list[dict] | None = None) -> dict[str, Route]:
    return {
        "/api/version": json_route({"version": "0.40.8"}),
        "/api/tags": json_route(
            {
                "models": models
                if models is not None
                else [
                    {
                        "name": MODEL,
                        "model": MODEL,
                        "size": 3_300_000_000,
                        "details": {"parameter_size": "4.0B", "quantization_level": "Q4_K_M"},
                    }
                ]
            }
        ),
    }


@dataclass
class FakeOllama:
    url: str
    routes: dict[str, Route]
    requests: list[tuple[str, str, bytes]] = field(default_factory=list)


@contextmanager
def fake_ollama(routes: dict[str, Route]) -> Iterator[FakeOllama]:
    state = FakeOllama(url="", routes=routes)

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            state.requests.append((self.command, self.path, body))
            route = state.routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.end_headers()
                return
            if route.delay:
                time.sleep(route.delay)
            self.send_response(route.status)
            for k, v in route.headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(route.body)))
            self.end_headers()
            try:
                self.wfile.write(route.body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        do_GET = _serve  # noqa: N815
        do_POST = _serve  # noqa: N815

        def log_message(self, *_args) -> None:  # тесты без шума в выводе
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def closed_local_port() -> int:
    """Порт на 127.0.0.1, на котором никто не слушает."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
