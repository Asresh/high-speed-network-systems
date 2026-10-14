#!/usr/bin/env bash
# Remove only the two dedicated namespaces created by setup_netns_lab.sh.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash tools/cleanup_netns_lab.sh" >&2
  exit 2
fi

ip netns del flowlab-a 2>/dev/null || true
ip netns del flowlab-b 2>/dev/null || true
echo "Removed flowlab-a and flowlab-b if they existed."
