# Đóng gói bản Windows -> dist/vsub-windows-amd64.zip (thư mục "vsub": Vsub.cmd, vsub.ps1, vsub.ico, app/)
# Lần chạy đầu Vsub.cmd cài Python + thư viện bằng uv (faster-whisper chạy CPU), tải FFmpeg, tạo shortcut.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$ver = (uv run --no-project python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])").Trim()
$dist = Join-Path (Get-Location) 'dist'
$out = Join-Path $dist 'vsub'
$zip = Join-Path $dist 'vsub-windows-amd64.zip'
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
if (Test-Path $zip) { Remove-Item $zip -Force }
$app = Join-Path $out 'app'
New-Item -ItemType Directory -Force $app | Out-Null
Copy-Item pyproject.toml, uv.lock, README.md, .python-version $app
Copy-Item src (Join-Path $app 'src') -Recurse
Get-ChildItem $app -Recurse -Directory -Include __pycache__, *.egg-info | Remove-Item -Recurse -Force
Get-ChildItem $app -Recurse -File -Filter .DS_Store | Remove-Item -Force
[IO.File]::WriteAllText((Join-Path $app 'VERSION'), $ver)
Copy-Item packaging\windows\Vsub.cmd, packaging\windows\vsub.ps1 $out
uv run --no-project --with pillow python scripts/make_icon.py (Join-Path $out 'vsub.ico')
if ($LASTEXITCODE) { throw 'make_icon lỗi' }
Compress-Archive -Path $out -DestinationPath $zip
Write-Host "✔ $zip (vsub $ver)"
