"""纯字节解析 MP4/fMP4 的 box 结构，用于**权威判定轨道类型**。

为什么不靠 MPD 声明：Steam 回放的 manifest.mpd 在异常退出、录制中断、
或某些版本生成时，AdaptationSet 上可能缺失 contentType / mimeType / codecs，
此时任何"猜"都可能把视频轨判成音频轨（或反之），进而导致：
  · 列表里显示"只有音频"
  · 预览黑屏、导出只有声音
真正的证据在 init 分片里——moov/trak/mdia/hdlr 的 handler_type 就是 vide/soun。
读一个几 KB 的 init 文件即可拿到，零解码、毫秒级。
"""
from __future__ import annotations

from pathlib import Path

# ISO BMFF 中常见 handler_type
HANDLER_KIND = {
    b"vide": "video",
    b"soun": "audio",
    b"sbtl": "subtitle",
    b"subt": "subtitle",
    b"text": "subtitle",
    b"meta": "meta",
    b"hint": "hint",
}

_SCAN_LIMIT = 4 * 1024 * 1024   # init 分片通常几 KB，给 4MB 余量足够


class _Reader:
    """在内存里按 box 边界游走。"""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def boxes(self, start: int = 0, end: int | None = None):
        """逐个产出 (type, payload_start, payload_end)。遇到畸形 box 立即停止。"""
        data = self.data
        end = len(data) if end is None else min(end, len(data))
        pos = max(0, start)
        while pos + 8 <= end:
            size = int.from_bytes(data[pos:pos + 4], "big")
            typ = data[pos + 4:pos + 8]
            header = 8
            if size == 1:                       # 64 位扩展长度
                if pos + 16 > end:
                    return
                size = int.from_bytes(data[pos + 8:pos + 16], "big")
                header = 16
            elif size == 0:                     # 延伸到文件末尾
                size = end - pos
            if size < header or pos + size > end:
                return
            yield typ, pos + header, pos + size
            pos += size

    def find(self, typ: bytes, start: int = 0, end: int | None = None):
        for t, ps, pe in self.boxes(start, end):
            if t == typ:
                return ps, pe
        return None


def _handlers(reader: _Reader, moov: tuple[int, int]) -> list[str]:
    """遍历 moov/trak/mdia/hdlr，收集每条轨道的 handler 类型。"""
    out: list[str] = []
    for typ, ps, pe in reader.boxes(*moov):
        if typ != b"trak":
            continue
        mdia = reader.find(b"mdia", ps, pe)
        if mdia is None:
            continue
        hdlr = reader.find(b"hdlr", *mdia)
        if hdlr is None:
            continue
        hs = hdlr[0]
        # hdlr: version(1) flags(3) pre_defined(4) handler_type(4)
        if hs + 12 > hdlr[1]:
            continue
        raw = reader.data[hs + 8:hs + 12]
        kind = HANDLER_KIND.get(raw)
        if kind:
            out.append(kind)
    return out


def sniff_track_kinds(path: Path | str) -> list[str]:
    """返回文件里每条轨道的类型，如 ['video', 'audio']。

    解析失败（无 moov / 非 MP4 / 文件读不到）时返回空列表，
    调用方应视为"未知"而不是"没有轨道"。
    """
    p = Path(path)
    try:
        with p.open("rb") as f:
            head = f.read(_SCAN_LIMIT)
    except OSError:
        return []
    if len(head) < 16:
        return []
    reader = _Reader(head)
    # 顶层找 moov。init 分片 = ftyp + moov；完整 mp4 可能是 ftyp + moov + mdat
    moov = reader.find(b"moov")
    if moov is None:
        # moov 可能因为 mdat 在前而被截断，退一步从文件头整体扫一遍
        return []
    return _handlers(reader, moov)


def sniff_media_kind(path: Path | str) -> str:
    """只关心"有没有视频"：返回 'video' / 'audio' / ''（未知）。"""
    kinds = sniff_track_kinds(path)
    if "video" in kinds:
        return "video"
    if "audio" in kinds:
        return "audio"
    return ""


def looks_like_mp4(path: Path | str) -> bool:
    """粗判是否是 ISO BMFF（ftyp box 在第 4~8 字节）。"""
    try:
        with Path(path).open("rb") as f:
            head = f.read(12)
    except OSError:
        return False
    return len(head) >= 12 and head[4:8] == b"ftyp"
