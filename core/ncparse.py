# -*- coding: utf-8 -*-
"""NC 程式解析：把 .nc 讀回「工步＋孔位」的結構，供斷言稽核使用。

與 app 端 electron/lib/hole-plan.js 的反推器同一套認定規則（刻意保持一致）：
  - 工步標頭 `(--- T12 H12 描述 ---)`，H 為選填（較早的案件只寫 T 號，H 由 G43 行補）
  - 循環行後接的裸 X/Y 列＝模態續行，到 G80 為止
  - 倒角認刀具描述（倒角／CC）不認循環碼——本廠倒角有用 G82 也有用 G81
"""
import re

CYCLES = ("G73", "G74", "G76", "G81", "G82", "G83", "G84", "G85", "G86", "G89")
CYCLE_RE = re.compile(r"\b(%s)\b" % "|".join(CYCLES))
HEAD_RE = re.compile(r"^\(-{2,}\s*(T\d+)\s+(?:H(\d+)\s+)?(.+?)\s*-{2,}\)\s*$")
# 檔頭素材尺寸。兩種寫法都要認，而且**軸序不一致**：
#   測試002「素材 40.3x240x1300」＝厚x寬x長
#   測試003「… S50C 1000x90x25.3」＝長x寬x厚（且沒有「素材」二字）
# 故不能靠位置取厚度——見 depth_budget。
STOCK_RE = re.compile(r"素材\s*([\d.]+)\s*[xX×]\s*([\d.]+)\s*[xX×]\s*([\d.]+)")
STOCK_BARE_RE = re.compile(r"\b([\d.]+)\s*[xX×]\s*([\d.]+)\s*[xX×]\s*([\d.]+)\b")
OP_RE = re.compile(r"^O\d+\s*\((OP\d+)", re.M)
# 檔頭座標系列：(G54 X0Y0=左前角[...] Z0=素材頂面 ; 單位mm)
Z0_RE = re.compile(r"Z0=([^;）)]*)")


def _num(line, letter):
    m = re.search(r"%s(-?[\d.]+)" % letter, line)
    return float(m.group(1)) if m else None


