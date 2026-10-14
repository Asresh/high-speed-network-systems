"""Forward JSON lines from bpftrace into the local diagnosis API."""

import argparse
import json
import subprocess
import sys
from urllib.request import Request, urlopen


def post_event(api: str, event: dict) -> None:
    body = json.dumps({"events": [event]}).encode("utf-8")
    request = Request(api.rstrip("/") + "/v1/events", data=body,
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=2) as response:
        if response.status != 202:
            raise RuntimeError(f"collector returned HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--probe", default="ebpf/tcp_retransmit.bt")
    parser.add_argument("--bpftrace", default="bpftrace")
    args = parser.parse_args()
    try:
        process = subprocess.Popen([args.bpftrace, args.probe], stdout=subprocess.PIPE,
                                   stderr=None, text=True, bufsize=1)
    except OSError as exc:
        print(f"unable to start bpftrace: {exc}", file=sys.stderr)
        return 2
    assert process.stdout is not None
    try:
        for line_number, line in enumerate(process.stdout, 1):
            try:
                post_event(args.api, json.loads(line))
            except (json.JSONDecodeError, ValueError, OSError, RuntimeError) as exc:
                print(f"line {line_number}: {exc}", file=sys.stderr)
                return 1
    except KeyboardInterrupt:
        process.terminate()
    finally:
        process.wait(timeout=5)
    return process.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
