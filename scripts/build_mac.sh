#!/bin/bash
# Đóng gói Vsub.app bản phát hành -> dist/vsub-mac-universal.zip
# App chỉ chứa script + mã nguồn + uv.lock, nên chạy được trên cả Mac chip M và Mac Intel:
# lần mở đầu, uv cài Python và thư viện đúng kiến trúc máy (mlx-whisper trên chip M, faster-whisper trên Intel).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VER="$(uv run --no-project python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
DIST="$ROOT/dist"
APP="$DIST/Vsub.app"
rm -rf "$APP" "$DIST/vsub-mac-universal.zip"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"

cp pyproject.toml uv.lock README.md .python-version "$APP/Contents/Resources/app/"
rsync -a --exclude __pycache__ --exclude '*.egg-info' --exclude .DS_Store src "$APP/Contents/Resources/app/"
echo "$VER" > "$APP/Contents/Resources/app/VERSION"
cp packaging/mac/launcher.sh "$APP/Contents/MacOS/vsub"
cp packaging/mac/setup.command "$APP/Contents/Resources/setup.command"
chmod +x "$APP/Contents/MacOS/vsub" "$APP/Contents/Resources/setup.command"

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
  <key>LSMinimumSystemVersion</key><string>11.0</string>
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

ICONSET="$(mktemp -d)/vsub.iconset"
mkdir -p "$ICONSET"
uv run --no-project --with pillow python scripts/make_icon.py "$ICONSET/icon_512x512@2x.png"
for sz in 16 32 128 256 512; do
  sips -z $sz $sz "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
  sips -z $((sz * 2)) $((sz * 2)) "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/vsub.icns"

xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep -s - "$APP"   # ký ad-hoc
(cd "$DIST" && ditto -c -k --sequesterRsrc --keepParent Vsub.app vsub-mac-universal.zip)
echo "✔ $DIST/vsub-mac-universal.zip (vsub $VER)"
