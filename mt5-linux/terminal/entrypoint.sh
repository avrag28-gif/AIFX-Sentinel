#!/usr/bin/env bash
set -euo pipefail
export WINEPREFIX="${WINEPREFIX:-/home/trader/.wine}"
export DISPLAY="${DISPLAY:-:99}"
mkdir -p /opt/mt5
Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp &
XVFB_PID=$!
cleanup() { kill "$XVFB_PID" 2>/dev/null || true; }
trap cleanup EXIT

wineboot --init
if [ ! -f /opt/mt5/terminal64.exe ]; then
  if [ -z "${MT5_INSTALLER_URL:-}" ]; then
    echo "MT5 not installed. Set MT5_INSTALLER_URL or mount a prepared MT5 installation into /opt/mt5." >&2
    exit 2
  fi
  wget -O /tmp/mt5setup.exe "$MT5_INSTALLER_URL"
  wine /tmp/mt5setup.exe /auto
  echo "Installer completed. Ensure terminal64.exe is available at /opt/mt5/terminal64.exe."
fi
if [ ! -f /opt/mt5/terminal64.exe ]; then
  echo "terminal64.exe not found at /opt/mt5/terminal64.exe" >&2
  exit 3
fi
if [ -z "${MT5_LOGIN:-}" ] || [ -z "${MT5_PASSWORD:-}" ] || [ -z "${MT5_SERVER:-}" ]; then
  echo "MT5_LOGIN, MT5_PASSWORD and MT5_SERVER must be set in the private .env file." >&2
  exit 4
fi
cat > /tmp/terminal.ini <<EOF
[Common]
Login=${MT5_LOGIN}
Password=${MT5_PASSWORD}
Server=${MT5_SERVER}
KeepPrivate=1
NewsEnable=0
[Experts]
Enabled=1
AllowLiveTrading=0
EOF
exec wine /opt/mt5/terminal64.exe ${MT5_TERMINAL_ARGS:-/portable} /config:/tmp/terminal.ini
