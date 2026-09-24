# -*- coding: utf-8 -*-
"""深度規則：把知識庫的公式變成唯一的可執行實作。

為什麼要這支：鑽尖 0.3D、無效牙 2.4P、排屑餘裕、殘餘壁厚 1.0/1.5 這些廠規
已經寫在知識庫，但過去每個案子的 gen_gcode.py 都自己重打一遍——打錯不會有人發現
（見 independence.py 實測：四案 39 處重寫）。

每個計算都回傳 (值, 算式)——**算式要能給人看**，不是只給機器用。
師傅那句「圖面寫 20 深，我們就會給它 23 深…然後鑽 26…程式是 28」要能逐段還原。
"""


class Term:
    """深度鏈的一段。unconfirmed 帶待澄清編號——未定案的值必須一路標到產出。"""

    def __init__(self, label, value, source="", unconfirmed=""):
        self.label, self.value, self.source, self.unconfirmed = label, value, source, unconfirmed

    def as_dict(self):
        d = {"label": self.label, "value": round(self.value, 4)}
        if self.source:
            d["source"] = self.source
        if self.unconfirmed:
            d["unconfirmed"] = self.unconfirmed
        return d


class Depth:
    """一段深度的計算結果：值 ＋ 可讀算式 ＋ 逐項出處。"""

    def __init__(self, terms, round_to=None):
        self.terms = terms
        raw = sum(t.value for t in terms)
        self.raw = raw
        self.value = round(raw, 2) if round_to is None else round(raw / round_to) * round_to

    @property
    def expr(self):
        parts = []
        for i, t in enumerate(self.terms):
            sign = "" if i == 0 else (" + " if t.value >= 0 else " − ")
            parts.append("%s%s %g" % (sign, t.label, abs(t.value)))
        tail = " = %g" % self.raw
        if abs(self.value - self.raw) > 1e-9:
            tail += " → %g" % self.value
        return "".join(parts) + tail

    def as_dict(self):
        return {"expr": self.expr, "terms": [t.as_dict() for t in self.terms],
                "result": self.value}


# ---- 各條規則（出處即知識庫頁名）----

KB_DEPTH = "知識庫：孔加工深度計算"
KB_SEQ = "知識庫：孔加工刀序與程式碼"


# 廠內慣用比例（知識庫〈孔加工深度計算〉二節載明的值）。
# 精確三角值為 0.30043／0.20711，但**本廠程式一律按 0.300／0.207 計算**——
# 核心若用精確值，同一個 Ø14 貫穿孔會算出 45.01 而非廠內的 45.0。
# 差 0.006mm 物理上無意義，但會讓核心與既有程式對不起來，也違背「規則跟廠走」。
SHOP_POINT_RATIO = {118: 0.300, 135: 0.207}


def drill_point(dia, angle=118, cfg=None):
    """鑽尖長度 Lp。比例優先取廠內慣用值，未登錄的角度才回退精確三角式。"""
    import math

    ratio = SHOP_POINT_RATIO.get(int(round(angle))) or (0.5 / math.tan(math.radians(angle / 2.0)))
    return Term("鑽尖(%.0f° %.3f×Ø%g)" % (angle, ratio, dia), ratio * dia,
                KB_DEPTH + " 二節",
                # ⚠#13：本廠「盲孔自動加 2」是固定值或 0.3D 未定案，未回確前一律走公式
                unconfirmed="#13" if abs(angle - 118) < 1e-6 else "")


def invalid_thread(pitch, turns=2.4):
    """無效牙＝導入牙數 × 螺距（中錐約 2.4 牙）。"""
    return Term("無效牙(%gP)" % turns, turns * pitch, KB_DEPTH + " 四、五節")


def chip_clearance(mm=3.0):
    """排屑餘裕。⚠#12：本廠給 3mm（2.4P），低於教科書 3–5P，深牙/薄板時裕度不足。"""
    return Term("排屑餘裕", mm, KB_DEPTH + " 四節", unconfirmed="#12")


def residual_limit(dia, small=1.0, large=1.5, split=12.0):
    """盲孔殘餘壁厚下限：小刀 1.0、大刀 1.5。"""
    return large if dia >= split else small


def blind_max_depth(thickness, dia, **kw):
    """盲孔最深可鑽到多少（＝板厚 − 殘餘壁厚下限）。"""
    need = residual_limit(dia, **kw)
    return thickness - need, need


def tap_blind_chain(thread_depth, pitch, drill_dia, thickness=None, **kw):
    """攻牙盲孔的四段深度鏈——師傅影片 12:35 的 20→23→26→28。

    回傳 (tap_depth, drill_depth)，兩者都是 Depth（各自帶算式）。
    """
    tap = Depth([Term("圖面有效牙深", thread_depth, "圖面"), invalid_thread(pitch)])
    drill = Depth([Term("攻牙 Z", tap.value, "上一段"), chip_clearance(kw.get("chip", 3.0)),
                   drill_point(drill_dia, kw.get("angle", 118))])
    if thickness is not None:
        limit, need = blind_max_depth(thickness, drill_dia)
        if drill.value > limit + 1e-9:
            drill.violation = ("殘餘壁厚不足：板厚 %g − 深 %g = %.2f ＜ 下限 %.1f"
                               % (thickness, drill.value, thickness - drill.value, need))
    return tap, drill


def through_depth(thickness, dia, angle=118, extra=0.0, flat_bottom=False, over_len=None):
    """貫穿孔：全徑要穿出底面。

    平底刀（高速鑽／U鑽）沒有鑽尖——貫穿量走刀具庫「通過長」欄，不是 0.3D。
    """
    terms = [Term("板厚", thickness, "素材")]
    if flat_bottom:
        terms.append(Term("通過長(刀具庫)", over_len if over_len is not None else 5.0, "刀具庫 高速鑽表"))
    else:
        terms.append(drill_point(dia, angle))
    if extra:
        terms.append(Term("餘裕", extra, "慣例"))
    return Depth(terms)


def tap_through_depth(thickness, over_len):
    """貫穿攻牙＝素材厚＋攻牙表「超過長」欄（知識庫：TH制程式慣例）。"""
    return Depth([Term("素材厚", thickness, "素材"),
                  Term("超過長(攻牙表)", over_len, "知識庫：TH制程式慣例")])


def chamfer_z(hole_dia, c, flat_comp):
    """孔口倒角 Z＝(D孔 + 2C − f) ÷ 2；f＝刀尖小平面，h＝f/2 為每支刀固有屬性。"""
    val = (hole_dia + 2 * c - flat_comp * 2) / 2.0
    return Depth([Term("孔半徑", hole_dia / 2.0, "圖面"),
                  Term("倒角量 C", c, "圖面"),
                  Term("小平面補償 h", -flat_comp, KB_SEQ + " 三節")]), val


def cycle_for(dia, depth, ld_thresholds=(3.0, 5.0)):
    """L/D → 固定循環選型（知識庫：孔加工刀序與程式碼 五節）。"""
    if not dia:
        return "G81", 0.0
    ld = abs(depth) / dia
    lo, hi = ld_thresholds
    return ("G81" if ld < lo else "G73" if ld <= hi else "G83"), ld
