# 下载 ffmpeg（Windows 64 位）到 bin/，供 PyInstaller 一起打包
# 用法: powershell -ExecutionPolicy Bypass -File scripts\fetch_ffmpeg.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root "bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null

if ((Test-Path (Join-Path $bin "ffmpeg.exe")) -and (Test-Path (Join-Path $bin "ffprobe.exe"))) {
    Write-Host "bin\ffmpeg.exe 已存在，跳过下载"
    exit 0
}

$url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$zip = Join-Path $env:TEMP "ffmpeg-essentials.zip"
Write-Host "下载 ffmpeg: $url"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing

$tmp = Join-Path $env:TEMP "ffmpeg_extract"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -Path $zip -DestinationPath $tmp -Force

$exe = Get-ChildItem -Path $tmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
$probe = Get-ChildItem -Path $tmp -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
if (-not $exe) { throw "压缩包内未找到 ffmpeg.exe" }

Copy-Item $exe.FullName (Join-Path $bin "ffmpeg.exe") -Force
if ($probe) { Copy-Item $probe.FullName (Join-Path $bin "ffprobe.exe") -Force }

Remove-Item -Recurse -Force $tmp
Remove-Item -Force $zip
Write-Host "完成：$(Join-Path $bin 'ffmpeg.exe')"
