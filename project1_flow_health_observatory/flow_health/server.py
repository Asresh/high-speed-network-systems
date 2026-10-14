"""Dependency-free JSON API for ingesting probe events and reading diagnoses."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .events import RetransmitEvent
from .store import TelemetryStore


class ObservatoryServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: TelemetryStore | None = None) -> None:
        self.store = store or TelemetryStore()
        super().__init__(address, ObservatoryHandler)


class ObservatoryHandler(BaseHTTPRequestHandler):
    server: ObservatoryServer

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/v1/flows":
            self._send(200, {"flows": self.server.store.summaries()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/events":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("request body must be between 1 byte and 1 MB")
            payload: Any = json.loads(self.rfile.read(length))
            records = payload.get("events") if isinstance(payload, dict) else None
            if not isinstance(records, list) or not records or len(records) > 500:
                raise ValueError("body must contain 1 to 500 events in an events array")
            events = [RetransmitEvent.from_mapping(item) for item in records]
            accepted = self.server.store.add_many(events)
            self._send(202, {"accepted": accepted})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run the Flow Health Observatory API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ObservatoryServer((args.host, args.port))
    print(f"Flow Health Observatory listening on http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
