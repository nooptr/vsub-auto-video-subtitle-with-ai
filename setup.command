#!/bin/bash
# Cài đặt vsub trên Mac: chạy trong Terminal bằng  bash setup.command
#  1. cài ffmpeg + uv (Homebrew) nếu thiếu
#  2. cài thư viện Python vào .venv
#  3. build Vsub.app ngay trên máy (bundle chuẩn, có icon, nhận file kéo thả)
#     bash setup.command --applet  -> dùng kiểu applet AppleScript cũ nếu bundle không mở được
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
cd "$(dirname "$0")" || exit 1
PROJECT="$(pwd)"
pause() { read -r -p "Enter để đóng"; }

echo "== Cài đặt vsub =="
if ! command -v brew >/dev/null; then
  echo "Chưa có Homebrew. Cài tại https://brew.sh rồi chạy lại."; pause; exit 1
fi
command -v ffmpeg >/dev/null || brew install ffmpeg || { pause; exit 1; }
command -v uv >/dev/null || brew install uv || { pause; exit 1; }

echo "→ Cài thư viện Python (lần đầu mất vài phút)..."
uv sync || { echo "✘ uv sync lỗi, xem ở trên."; pause; exit 1; }
"$PROJECT/.venv/bin/python" -c "import tkinter, mlx_whisper, faster_whisper, tkinterdnd2" \
  || { echo "✘ Thiếu thư viện sau khi cài."; pause; exit 1; }

APP="$PROJECT/Vsub.app"
VER="$("$PROJECT/.venv/bin/python" -c 'import vsub; print(vsub.__version__)')"
echo "→ Tạo Vsub.app..."
rm -rf "$APP"

if [ "$1" = "--applet" ]; then
  # Kiểu cũ: applet AppleScript (có 2 icon trên Dock). Chỉ dùng khi bundle bên dưới không mở được.
  TMP="$(mktemp -t vsub).applescript"
  cat > "$TMP" <<APPLESCRIPT
property proj : "$PROJECT"
on run
	launchGUI("")
end run
on open theItems
	set args to ""
	repeat with f in theItems
		set args to args & " " & quoted form of (POSIX path of f)
	end repeat
	launchGUI(args)
end open
on launchGUI(args)
	do shell script "cd " & quoted form of proj & " && nohup ./.venv/bin/vsub-gui" & args & " < /dev/null >> \"\$HOME/Library/Logs/vsub.log\" 2>&1 &"
end launchGUI
APPLESCRIPT
  osacompile -o "$APP" "$TMP" || { echo "✘ osacompile lỗi"; pause; exit 1; }
  rm -f "$TMP"
else
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Vsub</string>
  <key>CFBundleDisplayName</key><string>Vsub</string>
  <key>CFBundleIdentifier</key><string>dev.viennv.vsub</string>
  <key>CFBundleVersion</key><string>$VER</string>
  <key>CFBundleShortVersionString</key><string>$VER</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>vsub</string>
  <key>CFBundleIconFile</key><string>vsub</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>Video / Audio</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array><string>public.movie</string><string>public.audio</string><string>public.folder</string></array>
    </dict>
  </array>
</dict>
</plist>
PLIST
  # Launcher: exec thẳng vào Python -> tiến trình giao diện CHÍNH LÀ app (1 icon trên Dock)
  cat > "$APP/Contents/MacOS/vsub" <<LAUNCHER
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:\$HOME/.local/bin:\$PATH"
export VSUB_APP="\$(cd "\$(dirname "\$0")/../.." && pwd)"
cd "$PROJECT" || exit 1
exec "$PROJECT/.venv/bin/python" -m vsub.gui "\$@" < /dev/null >> "\$HOME/Library/Logs/vsub.log" 2>&1
LAUNCHER
  chmod +x "$APP/Contents/MacOS/vsub"
  # icon
  ICONSET="$(mktemp -d)/vsub.iconset"; mkdir -p "$ICONSET"
  if "$PROJECT/.venv/bin/python" "$PROJECT/scripts/make_icon.py" "$ICONSET/icon_512x512@2x.png"; then
    for sz in 16 32 128 256 512; do
      sips -z $sz $sz "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
      sips -z $((sz*2)) $((sz*2)) "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/vsub.icns" || echo "(không tạo được icon, bỏ qua)"
    cp "$ICONSET/icon_512x512@2x.png" "$APP/Contents/Resources/vsub.png"
  fi
  xattr -cr "$APP" 2>/dev/null
  codesign --force --deep -s - "$APP" 2>/dev/null || true   # ký ad-hoc để macOS chịu mở
  # báo cho Finder/Dock biết app mới (icon, loại file nhận kéo thả)
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null
fi

echo
echo "→ Kiểm tra các thành phần (Claude để dịch, VieNeu để thuyết minh)..."
"$PROJECT/.venv/bin/python" -m vsub doctor || true

echo
echo "✔ Xong! Từ giờ double-click Vsub.app (hoặc kéo video thả lên icon) để mở. Đang mở thử..."
open "$APP"
