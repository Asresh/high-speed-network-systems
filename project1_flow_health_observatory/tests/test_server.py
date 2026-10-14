import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flow_health.server import ObservatoryServer


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.server = ObservatoryServer(("127.0.0.1", 0))
        except PermissionError as exc:
            raise unittest.SkipTest(f"the current environment blocks loopback sockets: {exc}")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.base + path, data=data,
                          headers={"Content-Type": "application/json"}, method=method)
        with urlopen(request, timeout=2) as response:
            return response.status, json.load(response)

    def test_health_and_unknown_route(self):
        status, data = self.request("GET", "/health")
        self.assertEqual((status, data["status"]), (200, "ok"))
        with self.assertRaises(HTTPError) as error:
            self.request("GET", "/missing")
        self.assertEqual(error.exception.code, 404)

    def test_ingest_and_read_diagnosis(self):
        now = time.monotonic_ns()
        record = {"event": "tcp_retransmit", "timestamp_ns": now, "family": 2,
                  "source_ip": "192.0.2.1", "source_port": 40000,
                  "destination_ip": "198.51.100.2", "destination_port": 443}
        status, body = self.request("POST", "/v1/events", {"events": [record] * 5})
        self.assertEqual((status, body["accepted"]), (202, 5))
        status, body = self.request("GET", "/v1/flows")
        self.assertEqual(status, 200)
        self.assertEqual(body["flows"][0]["status"], "degraded")

    def test_invalid_batch_returns_400(self):
        with self.assertRaises(HTTPError) as error:
            self.request("POST", "/v1/events", {"events": [{"event": "bad"}]})
        self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
