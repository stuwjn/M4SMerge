"""应用配置持久化（JSON，原子写入）。

配置项刻意保持很少：M4SMerge 只做「把 Steam 剪辑合并成 mp4」一件事，
需要记住的只有 ffmpeg 在哪、导出到哪、主题深浅、以及用户手动指定的
剪辑目录。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


APP_NAME = "M4SMerge"


def app_root() -> Path:
    """程序所在目录：打包后是 exe 同级，源码运行是项目根。"""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_temp_dir() -> Path:
    """中转目录：程序目录下的 temp（解压到哪就占哪，用完清空）。"""
    return app_root() / "temp"


def portable_root() -> Path | None:
    """便携模式：exe（或项目根）旁边放了 portable.flag 就把配置写在那儿。

    这样整个程序连同配置都能装进 U 盘，不往 %APPDATA% 落任何东西。
    """
    import sys
    bases: list[Path] = []
    if getattr(sys, "frozen", False):
        bases.append(Path(sys.executable).resolve().parent)
    bases.append(Path(__file__).resolve().parents[2])
    for b in bases:
        try:
            if (b / "portable.flag").exists():
                return b
        except OSError:
            continue
    return None


def app_data_dir() -> Path:
    root = portable_root()
    if root is not None:
        p = root / "data"
    else:
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_output_dir() -> Path:
    """默认导出到系统「视频」文件夹。

    Windows 上 %USERPROFILE%\\Videos 是本地化的（中文系统显示「视频」，
    但真名仍是 Videos），所以按存在性挑，最后才退回主目录。
    """
    home = Path.home()
    for cand in (home / "Videos", home / "Videos" / "Captures", home / "视频"):
        try:
            if cand.is_dir():
                return cand
        except OSError:
            continue
    return home


DEFAULTS: dict[str, Any] = {
    "ffmpeg_dir": "",            # 自定义 ffmpeg 所在目录（空=自动探测）
    "scan_roots": [],            # 用户手动指定的剪辑目录（Steam 的会自动探测）
    "output_dir": "",            # 导出目录（空=系统「视频」）
    "auto_scan_on_start": True,
    "theme": "dark",
    "compress": False,           # 关=无损直通（推荐）；开=重编码压到 1080p
}


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_data_dir() / "settings.json")
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in DEFAULTS:
                        self._data[k] = v
        except (OSError, ValueError):
            pass
        # 类型防护：配置文件是可以被手改的，坏值不能带进界面。
        roots = self._data.get("scan_roots")
        if not isinstance(roots, list):
            self._data["scan_roots"] = []
        else:
            self._data["scan_roots"] = [str(x) for x in roots if isinstance(x, str) and x.strip()]
        for key in ("ffmpeg_dir", "output_dir"):
            if not isinstance(self._data.get(key), str):
                self._data[key] = ""
        # 布尔项只认真布尔：配置文件里写 "yes" 之类一律退回默认，
        # 免得 bool("no") == True 这种坑。
        for key in ("compress", "auto_scan_on_start"):
            if not isinstance(self._data.get(key), bool):
                self._data[key] = DEFAULTS[key]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)
