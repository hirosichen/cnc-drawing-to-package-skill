# -*- coding: utf-8 -*-
"""廠規公式斷言——正確性的來源。

每條規則都出自本廠知識庫既有的、有出處的結論（見 source 欄），並且**可以獨立對任何
一份既有 .nc 執行**，不需要那個案子改用核心。

重要：這些斷言的存在理由是「既有 .nc 從未上機、也未經客戶實際審閱」——
它們不是「已知正確」，只是 AI 上次產出的東西。所以正確性不能靠比對舊產出，
只能靠拿廠規去查。
"""
import re

PASS, FAIL, WARN, NA = "PASS", "FAIL", "WARN", "NA"

# 平底刀：捨棄式高速鑽（HD）、U 鑽、平頭鑽（F 系）——無鑽尖，貫穿量走「通過長」欄
FLAT_BOTTOM_RE = re.compile(r"高速鑽|U鑽|捨棄式|平頭鑽|\bHD\d|\bF\d{2}\b")


class Finding:
    def __init__(self, rule, status, where, detail):
        self.rule, self.status, self.where, self.detail = rule, status, where, detail

    def __repr__(self):
        return "[%s] %s %s — %s" % (self.status, self.rule, self.where, self.detail)


def _where(prog, b):
    return "%s %s %s %s" % (prog.op or prog.path, b.tool_t, b.tool_h, b.desc[:34])


# ---------------------------------------------------------------- R1 剛性攻牙
def r_rigid_tap(prog, cfg):
    """F = S × P。不等就是程式錯了。

    出處：知識庫〈孔加工刀序與程式碼〉七節（影片刀具表 M8×P1.25 S318/F397.5 實證）。
    """
    out = []
    for b in prog.blocks:
        if b.cycle not in ("G84", "G74"):
            continue
        th = b.thread
        if not th or b.s is None or b.f is None:
            out.append(Finding("R1 剛性攻牙 F=S×P", NA, _where(prog, b), "缺螺距或 S/F，無法檢核"))
            continue
        pitch = th[1]
        want = b.s * pitch
        ok = abs(want - b.f) < 0.51  # NC 進給常取整
        out.append(Finding(
            "R1 剛性攻牙 F=S×P", PASS if ok else FAIL, _where(prog, b),
            "S%g × P%g = %g，程式 F%g%s" % (b.s, pitch, want, b.f, "" if ok else " ← 不符"),
        ))
    return out


# ---------------------------------------------------------------- R2 公制底孔
def r_tap_drill(prog, cfg):
    """底孔 ≈ 大徑 − 螺距（嚙合率約 75%）。

    出處：知識庫〈孔加工深度計算〉六節。
    比對方式：找座標集合與攻牙工步相同、且非倒角非中心鑽的鑽孔工步。
    """
    out = []
    taps = [b for b in prog.blocks if b.cycle in ("G84", "G74")]
    for t in taps:
        th = t.thread
        if not th:
            continue
        major, pitch = th
        key = set(t.coords)
        drills = [b for b in prog.blocks
                  if b is not t and not b.is_chamfer and not b.is_spot
                  and b.cycle not in ("G84", "G74") and set(b.coords) == key and b.dia]
        if not drills:
            out.append(Finding("R2 公制底孔≈大徑−螺距", NA, _where(prog, t), "找不到同孔位的底孔工步"))
            continue
        d = drills[-1].dia
        want = major - pitch
        # 標準鑽頭會就近取，容許 ±0.35（如 M8 6.75→Ø6.8、M16 14.0→Ø14）
        ok = abs(d - want) <= 0.35
        out.append(Finding(
            "R2 公制底孔≈大徑−螺距", PASS if ok else FAIL, _where(prog, t),
            "M%g×P%g → 應 Ø%.2f，程式用 Ø%g%s" % (major, pitch, want, d, "" if ok else " ← 偏離"),
        ))
    return out


