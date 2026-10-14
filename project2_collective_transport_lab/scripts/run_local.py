"""Launch a small ring cluster on loopback and print each rank's result."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ring_allreduce.cpp"


def compile_binary(destination: Path) -> None:
    compiler = shlex.split(os.environ.get("CXX", "c++"))
    if not compiler or shutil.which(compiler[0]) is None:
        raise RuntimeError("a C++17 compiler is required; set CXX to its executable")
    command = compiler + ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic",
                          "-Werror", "-pthread", str(SOURCE), "-o", str(destination)]
    subprocess.run(command, cwd=ROOT, check=True)


def allocate_port_block(world_size: int) -> int:
    """Find a currently free consecutive loopback port block for the ranks."""
    for _ in range(50):
        first = socket.socket()
        try:
            first.bind(("127.0.0.1", 0))
            base = first.getsockname()[1]
        finally:
            first.close()
        if base < 1024 or base + world_size - 1 > 65535:
            continue
        reservations = []
        try:
            for port in range(base, base + world_size):
                sock = socket.socket()
                sock.bind(("127.0.0.1", port))
                reservations.append(sock)
        except OSError:
            for sock in reservations:
                sock.close()
            continue
        for sock in reservations:
            sock.close()
        return base
    raise RuntimeError("could not find a free consecutive port block")


def launch(binary: Path, world_size: int, elements: int, base_port: int | None = None,
           timeout: float = 25.0) -> tuple[list[dict], float]:
    if base_port is None:
        base_port = allocate_port_block(world_size)
    processes = []
    start = time.perf_counter()
    try:
        for rank in range(world_size):
            processes.append(subprocess.Popen(
                [str(binary), "--rank", str(rank), "--world-size", str(world_size),
                 "--base-port", str(base_port), "--elements", str(elements)],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=timeout)
            if process.returncode != 0:
                raise RuntimeError(f"rank exited {process.returncode}: {stderr.strip()}")
            outputs.append(json.loads(stdout))
        return outputs, time.perf_counter() - start
    except Exception:
        for process in processes:
            if process.poll() is None:
                process.kill()
        for process in processes:
            if process.poll() is None:
                process.wait()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-size", type=int, default=3)
    parser.add_argument("--elements", type=int, default=11)
    parser.add_argument("--base-port", type=int)
    args = parser.parse_args()
    if not 1 <= args.world_size <= 64:
        parser.error("--world-size must be between 1 and 64")
    if not 1 <= args.elements <= 1_000_000:
        parser.error("--elements must be between 1 and 1000000")
    binary = ROOT / "build" / "ring_allreduce"
    binary.parent.mkdir(parents=True, exist_ok=True)
    compile_binary(binary)
    results, elapsed = launch(binary, args.world_size, args.elements, args.base_port)
    print(json.dumps({"wall_seconds": round(elapsed, 6), "ranks": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