class Block:
    """一個固定循環區塊＝一支刀的一組同參數孔。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __repr__(self):
        return "<%s %s Z%s x%d %s>" % (self.tool_t, self.cycle, self.z, len(self.coords), self.desc[:24])

    # --- 由描述抽出的規格 ---
    @property
    def thread(self):
        """攻牙規格 (大徑, 螺距)，如 M16xP2.0 → (16.0, 2.0)"""
        m = re.search(r"M(\d+(?:\.\d+)?)\s*[xX*]\s*P?([\d.]+)", self.desc)
        return (float(m.group(1)), float(m.group(2))) if m else None

    @property
    def dia(self):
        """刀具／孔徑：描述裡第一個 Ø 值"""
        m = re.search(r"Ø(\d+(?:\.\d+)?)", self.desc)
        return float(m.group(1)) if m else None

    @property
    def is_chamfer(self):
        return bool(re.search(r"倒角", self.desc)) or bool(re.search(r"\bCC\d", self.desc))

    @property
    def is_spot(self):
        return bool(re.search(r"中心鑽|點窩", self.desc))


class Program:
    def __init__(self, path, text):
        self.path = path
        self.text = text
        m = OP_RE.search(text)
        self.op = m.group(1) if m else ""
        head = "\n".join(text.splitlines()[:8])
        s = STOCK_RE.search(head) or STOCK_BARE_RE.search(head)
        self.stock = tuple(float(g) for g in s.groups()) if s else None
        self.blocks = _parse_blocks(text, path)

    @property
    def z0(self):
        """檔頭宣告的 Z0 基準描述（如『素材頂面』『側面(朝上)』）"""
        m = Z0_RE.search(self.text)
        return m.group(1).strip() if m else ""

    @property
    def depth_budget(self):
        """Z 方向可用的材料厚度，(值, 說明) —— 判不出來時回 (None, 原因)。

        Z 打進板厚的工序（頂/底面朝上）才等於素材厚；側面立夾的 Z 打進的是寬或長，
        素材列的三個數字對不出是哪一個——**寧可判不出，也不要拿板厚給出假合格**。
        """
        if not self.stock:
            return None, "檔頭無素材尺寸"
        z0 = self.z0
        if any(k in z0 for k in ("頂面", "底面", "研磨完成面", "完成面", "工件面")):
            # 檔頭三尺寸的軸序各案不一（厚x寬x長 vs 長x寬x厚），無法靠位置判定厚度。
            # 取最小值：板件恆成立；若遇高塊件會低估厚度→殘餘壁算得更薄→偏向誤報 FAIL
            # 而非假合格，對安全規則而言是正確的偏誤方向。推論寫進說明讓人看得見。
            t = min(self.stock)
            return t, "厚度取檔頭三尺寸最小值 %g（%s；檔頭未標明何者為厚）" % (
                t, "x".join("%g" % v for v in self.stock))
        if "側面" in z0 or "端面" in z0:
            return None, "側面／端面工序：Z 打進的不是板厚，深度預算需 OP 定義才能檢核（Z0=%s）" % z0
        return None, "無法由檔頭判定 Z 的深度預算（Z0=%s）" % (z0 or "未標")


def _parse_blocks(text, path):
    """解析固定循環區塊，並記住每個區塊對應的**行號**——就地改參數要用。
    座標行的行號一律不動（座標不改，只改參數）。"""
    blocks, head, cur, last_h, s_val = [], None, None, "", None
    head_line = tool_line = g43_line = s_line = m29_line = None

    def close():
        nonlocal cur
        if cur is not None and cur.coords:
            blocks.append(cur)
        cur = None

    for i, line in enumerate(text.splitlines()):
        hm = HEAD_RE.match(line)
        if hm:
            close()
            head = (hm.group(1), "H%s" % hm.group(2) if hm.group(2) else "", hm.group(3).strip())
            last_h = head[1]
            head_line, tool_line, g43_line, s_line, m29_line = i, None, None, None, None
            continue
        if line.lstrip().startswith("("):
            continue
        if re.match(r"\s*T\d+\s+M0?6\b", line):
            tool_line = i
        g43 = re.search(r"\bG43\s*H(\d+)", line)
        if g43:
            last_h = "H%s" % g43.group(1)
            g43_line = i
        if re.search(r"\bM29\b", line):
            m29_line = i
        sv = _num(line, "S")
        if sv is not None:
            s_val = sv
            s_line = i
        if "G80" in line:
            close()
            continue
        cm = CYCLE_RE.search(line)
        if cm:
            close()
            x, y = _num(line, "X"), _num(line, "Y")
            cur = Block(
                nc=path,
                tool_t=head[0] if head else "?",
                tool_h=(head[1] or last_h) if head else last_h,
                desc=head[2] if head else "",
                cycle=cm.group(1),
                retract="G98" if "G98" in line else ("G99" if "G99" in line else ""),
                z=_num(line, "Z"),
                r=_num(line, "R"),
                q=_num(line, "Q"),
                f=_num(line, "F"),
                s=s_val,
                coords=[(x, y)] if x is not None and y is not None else [],
                cycle_line=i,
                head_line=head_line, tool_line=tool_line,
                g43_line=g43_line, s_line=s_line, m29_line=m29_line,
            )
            continue
        if cur is not None and re.match(r"^\s*X-?[\d.]", line) and not re.search(r"\bG0?[0-3]\b", line):
            x, y = _num(line, "X"), _num(line, "Y")
            if x is not None and y is not None:
                cur.coords.append((x, y))
    close()
    return blocks


def load(path):
    with open(path, encoding="utf-8") as fh:
        return Program(path, fh.read())