# ---------------------------------------------------------------- R3 循環選型
def r_cycle_by_ld(prog, cfg):
    """L/D < 3 → G81；3~5 → G73；> 5 → G83（＋高壓內冷）。

    出處：知識庫〈孔加工刀序與程式碼〉五節。
    只對「造孔」工步檢核（排除中心鑽、倒角、攻牙、鉸孔）。
    """
    out = []
    for b in prog.blocks:
        if b.is_spot or b.is_chamfer or b.cycle in ("G84", "G74", "G85", "G86", "G89"):
            continue
        d, z = b.dia, b.z
        if not d or z is None or d <= 0:
            continue
        ld = abs(z) / d
        if ld < 3:
            want = ("G81", "G82", "G73", "G83")
        elif ld <= 5:
            want = ("G73", "G83")
        else:
            want = ("G83",)
        ok = b.cycle in want
        out.append(Finding(
            "R3 循環選型 L/D", PASS if ok else FAIL, _where(prog, b),
            "Ø%g 深%g → L/D=%.1f 應用 %s，程式用 %s%s"
            % (d, abs(z), ld, "／".join(want), b.cycle, "" if ok else " ← 不符"),
        ))
    return out


# ---------------------------------------------------------------- R4 盲孔殘餘壁
def r_residual_wall(prog, cfg):
    """殘餘壁厚 = 板厚 − 程式 Z；小刀留 1.0、大刀留 1.5。

    出處：知識庫〈孔加工深度計算〉三節（影片 04:15 師傅原話）。
    只檢「盲孔」——描述含『貫穿/通孔』或深度已超過板厚者視為貫穿，跳過。
    """
    out = []
    thk, why = prog.depth_budget
    if not thk:
        return [Finding("R4 盲孔殘餘壁厚", NA, prog.op or prog.path, why)]
    small, large, split = cfg["residual_small"], cfg["residual_large"], cfg["residual_split_dia"]
    for b in prog.blocks:
        if b.is_spot or b.is_chamfer or b.z is None:
            continue
        depth = abs(b.z)
        if "貫穿" in b.desc or "通孔" in b.desc or depth >= thk:
            continue  # 貫穿孔不適用
        d = b.dia or (b.thread[0] if b.thread else None)
        if not d:
            continue
        need = small if d < split else large
        rest = thk - depth
        ok = rest >= need - 1e-6
        out.append(Finding(
            "R4 盲孔殘餘壁厚", PASS if ok else FAIL, _where(prog, b),
            "板厚%g − 深%g = 殘餘%.2f，Ø%g 需 ≥%.1f%s"
            % (thk, depth, rest, d, need, "" if ok else " ← 不足，背面可能鼓破"),
        ))
    return out


# ---------------------------------------------------------------- R5 轉速上限
def r_max_rpm(prog, cfg):
    """S 不得超過機台上限（本廠 shop.yaml 硬上限 4800）。"""
    cap = cfg["max_rpm"]
    out = []
    for b in prog.blocks:
        if b.s is None:
            continue
        ok = b.s <= cap
        if not ok:
            out.append(Finding("R5 轉速上限", FAIL, _where(prog, b), "S%g > 上限 %g" % (b.s, cap)))
    if not out:
        out.append(Finding("R5 轉速上限", PASS, prog.op or prog.path, "全數 ≤ %g" % cap))
    return out


# ---------------------------------------------------------------- R6 鑽尖補償
def r_drill_point(prog, cfg):
    """118° 鑽尖 Lp = 0.300 D——盲孔的程式 Z 應含這一段。

    出處：知識庫〈孔加工深度計算〉一、二節。
    ⚠待澄清 #13：本廠「盲孔程式自動加 2」究竟是固定 2mm 還是隨刀徑 0.3D 未定案；
    未回確前本規則只**報告**每支鑽頭的 Lp 供人核對，不判 FAIL。
    """
    out = []
    for b in prog.blocks:
        if b.is_spot or b.is_chamfer or b.cycle in ("G84", "G74", "G85", "G86", "G89"):
            continue
        d, z = b.dia, b.z
        if not d or z is None:
            continue
        if "貫穿" in b.desc or "通孔" in b.desc:
            continue
        lp = cfg["drill_point_ratio"] * d
        out.append(Finding(
            "R6 鑽尖補償 0.3D（待澄清#13，僅報告）", WARN, _where(prog, b),
            "Ø%g 的 118° 鑽尖 Lp=%.2f；程式 Z=%g → 全徑深約 %.2f" % (d, lp, z, abs(z) - lp),
        ))
    return out


