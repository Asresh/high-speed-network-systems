import unittest

from flow_health.events import RetransmitEvent


VALID = {"event": "tcp_retransmit", "timestamp_ns": 10, "family": 2,
         "source_ip": "10.0.0.1", "source_port": 1234,
         "destination_ip": "10.0.0.2", "destination_port": 443}


class EventTests(unittest.TestCase):
    def test_valid_event(self):
        event = RetransmitEvent.from_mapping(VALID)
        self.assertEqual(event.flow.source_port, 1234)
        self.assertIn("10.0.0.1", event.flow.as_string())

    def test_rejects_unknown_event_type(self):
        with self.assertRaisesRegex(ValueError, "event"):
            RetransmitEvent.from_mapping({**VALID, "event": "unknown"})

    def test_rejects_bad_timestamp_and_port(self):
        for changes in ({"timestamp_ns": True}, {"source_port": 65536}, {"family": 7}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                RetransmitEvent.from_mapping({**VALID, **changes})

    def test_address_must_match_declared_family(self):
        with self.assertRaisesRegex(ValueError, "address family"):
            RetransmitEvent.from_mapping({**VALID, "source_ip": "2001:db8::1"})


if __name__ == "__main__":
    unittest.main()
