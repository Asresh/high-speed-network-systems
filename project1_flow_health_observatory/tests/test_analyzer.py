import unittest

from flow_health.analyzer import FlowAnalyzer
from flow_health.events import RetransmitEvent
from flow_health.store import TelemetryStore


def event(at: int, source_port: int = 41000) -> RetransmitEvent:
    return RetransmitEvent.from_mapping({
        "event": "tcp_retransmit", "timestamp_ns": at, "family": 2,
        "source_ip": "10.0.0.4", "source_port": source_port,
        "destination_ip": "10.0.1.9", "destination_port": 443,
    })


class AnalyzerTests(unittest.TestCase):
    def test_severity_boundaries_and_evidence(self):
        analyzer = FlowAnalyzer(window_seconds=30, degraded_threshold=3, critical_threshold=6)
        for count, expected in ((2, "healthy"), (3, "degraded"), (6, "critical")):
            with self.subTest(count=count):
                result = analyzer.summarize([event(i + 100) for i in range(count)], 200)[0]
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["retransmissions"], count)
                self.assertEqual(bool(result["evidence"]), expected != "healthy")

    def test_old_and_future_events_are_excluded(self):
        analyzer = FlowAnalyzer(window_seconds=10, degraded_threshold=2, critical_threshold=4)
        result = analyzer.summarize([event(1), event(95_000_000_000),
                                     event(101_000_000_000)], now_ns=100_000_000_000)
        self.assertEqual(result[0]["retransmissions"], 1)

    def test_flows_are_grouped_and_sorted_by_severity(self):
        analyzer = FlowAnalyzer(degraded_threshold=2, critical_threshold=4)
        events = [event(100, 41000), event(101, 41000), event(102, 42000)]
        result = analyzer.summarize(events, now_ns=103)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["status"], "degraded")

    def test_invalid_thresholds_are_rejected(self):
        with self.assertRaises(ValueError):
            FlowAnalyzer(degraded_threshold=5, critical_threshold=5)

    def test_store_is_bounded(self):
        store = TelemetryStore(capacity=2)
        store.add_many([event(1), event(2), event(3)])
        self.assertEqual([e.timestamp_ns for e in store.snapshot()], [2, 3])


if __name__ == "__main__":
    unittest.main()