# ---------------------------------------------------------------- R7 剛攻前置
def r_m29_before_g84(prog, cfg):
    """FANUC 剛性攻牙：G84 之前必須有 M29 S<rpm>。

    出處：shop_profile controller=fanuc-0i-mf（G84 剛性攻牙 M29）；三案實作一致。
    缺 M29＝跑成非剛攻（靠彈簧筒夾補償），同步不保證 → 牙型爛、絲攻易斷。
    """
    out = []
    lines = prog.text.splitlines()
    last_m29 = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("("):
            continue
        if re.search(r"\bM29\b", line):
            last_m29 = i
        if re.search(r"\bG84\b", line):
            # M29 必須在同一支刀內、且在這行之前（換刀會重置：G43 之後才算數）
            ok = last_m29 is not None and last_m29 < i
            out.append(Finding(
                "R7 剛攻前置 M29", PASS if ok else FAIL,
                "%s 第 %d 行" % (prog.op or prog.path, i + 1),
                ("M29 於第 %d 行，G84 於第 %d 行" % (last_m29 + 1, i + 1)) if ok
                else "G84 之前找不到 M29 ← 會跑成非剛性攻牙，牙型不保證、絲攻易斷",
            ))
    return out


# ---------------------------------------------------------------- R8 貫穿深度
def r_through_depth(prog, cfg):
    """貫穿孔：程式 Z 必須讓**全徑**穿出底面，即 |Z| ≥ 板厚 + 鑽尖 0.3D。

    出處：知識庫〈孔加工深度計算〉一、二節（Z 值指鑽尖尖點，全徑段到錐體起點為止）。
    只鑽到剛好板厚＝底面只被鑽尖戳穿，孔口沒開全徑，會留下毛邊與未切透的環。
    """
    out = []
    thk, why = prog.depth_budget
    if not thk:
        return []  # 深度預算判不出來就不猜（R4 已就同一原因報 NA）
    for b in prog.blocks:
        if b.is_spot or b.is_chamfer or b.cycle in ("G84", "G74", "G85", "G86", "G89"):
            continue
        if "貫穿" not in b.desc and "通孔" not in b.desc:
            continue
        d, z = b.dia, b.z
        if not d or z is None:
            continue
        # 平底刀（捨棄式高速鑽／U鑽／平頭鑽）沒有 118° 鑽尖——它們的貫穿超越量走刀具庫
        # 的「通過長」欄，不是 0.3D。拿麻花鑽的幾何去套會誤判。
        if FLAT_BOTTOM_RE.search(b.desc):
            out.append(Finding(
                "R8 貫穿深度含鑽尖", NA, _where(prog, b),
                "平底刀（高速鑽／U鑽／平頭鑽）無 118° 鑽尖，貫穿量取刀具庫「通過長」欄——本規則不適用",
            ))
            continue
        # 複合標頭（一支刀底下多種用途，如「沉頭貫穿x10 + 銷逃孔15.15x4 + 預鑽x2」）：
        # 無法把「貫穿」歸給這個循環區塊——寧可判不出，也不要誤判。
        if "+" in b.desc:
            out.append(Finding(
                "R8 貫穿深度含鑽尖", NA, _where(prog, b),
                "此刀標頭含多種用途（%s），無法判定本循環是否為貫穿孔——需 hole_plan 才能分辨"
                % b.desc[:40],
            ))
            continue
        need = thk + cfg["drill_point_ratio"] * d
        ok = abs(z) >= need - 1e-6
        out.append(Finding(
            "R8 貫穿深度含鑽尖", PASS if ok else FAIL, _where(prog, b),
            "板厚%g + 鑽尖%.2f (0.3×Ø%g) = 需 ≥%.2f，程式 %g%s"
            % (thk, cfg["drill_point_ratio"] * d, d, need, abs(z), "" if ok else " ← 全徑未穿出"),
        ))
    return out


