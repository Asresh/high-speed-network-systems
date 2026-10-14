"""Run a self-contained synthetic incident through the API."""

import json
import threading
import time
from urllib.request import Request, urlopen

from .server import ObservatoryServer


def main() -> None:
    server = ObservatoryServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    now = time.monotonic_ns()
    events = [{"event": "tcp_retransmit", "timestamp_ns": now + i,
               "family": 2, "source_ip": "10.0.0.4", "source_port": 41000,
               "destination_ip": "10.0.1.9", "destination_port": 443}
              for i in range(8)]
    try:
        request = Request(base + "/v1/events", data=json.dumps({"events": events}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=2) as response:
            print("ingest:", response.read().decode())
        with urlopen(base + "/v1/flows", timeout=2) as response:
            print("diagnosis:", json.dumps(json.load(response), indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
