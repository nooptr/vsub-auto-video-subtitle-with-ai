# vsub cho Windows: lần đầu (hoặc sau khi cập nhật) cài Python + thư viện bằng uv, tải FFmpeg,
# tạo shortcut "vsub" trên Desktop và Start Menu, rồi mở app.
#   Vsub.cmd               mở app (tự cài nếu cần)
#   Vsub.cmd -Setup        cài lại
#   Vsub.cmd -NoLaunch     chỉ cài, không mở app
param([switch]$Setup, [switch]$NoLaunch, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Root = $PSScriptRoot
$HomeDir = if ($env:VSUB_HOME) { $env:VSUB_HOME } else { Join-Path $env:LOCALAPPDATA 'vsub' }
$Venv = Join-Path $HomeDir 'venv'
$Pyw = Join-Path $Venv 'Scripts\pythonw.exe'
$Ver = (Get-Content (Join-Path $Root 'app\VERSION') -Raw).Trim()
$Marker = Join-Path $Venv '.vsub-version'
$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'

New-Item -ItemType Directory -Force $HomeDir | Out-Null
# để nút "Cập nhật ngay" trong app biết bản cài nằm ở đâu
[IO.File]::WriteAllText((Join-Path $HomeDir 'install.json'),
  (@{ kind = 'windows'; path = $Root; version = $Ver } | ConvertTo-Json))
$env:Path = (Join-Path $HomeDir 'ffmpeg\bin') + ";$env:USERPROFILE\.local\bin;$env:Path"

function Install-Vsub {
  Write-Host "== vsub ${Ver}: cài đặt lần đầu / cập nhật ==" -ForegroundColor Cyan
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host '-> Cài uv (trình cài thư viện Python)...'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  }
  $src = Join-Path $HomeDir 'src'
  if (Test-Path $src) { Remove-Item $src -Recurse -Force }
  Copy-Item (Join-Path $Root 'app') $src -Recurse
  Write-Host '-> Cài Python và thư viện (lần đầu mất vài phút)...'
  $env:UV_PROJECT_ENVIRONMENT = $Venv
  & uv sync --frozen --no-editable --project $src
  if ($LASTEXITCODE) { throw "uv sync lỗi (mã $LASTEXITCODE)" }

  if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host '-> Tải FFmpeg (~90 MB)...'
    $zip = Join-Path $env:TEMP 'vsub-ffmpeg.zip'
    $tmp = Join-Path $env:TEMP 'vsub-ffmpeg'
    Invoke-WebRequest -UseBasicParsing $FfmpegUrl -OutFile $zip
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip -DestinationPath $tmp -Force
    $bin = (Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1).DirectoryName
    $dst = Join-Path $HomeDir 'ffmpeg\bin'
    New-Item -ItemType Directory -Force $dst | Out-Null
    Copy-Item (Join-Path $bin '*') $dst -Force
    Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
  Set-Content -Path $Marker -Value $Ver

  $ico = Join-Path $HomeDir 'vsub.ico'
  Copy-Item (Join-Path $Root 'vsub.ico') $ico -Force
  $ws = New-Object -ComObject WScript.Shell
  foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    if (-not $dir -or -not (Test-Path $dir)) { continue }
    $lnk = $ws.CreateShortcut((Join-Path $dir 'vsub.lnk'))
    $lnk.TargetPath = $Pyw
    $lnk.Arguments = '-m vsub.gui'
    $lnk.WorkingDirectory = $HomeDir
    $lnk.IconLocation = $ico
    $lnk.Description = 'vsub - làm phụ đề, dịch, thuyết minh tự động'
    $lnk.Save()
  }
  Write-Host '✔ Xong. Đã tạo shortcut "vsub" trên Desktop và Start Menu.' -ForegroundColor Green
}

try {
  $current = if (Test-Path $Marker) { (Get-Content $Marker -Raw).Trim() } else { '' }
  if ($Setup -or -not (Test-Path $Pyw) -or $current -ne $Ver) { Install-Vsub }
  if (-not $NoLaunch) {
    $argList = @('-m', 'vsub.gui') + @($Files | Where-Object { $_ } | ForEach-Object { '"' + $_ + '"' })
    Start-Process -FilePath $Pyw -ArgumentList $argList -WorkingDirectory $HomeDir
  }
} catch {
  Write-Host ''
  Write-Host "✘ Lỗi: $_" -ForegroundColor Red
  if (-not $env:CI) { Read-Host 'Enter để đóng' }
  exit 1
}
