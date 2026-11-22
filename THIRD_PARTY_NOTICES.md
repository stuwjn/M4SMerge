# 第三方资源与许可声明

本项目自身以 MIT 协议发布。以下是随项目分发的第三方资源，以及它们的授权情况。

---

## YesPlayMusic — 界面设计与图标

- **项目**：https://github.com/qier222/YesPlayMusic
- **作者**：qier222 及贡献者
- **许可**：MIT License，Copyright (c) 2020-2023 qier222

用途：

1. **界面语言**：`app/ui/theme.py` 中的颜色令牌、字号、圆角、间距、导航/列表的尺寸与状态样式，
   均对照该仓库 `src/assets/css/global.scss` 与各组件 scoped 样式中的实际取值实现，而非凭截图估算。
2. **小图标**：`app/resources/` 下的 `arrow-*.png`（下拉箭头）、`check.png`（复选框勾）、
   `sun-*.png` / `moon-*.png`（深浅色切换）由该仓库 `src/assets/icons/` 下的对应 SVG
   重新着色并栅格化而来（原始 SVG 逐字节取自该 MIT 项目）。

MIT 许可全文：

```
MIT License

Copyright (c) 2020-2023 qier222

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

应用图标 `app.ico` / `app.png`（圆角方块 + 三道横杠）为本项目自行绘制，不含第三方素材。

---

## FFmpeg

- **项目**：https://ffmpeg.org
- **许可**：LGPL 2.1+ / GPL 2+（取决于构建选项）

Windows 打包版内置的是 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 的 **essentials** 构建
（FFmpeg 6.0，含 libx264 / libx265，因此该构建整体按 **GPL v2+** 分发）。

程序通过命令行调用 `ffmpeg.exe` / `ffprobe.exe`，属于独立进程调用，不构成链接；
但**如果你要再分发内置 ffmpeg 的安装包**，请随包附带 FFmpeg 的 GPL 许可文本与源码获取方式
（https://ffmpeg.org/download.html）。源码运行时自备 ffmpeg 则不受此约束。

---

## PySide6 / Qt

- **项目**：https://www.qt.io/qt-for-python
- **许可**：LGPL v3（PySide6 采用 LGPLv3 / GPLv3 双授权）

以 PyInstaller 打包时 Qt 库以动态链接形式随包分发，遵循 LGPLv3 的相应义务
（保留许可声明、允许替换库文件）。如需闭源商业分发，请评估 Qt 的商业授权。

---

## 其他 Python 依赖

| 包 | 许可 | 用途 |
|---|---|---|
| PySide6 | LGPL-3.0 | GUI |
| PyInstaller | GPL-2.0（带例外条款，允许打包专有程序） | 生成 Windows 可执行文件 |

---

## 关于 Steam 剪辑格式

本项目实现的是公开的 **MPEG-DASH / ISO BMFF（fMP4）** 规范解析，
不包含、不反编译 Valve 的任何专有代码或资源。Steam 仅为格式来源的场景说明，与 Valve 无隶属关系。
