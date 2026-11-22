"""MPD (DASH 清单) 解析：把清单还原成每轨的分片文件序列。

支持 SegmentTemplate（$Number$ / $Time$ / SegmentTimeline）、SegmentList、SegmentBase。
Steam 回放、B 站/YouTube DASH 缓存等场景通用。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class DashTrack:
    kind: str                     # "video" | "audio"
    segments: list[Path] = field(default_factory=list)
    init: Path | None = None
    codec: str = ""
    mime: str = ""
    bandwidth: int = 0
    width: int = 0
    height: int = 0
    duration: float = 0.0         # 清单声明的时长（秒），可能为 0


def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _attr(el: ET.Element, name: str, default: str = "") -> str:
    return el.attrib.get(name, default) or default


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _tag(c) == name]


def _first(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _tag(c) == name:
            return c
    return None


def _first_of(els: Iterable[ET.Element], name: str) -> ET.Element | None:
    """注意：ET.Element 的布尔值取决于子元素个数，空元素为 False，
    因此绝不能用 `_first(a, x) or _first(b, x)` 这种写法。"""
    for el in els:
        got = _first(el, name)
        if got is not None:
            return got
    return None


def _parse_iso_duration(val: str) -> float:
    """PT12.5S / PT1H2M3.5S -> 秒"""
    if not val:
        return 0.0
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?$", val.strip())
    if not m:
        return 0.0
    d, h, mi, s = m.groups()
    return (float(d or 0) * 86400 + float(h or 0) * 3600
            + float(mi or 0) * 60 + float(s or 0))


_NUM_PAT = re.compile(r"\$Number(?:%0(\d+)d)?\$")
_TIME_PAT = re.compile(r"\$Time(?:%0(\d+)d)?\$")


def _fill(template: str, number: int | None = None, time: int | None = None,
          rep_id: str = "", bandwidth: int = 0) -> str:
    out = template.replace("$RepresentationID$", rep_id)
    out = out.replace("$Bandwidth$", str(bandwidth))

    def num_sub(m: re.Match) -> str:
        width = int(m.group(1) or 0)
        return str(number).zfill(width) if width else str(number)

    def time_sub(m: re.Match) -> str:
        width = int(m.group(1) or 0)
        return str(time).zfill(width) if width else str(time)

    out = _NUM_PAT.sub(num_sub, out)
    out = _TIME_PAT.sub(time_sub, out)
    return out


def _resolve(base: Path, ref: str) -> Path:
    ref = ref.strip()
    if not ref:
        return base
    p = Path(ref.replace("\\", "/"))
    if p.is_absolute():
        return p
    return (base / p)


def parse_mpd(mpd_path: Path, prefer_best: bool = True) -> list[DashTrack]:
    try:
        tree = ET.parse(mpd_path)
    except (ET.ParseError, OSError):
        return []
    root = tree.getroot()
    base = mpd_path.parent
    global_dur = _parse_iso_duration(_attr(root, "mediaPresentationDuration"))

    periods = _children(root, "Period") or [root]
    tracks: list[DashTrack] = []
    for period in periods:
        period_dur = _parse_iso_duration(_attr(period, "duration")) or global_dur
        for aset in _children(period, "AdaptationSet"):
            tracks.extend(_parse_adaptation(aset, base, period_dur))
        if tracks:
            break   # 只取第一个有效 Period（回放场景足够）
    tracks = [t for t in tracks if t.segments or t.init]
    # MPD 不一定声明了全部轨道：Steam 录制中断、清单被截断时，磁盘上明明有
    # init-stream0.m4s + 一整套视频分片，清单里却只有音频轨。这里按目录补齐。
    tracks.extend(_orphan_tracks(mpd_path.parent, tracks))
    if not tracks:
        return []
    # 关键顺序：先把轨道类型校正为真实值，再做"同类取最高码率"的取舍。
    # 反过来的话，MPD 声明缺失时视频/音频会被判成同一类，低码率那路被直接丢掉。
    refine_kinds(tracks)
    return _select(tracks) if prefer_best else _dedupe(tracks)


_INIT_STEM = re.compile(r"^init[-_](?P<tag>.+)$")
_SEG_SUFFIXES = (".m4s", ".mp4", ".m4v", ".m4a")


def _tag_in(stem: str, tag: str) -> bool:
    """tag 必须整段出现且后面不接数字，避免 stream1 误配 stream10。"""
    start = 0
    while True:
        i = stem.find(tag, start)
        if i < 0:
            return False
        j = i + len(tag)
        if j >= len(stem) or not stem[j].isdigit():
            return True
        start = i + 1


def _orphan_tracks(mpd_dir: Path, declared: list[DashTrack]) -> list[DashTrack]:
    """把目录里没被清单引用到的 init-* 分片补成独立轨道。"""
    try:
        entries = [p for p in mpd_dir.iterdir() if p.is_file()]
    except OSError:
        return []
    used = {t.init.resolve() for t in declared if t.init}
    used_names = {t.init.name for t in declared if t.init}
    out: list[DashTrack] = []
    for init in sorted(entries):
        m = _INIT_STEM.match(init.stem)
        if m is None or init.suffix.lower() not in _SEG_SUFFIXES:
            continue
        try:
            if init.resolve() in used:
                continue
        except OSError:
            continue
        if init.name in used_names:
            continue
        tag = m.group("tag")
        segs: list[tuple[int, Path]] = []
        for e in entries:
            if e == init or e.suffix.lower() not in _SEG_SUFFIXES:
                continue
            if not _tag_in(e.stem, tag):
                continue
            sp = _split_num(e)
            if sp is None:
                continue
            segs.append((sp[1], e))
        if not segs:
            continue
        segs.sort(key=lambda x: x[0])
        out.append(DashTrack(kind="", init=init, segments=[p for _, p in segs]))
        used_names.add(init.name)
    return out


def _parse_adaptation(aset: ET.Element, base: Path, period_dur: float) -> list[DashTrack]:
    """解析一个 AdaptationSet 下的全部 Representation（先不去重，交由 _select）。"""
    reps = _children(aset, "Representation")
    if not reps:
        reps = [ET.Element("Representation")]
    parsed: list[DashTrack] = []
    for rep in reps:
        tr = _parse_representation(aset, rep, base, period_dur)
        if tr is not None:
            parsed.append(tr)
    return parsed


def _select(tracks: list[DashTrack]) -> list[DashTrack]:
    """每个类型保留一路：优先带宽最高，带宽相同时保留分片最多的。"""
    best: dict[str, DashTrack] = {}
    for t in tracks:
        cur = best.get(t.kind)
        if cur is None or (t.bandwidth, len(t.segments)) > (cur.bandwidth, len(cur.segments)):
            best[t.kind] = t
    return list(best.values())


def _dedupe(tracks: Iterable[DashTrack]) -> list[DashTrack]:
    best: dict[tuple[str, int], DashTrack] = {}
    for t in tracks:
        key = (t.kind, t.bandwidth)
        if key not in best:
            best[key] = t
    return list(best.values())


def refine_kinds(tracks: list[DashTrack]) -> None:
    """用 init 分片里的 hdlr 校正轨道类型（就地修改）。

    这是整条链路上唯一可信的判定依据：MPD 的 contentType / mimeType / codecs
    都可能缺失或被写错，而 moov 里的 handler_type 不会。嗅探失败时保留原判定。
    """
    from .mp4box import sniff_media_kind

    for t in tracks:
        probe_file = t.init if (t.init and t.init.exists()) else None
        if probe_file is None:
            probe_file = next((s for s in t.segments if s.exists()), None)
        if probe_file is None:
            continue
        real = sniff_media_kind(probe_file)
        if real:
            t.kind = real

    # 仍无法判定（init 缺失且 MPD 没写清楚）：按码率兜底。
    # DASH 音频一般 64k~320k，视频基本都在 1M 以上，这个界线足够安全。
    for t in tracks:
        if not t.kind:
            t.kind = "video" if t.bandwidth >= 1_000_000 else "audio"


def _guess_kind(mime: str, codecs: str, aset: ET.Element, rep: ET.Element) -> str:
    """按声明猜类型。宁可返回空串（未知），也不要瞎猜成 audio。"""
    ct = _attr(aset, "contentType") or _attr(rep, "contentType")
    if ct.startswith("video"):
        return "video"
    if ct.startswith("audio"):
        return "audio"
    if ct:
        return ct
    for m in (mime, _attr(aset, "mimeType"), _attr(rep, "mimeType")):
        if m.startswith("video"):
            return "video"
        if m.startswith("audio"):
            return "audio"
    c = (codecs or "").lower()
    if any(c.startswith(x) for x in ("avc", "hev", "hvc", "vp0", "vp8", "vp9", "av01", "mp4v")):
        return "video"
    if any(c.startswith(x) for x in ("mp4a", "opus", "vorbis", "ac-3", "ec-3", "flac", "aac")):
        return "audio"
    # 有分辨率 = 视频（Steam 的 AdaptationSet 通常带 width/height）
    w = _attr(rep, "width") or _attr(aset, "width")
    h = _attr(rep, "height") or _attr(aset, "height")
    if w.isdigit() and int(w) > 0 and h.isdigit() and int(h) > 0:
        return "video"
    # 有语言或采样率 = 音频
    if _attr(aset, "lang") or _attr(rep, "audioSamplingRate"):
        return "audio"
    return ""   # 未知：等 refine_kinds 用 init 分片判定


def _parse_representation(aset: ET.Element, rep: ET.Element,
                          base: Path, period_dur: float) -> DashTrack | None:
    mime = _attr(rep, "mimeType") or _attr(aset, "mimeType")
    codec = _attr(rep, "codecs") or _attr(aset, "codecs")
    kind = _guess_kind(mime, codec, aset, rep)
    tr = DashTrack(kind=kind, mime=mime, codec=codec,
                   bandwidth=int(_attr(rep, "bandwidth", "0") or 0),
                   width=int(_attr(rep, "width", "0") or 0),
                   height=int(_attr(rep, "height", "0") or 0),
                   duration=period_dur)
    rep_id = _attr(rep, "id")

    seg_base = _first_of((rep, aset), "SegmentBase")
    seg_list = _first_of((rep, aset), "SegmentList")
    seg_tpl = _first_of((rep, aset), "SegmentTemplate")

    # BaseURL（元素文本，可能是相对目录或完整文件）
    bu = ""
    for el in (_first(rep, "BaseURL"), _first(aset, "BaseURL")):
        if el is not None and (el.text or "").strip():
            bu = (el.text or "").strip()
            break
    if bu:
        base = _resolve(base, bu)

    if seg_tpl is not None:
        _fill_template(tr, seg_tpl, aset, rep, base, period_dur, rep_id)
    elif seg_list is not None:
        init_el = _first(seg_list, "Initialization")
        if init_el is not None:
            src = _attr(init_el, "sourceURL")
            if src:
                tr.init = _resolve(base, src)
        for su in _children(seg_list, "SegmentURL"):
            media = _attr(su, "media")
            if media:
                tr.segments.append(_resolve(base, media))
    elif seg_base is not None:
        init_el = _first(seg_base, "Initialization")
        if init_el is not None:
            src = _attr(init_el, "sourceURL")
            if src:
                tr.init = _resolve(base, src)
        # 整段自包含文件（无 init / 无分片）
        if tr.init is None and base.is_file():
            tr.segments.append(base)
    elif base.is_file():
        tr.segments.append(base)
    return tr


def _fill_template(tr: DashTrack, tpl: ET.Element, aset: ET.Element, rep: ET.Element,
                   base: Path, period_dur: float, rep_id: str) -> None:
    timescale = int(_attr(tpl, "timescale", "0") or _attr(aset, "timescale", "1") or 1) or 1
    start_number = int(_attr(tpl, "startNumber", "1") or 1)
    init_tpl = _attr(tpl, "initialization")
    media_tpl = _attr(tpl, "media")
    if init_tpl:
        tr.init = _resolve(base, _fill(init_tpl, number=start_number, rep_id=rep_id,
                                       bandwidth=tr.bandwidth))

    timeline = _first(tpl, "SegmentTimeline")
    entries: list[tuple[int, int]] = []   # (number, time)
    if timeline is not None:
        cur_time = 0
        number = start_number
        for s in _children(timeline, "S"):
            t_attr = _attr(s, "t")
            if t_attr:
                cur_time = int(t_attr)
            d = int(_attr(s, "d", "0") or 0)
            r = int(_attr(s, "r", "0") or 0)
            repeat = r if r >= 0 else 0
            for _ in range(repeat + 1):
                entries.append((number, cur_time))
                cur_time += d
                number += 1
            if r < 0:   # 重复到 Period 结束
                total = int(period_dur * timescale)
                while d and cur_time < total:
                    entries.append((number, cur_time))
                    cur_time += d
                    number += 1
    elif media_tpl:
        seg_dur = int(_attr(tpl, "duration", "0") or 0)
        if seg_dur > 0 and period_dur > 0:
            count = max(1, int(round(period_dur * timescale / seg_dur)))
            entries = [(start_number + i, i * seg_dur) for i in range(count)]
        else:
            entries = []

    if media_tpl:
        for number, t in entries:
            tr.segments.append(_resolve(base, _fill(media_tpl, number=number, time=t,
                                                    rep_id=rep_id, bandwidth=tr.bandwidth)))
        _supplement_from_dir(tr, base, media_tpl, rep_id, tr.bandwidth)


_STEM_NUM = re.compile(r"^(?P<pre>.*?)(?P<num>\d+)$")


def _split_num(path: Path) -> tuple[str, int, int, str] | None:
    """把 chunk-stream0-00012.m4s 拆成 (前缀, 序号, 序号宽度, 后缀)。"""
    m = _STEM_NUM.match(path.stem)
    if not m:
        return None
    raw = m.group("num")
    return m.group("pre"), int(raw), len(raw), path.suffix


def _supplement_from_dir(tr: DashTrack, base: Path, media_tpl: str,
                         rep_id: str, bandwidth: int) -> None:
    """清单声明的分片数可能少算尾部（时长取整），把目录里多出来的分片补上。"""
    if "$Number" not in media_tpl or not tr.segments:
        return
    last = tr.segments[-1]
    split = _split_num(last)
    if split is None:
        return
    pre, last_num, width, suffix = split
    dir_ = last.parent
    try:
        entries = list(dir_.iterdir())
    except OSError:
        return
    extra: list[tuple[int, Path]] = []
    for e in entries:
        if not e.is_file():
            continue
        sp = _split_num(e)
        if sp is None:
            continue
        p2, n2, _, s2 = sp
        if p2 == pre and s2 == suffix and n2 > last_num:
            extra.append((n2, e))
    for _, f in sorted(extra):
        tr.segments.append(f)
