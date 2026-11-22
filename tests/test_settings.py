"""配置与命名自测：python tests/test_settings.py

改名到 M4SMerge 之后，配置目录、日志目录、默认输出目录都必须跟着换；
配置文件是纯文本，用户（或旧版本）写进来的坏值不能把界面带崩。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_pkg  # noqa: E402
from app.core.settings import APP_NAME, Settings, default_output_dir  # noqa: E402
from app.core.utils import ensure_unique, human_duration, human_size, safe_filename  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def main() -> int:
    print("--- 改名 ---")
    check("应用名是 M4SMerge", APP_NAME == "M4SMerge", APP_NAME)
    check("版本号是 2.0.0", app_pkg.__version__ == "2.0.0", app_pkg.__version__)

    print()
    print("--- 默认配置 ---")
    d = Path(tempfile.mkdtemp())
    s = Settings(d / "settings.json")
    check("默认无损（不压缩）", s.get("compress") is False)
    check("默认启动自动扫描", s.get("auto_scan_on_start") is True)
    check("默认深色", s.get("theme") == "dark")
    check("没有自定义剪辑目录", s.get("scan_roots") == [])
    check("没有自定义 ffmpeg", s.get("ffmpeg_dir") == "")

    print()
    print("--- 坏配置防护 ---")
    cases = [
        ("scan_roots", "not-a-list", []),
        ("scan_roots", [1, 2, None, "  ", "/x"], ["/x"]),
        ("ffmpeg_dir", 123, ""),
        ("output_dir", {"a": 1}, ""),
        ("compress", "yes", False),
    ]
    for key, value, want in cases:
        p = Path(tempfile.mkdtemp()) / "s.json"
        p.write_text(json.dumps({key: value}), "utf-8")
        got = Settings(p).get(key)
        check(f"坏值 {key}={value!r} 被规整", got == want, repr(got))

    print()
    print("--- 未知键不落地 ---")
    p = Path(tempfile.mkdtemp()) / "s.json"
    p.write_text(json.dumps({"不存在的键": 1, "theme": "light"}), "utf-8")
    s2 = Settings(p)
    check("已知键正常读取", s2.get("theme") == "light")
    check("未知键被忽略", s2.get("不存在的键") is None)

    print()
    print("--- 存盘 ---")
    p = Path(tempfile.mkdtemp()) / "s.json"
    s3 = Settings(p)
    s3.set("output_dir", "/tmp/x")
    s3.set("compress", True)
    s3.save()
    s4 = Settings(p)
    check("存盘后能读回", s4.get("output_dir") == "/tmp/x" and s4.get("compress") is True)
    check("存盘是合法 JSON", isinstance(json.loads(p.read_text("utf-8")), dict))

    print()
    print("--- 默认输出目录 ---")
    out = default_output_dir()
    check("默认输出目录存在", out.is_dir(), str(out))

    print()
    print("--- 输出重名不覆盖 ---")
    od = Path(tempfile.mkdtemp())
    a = ensure_unique(od / "clip_1.mp4")
    check("首次不加后缀", a.name == "clip_1.mp4", a.name)
    a.write_bytes(b"x")
    b = ensure_unique(od / "clip_1.mp4")
    check("第二次加 -2", b.name == "clip_1-2.mp4", b.name)
    b.write_bytes(b"x")
    c = ensure_unique(od / "clip_1.mp4")
    check("第三次加 -3", c.name == "clip_1-3.mp4", c.name)
    check("原有文件没被覆盖", a.read_bytes() == b"x")

    print()
    print("--- 文件名清洗 ---")
    check("非法字符被替换", safe_filename('a<b>c:d/e\\f|g?h*i') == "a_b_c_d_e_f_g_h_i",
          safe_filename('a<b>c:d/e\\f|g?h*i'))
    check("空文件名有兜底", safe_filename("") == "clip", safe_filename(""))
    check("超长名被截断", len(safe_filename("x" * 400)) <= 120, str(len(safe_filename("x" * 400))))

    print()
    print("--- 格式化 ---")
    check("秒数格式化", human_duration(75) == "01:15", human_duration(75))
    check("小时格式化", human_duration(3725) == "1:02:05", human_duration(3725))
    check("未知时长", human_duration(None) == "--:--", human_duration(None))
    check("体积格式化", human_size(1536 * 1024) == "1.5 MB", human_size(1536 * 1024))

    print()
    print(f"{'全部通过' if not failures else '失败 %d 项: %s' % (len(failures), failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
