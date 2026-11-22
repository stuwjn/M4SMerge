# 打包成 Windows 免安装版（dist\M4SMerge\M4SMerge.exe）
# 用法: powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
param(
    [switch]$SkipFfmpeg,
    [switch]$OneFile
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install "pyinstaller>=6.3"

if (-not $SkipFfmpeg) {
    & (Join-Path $PSScriptRoot "fetch_ffmpeg.ps1")
}

$args = @(
    "--noconfirm", "--clean",
    "--name", "M4SMerge",
    "--paths", ".",
    "--exclude-module", "tkinter",
    "--exclude-module", "numpy",
    "--exclude-module", "pandas",
    "--exclude-module", "matplotlib",
    # M4SMerge 不播放、不要浏览器内核：排除掉能省一百多 MB
    "--exclude-module", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineQuick",
    "--exclude-module", "PySide6.QtWebChannel",
    "--exclude-module", "PySide6.QtMultimedia",
    "--exclude-module", "PySide6.QtMultimediaWidgets",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtQuickWidgets"
)
# 两者都必须带 --windowed：否则 --onefile 打出来的 exe 会挂一个黑色控制台窗口
$args += "--windowed"
if ($OneFile) { $args += "--onefile" }

if (Test-Path "bin\ffmpeg.exe") {
    $args += @("--add-binary", "bin\ffmpeg.exe;bin", "--add-binary", "bin\ffprobe.exe;bin")
}
if (Test-Path "app\resources") {
    $args += @("--add-data", "app\resources;app\resources")
}
if (Test-Path "app\resources\app.ico") {
    $args += @("--icon", "app\resources\app.ico")
}
$args += "app\main.py"

pyinstaller @args

Write-Host ""
Write-Host "打包完成。运行: dist\M4SMerge\M4SMerge.exe"
Write-Host "若目标机器未内置 ffmpeg，请把 ffmpeg.exe / ffprobe.exe 放到 exe 同级 bin 目录，或在程序设置里指定路径。"