# ---------------------------------------------------------------- R9 鉸孔時機
def r_ream_after_grinding(prog, cfg):
    """固定銷鉸孔必須在研磨之後——這是本廠鐵則，不是偏好。

    出處：知識庫〈固定銷符號〉工序鐵則、〈導柱導套搪孔工法〉二次加工節
    （研磨後才鉸；研磨前鉸完，研磨會把位置與孔徑一起帶走）。
    檢核方式：程式含鉸孔循環（G85/G86/G89）時，檔頭必須表明本工序在研磨之後。
    """
    reams = [b for b in prog.blocks if b.cycle in ("G85", "G86", "G89")]
    if not reams:
        return []
    head = "\n".join(prog.text.splitlines()[:8])
    ok = bool(re.search(r"研磨後|研磨完成|研磨之後", head))
    where = "%s（%d 個鉸孔工步）" % (prog.op or prog.path, len(reams))
    return [Finding(
        "R9 鉸孔在研磨之後", PASS if ok else FAIL, where,
        "檔頭已標明研磨後基準" if ok
        else "檔頭未表明本工序在研磨之後 ← 研磨前鉸孔，位置與孔徑會被研磨帶走",
    )]


# ---------------------------------------------------------------- R10 M0 換刀
def r_m0_for_variable_tools(prog, cfg):
    """非固定刀（T1 高速鑽站／T2 絲攻站／倉外 T100 類）呼叫進主軸後必須 M0 停機。

    出處：知識庫〈刀具表與刀倉配置〉M0 換刀鐵則（凌鉦 2026-07-25 07:11 定案）——
    「T3~T22 固定刀直接呼叫；其餘刀號呼叫進主軸後都要 M0 暫停→手動換刀→
      輸入刀長補正值→才能繼續加工」。
    沒有 M0＝主軸裡是上一把刀或空的就直接下刀。

    注意：本規則 2026-07-25 才定案，早於此日交付的案件會判 FAIL——那不是當時寫錯，
    而是廠規更新後舊案沒有跟著對。這正是本規則要暴露的東西。
    """
    lo, hi = cfg["fixed_tool_range"]
    lines = prog.text.splitlines()
    calls = [(i, int(m.group(1))) for i, ln in enumerate(lines)
             if (m := re.match(r"\s*T(\d+)\s+M0?6\b", ln))]
    out = []
    for idx, (i, t) in enumerate(calls):
        if lo <= t <= hi:
            continue  # 固定刀直接呼叫
        end = calls[idx + 1][0] if idx + 1 < len(calls) else len(lines)
        # M0 依廠內慣例放在**換刀點**——通常緊接在 T 呼叫之前（換完再啟動），
        # 也可能在呼叫之後、切削之前。窗口需涵蓋兩側，否則會誤判。
        first_cut = next((j for j, ln in enumerate(lines[i:end])
                          if re.search(r"\bG8[1-9]\b|\bG0?1\b", ln)), end - i)
        seg = lines[max(0, i - 12):i + first_cut]
        has_m0 = any(re.search(r"\bM0?0\b", ln) and not ln.lstrip().startswith("(")
                     for ln in seg)
        out.append(Finding(
            "R10 非固定刀 M0 換刀", PASS if has_m0 else FAIL,
            "%s 第 %d 行 T%d" % (prog.op or prog.path, i + 1, t),
            "切削前有 M0 停機" if has_m0
            else "T%d 非 T%d~T%d 固定刀，進主軸後切削前無 M0 ← 主軸裡可能不是這把刀"
                 % (t, lo, hi),
        ))
    return out


ALL_RULES = [r_rigid_tap, r_tap_drill, r_cycle_by_ld, r_residual_wall,
             r_max_rpm, r_drill_point, r_m29_before_g84, r_through_depth,
             r_ream_after_grinding, r_m0_for_variable_tools]

DEFAULT_CFG = {
    "max_rpm": 4800,             # shop.yaml 硬上限（知識庫：機台特性）
    "residual_small": 1.0,       # 知識庫：孔加工深度計算 三節
    "residual_large": 1.5,
    "residual_split_dia": 12.0,  # 小刀/大刀分界（暫定，待廠內確認）
    "fixed_tool_range": (3, 22),  # T3~T22 固定刀（知識庫：刀具表與刀倉配置）
    "drill_point_ratio": 0.300,  # 118°（知識庫：孔加工深度計算 二節）
}


def audit(prog, cfg=None, rules=None):
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    out = []
    for fn in (rules or ALL_RULES):
        out.extend(fn(prog, cfg))
    return out
