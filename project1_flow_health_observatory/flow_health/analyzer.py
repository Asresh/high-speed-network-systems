"""Explainable, bounded-window diagnosis for TCP retransmission bursts."""

from typing import Iterable, Optional

from .events import RetransmitEvent


class FlowAnalyzer:
    def __init__(self, window_seconds: int = 30, degraded_threshold: int = 5,
                 critical_threshold: int = 20) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if degraded_threshold <= 0 or critical_threshold <= degraded_threshold:
            raise ValueError("thresholds must be positive and critical > degraded")
        self.window_ns = window_seconds * 1_000_000_000
        self.degraded_threshold = degraded_threshold
        self.critical_threshold = critical_threshold

    def summarize(self, events: Iterable[RetransmitEvent],
                  now_ns: Optional[int] = None) -> list[dict]:
        items = list(events)
        if now_ns is None:
            now_ns = max((event.timestamp_ns for event in items), default=0)
        recent = [event for event in items
                  if 0 <= now_ns - event.timestamp_ns < self.window_ns]
        grouped: dict[str, list[RetransmitEvent]] = {}
        for event in recent:
            grouped.setdefault(event.flow.as_string(), []).append(event)

        summaries = []
        for flow_id, flow_events in grouped.items():
            count = len(flow_events)
            if count >= self.critical_threshold:
                status = "critical"
            elif count >= self.degraded_threshold:
                status = "degraded"
            else:
                status = "healthy"
            evidence = []
            if count >= self.degraded_threshold:
                evidence.append({
                    "signal": "tcp_retransmissions",
                    "observed": count,
                    "window_seconds": self.window_ns // 1_000_000_000,
                    "threshold": self.degraded_threshold,
                })
            summaries.append({
                "flow_id": flow_id,
                "status": status,
                "retransmissions": count,
                "first_seen_ns": min(event.timestamp_ns for event in flow_events),
                "last_seen_ns": max(event.timestamp_ns for event in flow_events),
                "evidence": evidence,
                "recommended_checks": _checks(status),
            })
        return sorted(summaries, key=lambda item: (item["status"] == "healthy",
                                                   -item["retransmissions"],
                                                   item["flow_id"]))


def _checks(status: str) -> list[str]:
    if status == "critical":
        return ["Inspect the affected path for loss or congestion.",
                "Compare interface drop counters and queue occupancy.",
                "Check recent route, policy, and host network changes."]
    if status == "degraded":
        return ["Compare retransmissions with interface drops and RTT samples.",
                "Check for a recent path or workload change."]
    return []
