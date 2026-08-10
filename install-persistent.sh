#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly RULE_TARGET="/etc/udev/rules.d/70-wayland-scroll-forwarder.rules"
readonly SERVICE_TARGET="${HOME}/.config/systemd/user/wayland-scroll-forwarder.service"

usage() {
  printf 'Usage: %s "EXACT INPUT DEVICE NAME"\n' "${0##*/}"
  printf 'Example: %s "Naga V2 Pro Mouse"\n' "${0##*/}"
}

if [[ ${EUID} -eq 0 ]]; then
  printf 'Run this installer as the desktop user, not as root.\n' >&2
  exit 1
fi

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

readonly DEVICE_NAME="$1"
if (( ${#DEVICE_NAME} > 127 )) || \
  ! printf '%s\n' "${DEVICE_NAME}" | LC_ALL=C grep -Eq '^[[:alnum:]][[:alnum:] ._:+-]*$'; then
  printf 'Device name contains unsupported characters.\n' >&2
  exit 2
fi

readonly TEMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TEMP_DIR}"' EXIT

# The validation above excludes sed replacement metacharacters except spaces,
# so substituting the exact kernel-reported device name is deterministic.
sed "s/@DEVICE_NAME@/${DEVICE_NAME}/g" \
  "${SCRIPT_DIR}/config/70-wayland-scroll-forwarder.rules.in" \
  > "${TEMP_DIR}/70-wayland-scroll-forwarder.rules"

install -Dm755 \
  "${SCRIPT_DIR}/scroll_forwarder.py" \
  "${HOME}/.local/bin/wayland-scroll-forwarder"
install -Dm644 \
  "${SCRIPT_DIR}/config/wayland-scroll-forwarder.service" \
  "${SERVICE_TARGET}"

printf 'Authentication is required to install the narrowly scoped udev rule.\n'
pkexec install -Dm644 \
  "${TEMP_DIR}/70-wayland-scroll-forwarder.rules" \
  "${RULE_TARGET}"
pkexec udevadm control --reload-rules
pkexec udevadm trigger --subsystem-match=input --action=add

systemctl --user stop wayland-scroll-forwarder.service 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now wayland-scroll-forwarder.service

printf '\nInstalled persistent forwarder for: %s\n' "${DEVICE_NAME}"
printf 'Stable device: /dev/input/wayland-scroll-forwarder-mouse\n'
printf 'Service: wayland-scroll-forwarder.service\n'
