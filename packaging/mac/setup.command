#!/bin/bash
# vsub (macOS): cài Python + thư viện lần đầu / sau khi cập nhật, rồi mở app.
# Mac chip M: Whisper chạy GPU (mlx-whisper). Mac Intel: faster-whisper. uv tự chọn đúng bản.
set -e
RES="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$RES/../.." && pwd)"
HOME_DIR="${VSUB_HOME:-$HOME/Library/Application Support/vsub}"
VENV="$HOME_DIR/venv"
VER="$(cat "$RES/app/VERSION")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
trap 'echo; echo "✘ Cài đặt lỗi — xem thông báo ở trên."; [ -t 0 ] && read -r -p "Enter để đóng"' ERR
echo "== vsub $VER: cài đặt lần đầu / cập nhật =="
if ! command -v uv >/dev/null; then
  echo "→ Cài uv (trình cài thư viện Python)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
mkdir -p "$HOME_DIR"
# chép mã nguồn ra ngoài bundle: không ghi gì vào trong Vsub.app (giữ chữ ký của app)
rm -rf "$HOME_DIR/src"
cp -R "$RES/app" "$HOME_DIR/src"
echo "→ Cài Python và thư viện (lần đầu mất vài phút)…"
UV_PROJECT_ENVIRONMENT="$VENV" uv sync --frozen --no-editable --project "$HOME_DIR/src"
echo "$VER" > "$VENV/.vsub-version"
command -v ffmpeg >/dev/null || echo "⚠ Chưa có FFmpeg: mở vsub, vào tab “Thư viện” để cài (hoặc: brew install ffmpeg)"
echo "✔ Xong."
if [ -z "${VSUB_NO_LAUNCH:-}" ]; then
  echo "Đang mở vsub…"
  open -n "$APP"
fi
