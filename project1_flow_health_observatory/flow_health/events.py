"""Validated event model shared by the HTTP service and Linux probe adapter."""

from dataclasses import dataclass
import ipaddress
from typing import Any, Mapping


@dataclass(frozen=True, order=True)
class FlowKey:
    family: int
    source_ip: str
    source_port: int
    destination_ip: str
    destination_port: int

    def as_string(self) -> str:
        return (f"{self.family}:{self.source_ip}:{self.source_port}->"
                f"{self.destination_ip}:{self.destination_port}")


@dataclass(frozen=True)
class RetransmitEvent:
    timestamp_ns: int
    flow: FlowKey

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RetransmitEvent":
        if value.get("event") != "tcp_retransmit":
            raise ValueError("event must be tcp_retransmit")
        timestamp = value.get("timestamp_ns")
        family = value.get("family")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
            raise ValueError("timestamp_ns must be a positive integer")
        if isinstance(family, bool) or family not in (2, 10):
            raise ValueError("family must be 2 (IPv4) or 10 (IPv6)")
        source_ip = _required_text(value, "source_ip")
        destination_ip = _required_text(value, "destination_ip")
        expected_version = 4 if family == 2 else 6
        for name, address in (("source_ip", source_ip), ("destination_ip", destination_ip)):
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError as exc:
                raise ValueError(f"{name} must be a valid IP address") from exc
            if parsed.version != expected_version:
                raise ValueError(f"{name} does not match the address family")
        source_port = _port(value, "source_port")
        destination_port = _port(value, "destination_port")
        return cls(timestamp, FlowKey(family, source_ip, source_port,
                                      destination_ip, destination_port))


def _required_text(value: Mapping[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip() or len(item) > 64:
        raise ValueError(f"{name} must be a nonempty string of at most 64 characters")
    return item


def _port(value: Mapping[str, Any], name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 65535:
        raise ValueError(f"{name} must be an integer between 0 and 65535")
    return item
