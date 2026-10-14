#!/usr/bin/env bash
# Create an isolated two namespace lab for safe tc and iptables experiments.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash tools/setup_netns_lab.sh" >&2
  exit 2
fi

for namespace in flowlab-a flowlab-b; do
  if ip netns list | awk '{print $1}' | grep -Fxq "${namespace}"; then
    echo "${namespace} already exists; inspect it and run cleanup_netns_lab.sh before retrying" >&2
    exit 1
  fi
done

delay="${FLOWLAB_DELAY:-20ms}"
loss="${FLOWLAB_LOSS:-1%}"
drop_port="${FLOWLAB_DROP_PORT:-443}"
if [[ ! "${drop_port}" =~ ^[0-9]{1,5}$ ]] || (( drop_port < 1 || drop_port > 65535 )); then
  echo "FLOWLAB_DROP_PORT must be an integer from 1 to 65535" >&2
  exit 2
fi

cleanup_partial() {
  ip netns del flowlab-a 2>/dev/null || true
  ip netns del flowlab-b 2>/dev/null || true
}
trap cleanup_partial ERR

ip netns add flowlab-a
ip netns add flowlab-b
ip link add flowlab-a0 type veth peer name flowlab-b0
ip link set flowlab-a0 netns flowlab-a
ip link set flowlab-b0 netns flowlab-b
ip -n flowlab-a address add 10.70.0.1/30 dev flowlab-a0
ip -n flowlab-b address add 10.70.0.2/30 dev flowlab-b0
ip -n flowlab-a link set lo up
ip -n flowlab-b link set lo up
ip -n flowlab-a link set flowlab-a0 up
ip -n flowlab-b link set flowlab-b0 up
ip netns exec flowlab-a tc qdisc add dev flowlab-a0 root netem delay "${delay}" loss "${loss}"

if [[ "${FLOWLAB_DROP:-0}" == "1" ]]; then
  ip netns exec flowlab-a iptables -A OUTPUT -p tcp --dport "${drop_port}" -j DROP
fi

trap - ERR
echo "Created isolated namespaces flowlab-a and flowlab-b."
echo "Impairment: delay=${delay}, loss=${loss}."
echo "Optional firewall drop: FLOWLAB_DROP=1 (destination TCP port ${drop_port})."
echo "Run a test only inside a namespace with: ip netns exec flowlab-a COMMAND"
echo "Remove the lab with: sudo bash tools/cleanup_netns_lab.sh"
