# High Speed Network Systems

Two small, runnable systems projects for understanding how network behavior is observed, diagnosed, and exercised by distributed workloads. Both projects are designed to be read from the top down, run locally, and tested without access to a production network.

## Project map

| Project | Focus | Main implementation |
| --- | --- | --- |
| [Project 1: Flow Health Observatory](project1_flow_health_observatory/README.md) | Linux TCP retransmission telemetry, eBPF tracepoint capture, explainable incident summaries, and a local JSON API | Python 3 standard library and bpftrace |
| Project 2 | Distributed tensor collective communication over TCP | Added in the next project pull request |

## How the projects fit together

```mermaid
flowchart LR
  A[Linux TCP stack] --> B[eBPF tracepoint]
  B --> C[Flow Health API]
  C --> D[Windowed flow diagnosis]
  E[Distributed collective workload] --> A
  D --> F[Evidence and operator checks]
```

Project 1 focuses on visibility and diagnosis. Project 2 will create a reproducible distributed workload that makes communication patterns and transport costs easier to inspect.

## Requirements

- Python 3.9 or newer for Project 1 and its tests.
- Linux with `bpftrace` and permission to attach BPF programs to use live kernel capture.
- A C++17 compiler for Project 2.

The synthetic examples and tests need no third party Python packages. Live kernel tracing is optional and Linux only.

## Quick start

```bash
cd project1_flow_health_observatory
python3 -m flow_health.demo
python3 -m unittest discover -s tests -v
```

The demo runs a local server, submits a synthetic retransmission burst, and prints the returned diagnosis. To run the service independently:

```bash
python3 -m flow_health.server --host 127.0.0.1 --port 8080
```

## Pull requests

Each project is introduced in its own reviewable pull request. The second project is based on the first project's branch so both changes can be reviewed in sequence without conflicts in shared documentation.

## Scope

These are educational prototypes. The telemetry service keeps bounded in-memory state and uses transparent thresholds; it does not claim to replace fleet monitoring, a production incident system, or kernel-native telemetry infrastructure.
