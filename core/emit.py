# -*- coding: utf-8 -*-
"""NC 輸出：固定循環、換刀段、檔頭——本廠慣例的唯一實作。

驗收標準不是「看起來像」，是**逐字元復刻既有程式**（見 tests/test_emit.py）。
數字格式、空白、行序一個位元組都不能差，否則就不能宣稱它取代得了手寫生成器。
"""


def fmt(v):
    """本廠數字慣例：最多三位小數、去尾零、-0 視為 0。"""
    if v is None:
        return ""
    s = "%.3f" % float(v)
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


class ToolBlock:
    """一支刀的完整區塊：標頭註解 → G28 退刀 → 換刀 → 啟動 → G43 → 冷卻。

    M0 換刀鐵則（知識庫：刀具表與刀倉配置，凌鉦 07-25 定案）：
    T3~T22 固定刀直接呼叫；其餘（T1／T2／T100 類）進主軸後必 M0 手動換刀。
    """

    def __init__(self, t, h, desc, s, work="G54", clear_z=50.0,
                 fixed_range=(3, 22), m0_note=None, rigid_tap_s=None, legacy_no_m0=False):
        # legacy_no_m0：復刻 2026-07-25 M0 鐵則定案**之前**產出的程式時用。
        # 它存在的唯一理由是回歸比對——正常生成一律不得開啟。
        self.t, self.h, self.desc, self.s = t, h, desc, s
        self.work, self.clear_z = work, clear_z
        self.fixed_range = fixed_range
        self.m0_note = m0_note
        self.rigid_tap_s = rigid_tap_s
        self.legacy_no_m0 = legacy_no_m0
        self.lines = []

    @property
    def needs_m0(self):
        if self.legacy_no_m0:
            return False
        try:
            n = int(str(self.t).lstrip("Tt"))
        except ValueError:
            return True
        lo, hi = self.fixed_range
        return not (lo <= n <= hi)

    def head(self):
        out = ["", "(--- %s H%02d %s ---)" % (self.t, self.h, self.desc)]
        if self.needs_m0:
            # 非固定刀：先停機讓現場換刀並輸入補正，再繼續
            out.append("(%s)" % (self.m0_note or "換刀後輸入刀長補正 H%02d 再啟動" % self.h))
            out.append("M0")
        out += ["G91 G28 Z0.", "G90",
                "%s M6" % self.t,
                "G0 G90 %s X0 Y0 S%s M3" % (self.work, fmt(self.s)),
                "G43 H%02d Z%s." % (self.h, fmt(self.clear_z)),
                "M8"]
        if self.rigid_tap_s is not None:
            out.append("M29 S%s" % fmt(self.rigid_tap_s))
        return out

    def tail(self):
        return ["G80", "M9", "G91 G28 Z0.", "G90", "M5"]


def cycle(code, points, z, r, q=None, p=None, f=None, retract="G98"):
    """固定循環＋模態座標列。座標由呼叫端給，本模組不產生也不改座標。"""
    if not points:
        return []
    x, y = points[0]
    head = "%s %s X%s Y%s Z%s R%s" % (retract, code, fmt(x), fmt(y), fmt(z), fmt(r))
    if q is not None:
        head += " Q%s" % fmt(q)
    if p is not None:
        head += " P%s" % fmt(p)
    if f is not None:
        head += " F%s" % fmt(f)
    out = [head]
    out += ["X%s Y%s" % (fmt(px), fmt(py)) for px, py in points[1:]]
    out.append("G80")
    return out


def header(onum, title, part_line, machine_line, origin_line, source_line):
    return ["%", "O%04d (%s)" % (onum, title), part_line, machine_line,
            origin_line, source_line,
            "G21 G17 G90 G94 G40 G49 G80"]


def footer():
    return ["", "G91 G28 Z0.", "G28 Y0.", "G90", "M30", "%"]
