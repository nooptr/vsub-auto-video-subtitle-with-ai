#!/bin/bash
# Vsub.app (bản phát hành) — chạy được trên cả Mac chip M và Mac Intel.
# Lần đầu, hoặc vừa cập nhật: mở Terminal cài Python + thư viện (setup.command). Sau đó mở thẳng app.
APP="$(cd "$(dirname "$0")/../.." && pwd)"
RES="$APP/Contents/Resources"
HOME_DIR="${VSUB_HOME:-$HOME/Library/Application Support/vsub}"
VENV="$HOME_DIR/venv"
VER="$(cat "$RES/app/VERSION" 2>/dev/null)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
export VSUB_APP="$APP"
mkdir -p "$HOME_DIR" "$HOME/Library/Logs"
# để nút "Cập nhật ngay" biết app đang nằm ở đâu
ESC="$(printf '%s' "$APP" | sed 's/\\/\\\\/g; s/"/\\"/g')"
printf '{"kind": "mac-app", "path": "%s", "version": "%s"}\n' "$ESC" "$VER" > "$HOME_DIR/install.json"
if [ ! -x "$VENV/bin/python" ] || [ "$(cat "$VENV/.vsub-version" 2>/dev/null)" != "$VER" ]; then
  open -a Terminal "$RES/setup.command"
  exit 0
fi
exec "$VENV/bin/python" -m vsub.gui "$@" < /dev/null >> "$HOME/Library/Logs/vsub.log" 2>&1
