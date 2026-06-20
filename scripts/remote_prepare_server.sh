#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

SUDO_PASSWORD_ESCAPED="$(printf '%q' "${NCP_PASSWORD:-}")"

ssh_base "CODEX_SUDO_PASSWORD=$SUDO_PASSWORD_ESCAPED bash -s" <<'REMOTE'
set -euo pipefail

run_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif sudo -n true >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "$CODEX_SUDO_PASSWORD" | sudo -S "$@"
  fi
}

if ! command -v docker >/dev/null; then
  run_sudo apt-get update
  run_sudo apt-get install -y docker.io docker-compose curl
fi

run_sudo systemctl enable --now docker >/dev/null 2>&1 || true

if ! command -v curl >/dev/null; then
  run_sudo apt-get update
  run_sudo apt-get install -y curl
fi

COMPOSE_VERSION="v2.29.7"
compose_version="$(docker-compose version --short 2>/dev/null || true)"
if [[ "$compose_version" != 2.* ]]; then
  case "$(uname -m)" in
    x86_64) compose_arch="x86_64" ;;
    aarch64|arm64) compose_arch="aarch64" ;;
    *) echo "Unsupported architecture: $(uname -m)"; exit 1 ;;
  esac
  run_sudo curl -fsSL --retry 3 \
    "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-$compose_arch" \
    -o /usr/local/bin/docker-compose
  run_sudo chmod +x /usr/local/bin/docker-compose
fi

if ! docker ps >/dev/null 2>&1; then
  if [ "$(id -u)" -ne 0 ]; then
    run_sudo usermod -aG docker "$USER" || true
  fi
fi

run_sudo mkdir -p /srv/projects
run_sudo chmod 775 /srv/projects

SWAP_SIZE_BYTES=2147483648
CURRENT_SWAP_SIZE=0
if [ -f /swapfile ]; then
  CURRENT_SWAP_SIZE="$(stat -c %s /swapfile)"
fi

if [ "$CURRENT_SWAP_SIZE" -ne "$SWAP_SIZE_BYTES" ]; then
  if swapon --show=NAME --noheadings | grep -qx '/swapfile'; then
    run_sudo swapoff /swapfile
  fi
  run_sudo rm -f /swapfile
  run_sudo fallocate -l 2G /swapfile || run_sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  run_sudo chmod 600 /swapfile
  run_sudo mkswap /swapfile
fi

if ! swapon --show=NAME --noheadings | grep -qx '/swapfile'; then
  run_sudo swapon /swapfile
fi

if ! grep -q '^/swapfile ' /etc/fstab; then
  echo '/swapfile none swap sw 0 0' | run_sudo tee -a /etc/fstab >/dev/null
fi

echo "OK remote_prepare"
REMOTE
