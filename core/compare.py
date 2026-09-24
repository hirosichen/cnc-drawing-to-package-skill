# -*- coding: utf-8 -*-
"""基準比對：拿廠內人工撰寫的程式當基準，比對 AI 產出。

為什麼需要（design D5）：AI 自己的舊產出不是正確性基準——那些 .nc 從未上機、
也未經客戶實際審閱。**唯一真正的外部真相是廠內人工程式**（影片 28:43 師傅：
「你們實際跑出來的是真正正確的」）。

比對的不是逐字元——人工與生成的寫法必然不同（排版、註解、刀序安排）。
比的是**語意五維度**：孔群／工序鏈／深度／切削條件／循環選型。

判讀原則：差異一律列出、分三類，**不預設任一方為對**——但基準是唯一上過機的那份，
舉證責任在產出這邊。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ncparse  # noqa: E402

# 差異分類
AI_WRONG = "產出有誤"
BASE_VS_RULE = "基準與廠規不符"
CONVENTION = "慣例差異"
UNKNOWN = "待判讀"


class Diff:
    def __init__(self, dim, kind, where, base, made, note=""):
        self.dim, self.kind, self.where, self.base, self.made, self.note = dim, kind, where, base, made, note

    def __repr__(self):
        return "[%s] %s %s：基準=%s ／ 產出=%s%s" % (
            self.dim, self.kind, self.where, self.base, self.made,
            "（%s）" % self.note if self.note else "")


def _key(coords):
    return tuple(sorted(set(coords)))


def hole_groups(prog):
    """以座標集合為身分聚孔群（與 app 端反推器同一套認定）。"""
    blocks = [b for b in prog.blocks if b.coords]
    sets = [set(b.coords) for b in blocks]
    groups = {}
    for i, s in enumerate(sets):
        # 最小集才算孔群；超集（中心鑽、倒角刀）是共用工步
        if any(j != i and len(o) < len(s) and o <= s for j, o in enumerate(sets)):
            continue
        groups.setdefault(_key(blocks[i].coords), [])
    for k in groups:
        ks = set(k)
        groups[k] = [b for b in blocks if ks <= set(b.coords)]
    return groups


def _tool_chain(blocks):
    return [b.tool_t for b in blocks]


def _cut(b):
    return (b.s, b.f, b.q)


def compare_programs(base, made):
    """比對兩支 .nc（同一工序）。回傳 Diff 清單。"""
    diffs = []
    gb, gm = hole_groups(base), hole_groups(made)

    # --- 維度一：孔群 ---
    only_b = set(gb) - set(gm)
    only_m = set(gm) - set(gb)
    for k in sorted(only_b):
        diffs.append(Diff("孔群", AI_WRONG, "%d 孔 @%s" % (len(k), k[0]),
                          "有（%s）" % gb[k][-1].desc[:24], "無",
                          "基準有這群孔、產出沒有——優先懷疑判圖漏了"))
    for k in sorted(only_m):
        diffs.append(Diff("孔群", UNKNOWN, "%d 孔 @%s" % (len(k), k[0]),
                          "無", "有（%s）" % gm[k][-1].desc[:24],
                          "產出多出這群孔——可能是判圖多讀，也可能基準漏做"))

    # --- 共有孔群逐維度比 ---
    for k in sorted(set(gb) & set(gm)):
        bb, mm = gb[k], gm[k]
        where = "%d 孔 @%s" % (len(k), k[0])

        cb, cm = _tool_chain(bb), _tool_chain(mm)
        if cb != cm:
            # 同一組刀只是順序不同＝排刀慣例；刀組本身不同＝少做或多做了工步，不能算慣例
            same_set = sorted(cb) == sorted(cm)
            missing = [t for t in cb if t not in cm]
            diffs.append(Diff(
                "工序鏈", CONVENTION if same_set else (AI_WRONG if missing else UNKNOWN),
                where, "→".join(cb), "→".join(cm),
                "刀序不同，刀組相同——排刀慣例差異" if same_set
                else ("產出少了 %s ← 工步漏做？" % "／".join(missing) if missing
                      else "產出多出工步——需判讀"),
            ))

        for i in range(min(len(bb), len(mm))):
            b, m = bb[i], mm[i]
            if b.z is not None and m.z is not None and abs(b.z - m.z) > 0.001:
                diffs.append(Diff("深度", AI_WRONG, "%s／%s" % (where, b.desc[:18]),
                                  b.z, m.z, "深度不同——差值能否由廠規解釋？"))
            if b.cycle != m.cycle:
                diffs.append(Diff("循環選型", UNKNOWN, "%s／%s" % (where, b.desc[:18]),
                                  b.cycle, m.cycle, "固定循環不同（排屑策略）"))
            if _cut(b) != _cut(m):
                diffs.append(Diff("切削條件", CONVENTION, "%s／%s" % (where, b.desc[:18]),
                                  "S%s F%s Q%s" % _cut(b), "S%s F%s Q%s" % _cut(m),
                                  "S/F/Q 不同——基準若取自刀具庫，產出應對齊"))
    return diffs


def compare_cases(base_dir, made_dir):
    """以 OP 配對兩個案件資料夾內的 .nc。"""
    def ncs(d):
        g = os.path.join(d, "gcode")
        base = g if os.path.isdir(g) else d
        out = {}
        for n in sorted(os.listdir(base)):
            if n.lower().endswith(".nc"):
                p = ncparse.load(os.path.join(base, n))
                out[p.op or n] = p
        return out

    B, M = ncs(base_dir), ncs(made_dir)
    all_diffs, report = [], []
    for op in sorted(set(B) | set(M)):
        if op not in M:
            report.append(("缺工序", op, "基準有、產出無"))
            continue
        if op not in B:
            report.append(("多工序", op, "產出有、基準無"))
            continue
        d = compare_programs(B[op], M[op])
        all_diffs += [(op, x) for x in d]
    return all_diffs, report


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) != 2:
        print("用法：python3 compare.py <基準案件或.nc> <產出案件或.nc>")
        sys.exit(2)
    diffs, report = compare_cases(args[0], args[1])
    for kind, op, note in report:
        print("⚠ %s %s：%s" % (kind, op, note))
    if not diffs:
        print("✅ 五維度（孔群／工序鏈／深度／切削條件／循環選型）無差異")
    else:
        by_kind = {}
        for op, d in diffs:
            by_kind.setdefault(d.kind, []).append((op, d))
        print("差異 %d 項：" % len(diffs))
        for kind in (AI_WRONG, BASE_VS_RULE, UNKNOWN, CONVENTION):
            items = by_kind.get(kind, [])
            if not items:
                continue
            print("\n── %s（%d）" % (kind, len(items)))
            for op, d in items[:30]:
                print("   %s %s" % (op, d))
    print("\n判讀原則：不預設任一方為對——但基準是唯一上過機的那份，舉證責任在產出這邊。")
