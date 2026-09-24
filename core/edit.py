# -*- coding: utf-8 -*-
"""就地改參數：座標一律不動，只改刀具與切削參數。

依據師傅實務（影片 06:48）：
  「我們程式人就會拿九點八的刀子，然後用手動去改成 BF（精搪），
    **然後座標不改，只要改它的參數而已**」

為什麼不重跑生成器：現有案件的 gen_gcode.py 是各案手寫的，沒有 hole_plan.json 契約
（見 gcode-core change）。在契約落地前，就地改寫該循環區塊的參數行是唯一
既能用又不違反「座標不改」原則的路徑。

代價（必須讓使用者知道）：改過的 .nc 會與該案自己的 gen_gcode.py 不同步——
重跑生成器不會得到同樣結果。故一律寫 EDITED 標記並強制重跑稽核。
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ncparse  # noqa: E402

MARK = "gcode/.edited.json"


def _set_word(line, letter, value):
    """替換一行裡的 X/Z/R/Q/F/S 等字碼值；沒有就不動。"""
    if value is None:
        return line
    txt = ("%g" % value) if isinstance(value, (int, float)) else str(value)
    pat = re.compile(r"(?<![A-Za-z])%s-?[\d.]+" % letter)
    return pat.sub("%s%s" % (letter, txt), line, count=1) if pat.search(line) else line


def _backup(gdir):
    """改寫前備份整個 gcode/ 現況，回傳備份序號。"""
    bdir = os.path.join(gdir, ".backup")
    os.makedirs(bdir, exist_ok=True)
    n = 1 + max([int(x) for x in os.listdir(bdir) if x.isdigit()] or [0])
    dst = os.path.join(bdir, str(n))
    os.makedirs(dst)
    for f in os.listdir(gdir):
        if f.startswith("."):
            continue
        src = os.path.join(gdir, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dst, f))
    return n


def plan_edits(case_dir, edits):
    """試算：回傳每筆編輯將改動哪一行、改成什麼（不寫檔）。

    edits: [{nc, cycleLine, t, h, spec, z, r, q, s, f}]
    """
    gdir = os.path.join(case_dir, "gcode")
    out = []
    byfile = {}
    for e in edits:
        byfile.setdefault(e["nc"], []).append(e)
    for rel, items in byfile.items():
        path = os.path.join(case_dir, rel)
        if not os.path.isfile(path):
            out.append({"nc": rel, "error": "找不到檔案"})
            continue
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        prog = ncparse.load(path)
        idx = {b.cycle_line: b for b in prog.blocks}
        for e in items:
            b = idx.get(e.get("cycleLine"))
            if b is None:
                out.append({"nc": rel, "error": "循環行 %s 不在解析結果內" % e.get("cycleLine")})
                continue
            chg = []
            # 循環行：Z / R / Q / F
            new_cycle = lines[b.cycle_line]
            for letter, key in (("Z", "z"), ("R", "r"), ("Q", "q"), ("F", "f")):
                if e.get(key) is not None:
                    before = new_cycle
                    new_cycle = _set_word(new_cycle, letter, e[key])
                    if before != new_cycle:
                        chg.append({"line": b.cycle_line + 1, "before": before, "after": new_cycle})
            # 轉速：S 行（攻牙另有 M29 S）
            for ln in (b.s_line, b.m29_line):
                if e.get("s") is not None and ln is not None:
                    before = lines[ln]
                    after = _set_word(before, "S", e["s"])
                    if before != after:
                        chg.append({"line": ln + 1, "before": before, "after": after})
            # 換刀：標頭／T 呼叫／G43 H
            if e.get("t") and b.tool_line is not None:
                before = lines[b.tool_line]
                after = re.sub(r"^(\s*)T\d+", r"\g<1>%s" % e["t"], before)
                if before != after:
                    chg.append({"line": b.tool_line + 1, "before": before, "after": after})
            if e.get("h") and b.g43_line is not None:
                before = lines[b.g43_line]
                after = re.sub(r"(G43\s*H)\d+", r"\g<1>%s" % str(e["h"]).lstrip("Hh"), before)
                if before != after:
                    chg.append({"line": b.g43_line + 1, "before": before, "after": after})
            if (e.get("t") or e.get("h") or e.get("spec")) and b.head_line is not None:
                before = lines[b.head_line]
                after = before
                if e.get("t"):
                    after = re.sub(r"(\(-{2,}\s*)T\d+", r"\g<1>%s" % e["t"], after)
                if e.get("h"):
                    after = re.sub(r"(T\d+\s+)H\d+", r"\g<1>H%s" % str(e["h"]).lstrip("Hh").zfill(2), after)
                if e.get("spec"):
                    after = re.sub(r"(\(-{2,}\s*T\d+\s+(?:H\d+\s+)?).*?(\s*-{2,}\))",
                                   lambda m: m.group(1) + e["spec"] + m.group(2), after)
                if before != after:
                    chg.append({"line": b.head_line + 1, "before": before, "after": after})
            out.append({"nc": rel, "cycleLine": b.cycle_line,  # 0-based，與輸入同基準
                        "tool": "%s %s" % (b.tool_t, b.tool_h), "desc": b.desc[:40],
                        "changes": chg})
    return out


def apply_edits(case_dir, edits, note="", expect=None):
    """實際寫入。座標行永不改動。

    expect：使用者在 UI 上**看到的那份預覽**。有給就以它為準比對——
    防的是「預覽之後檔案被別人改掉，套用的結果跟他看到的不一樣」。
    重新試算一次是防不住這件事的（重算會貼合當下內容，永遠對得上）。
    """
    preview = expect if expect else plan_edits(case_dir, edits)
    errs = [p for p in preview if p.get("error")]
    if errs:
        return {"ok": False, "reason": "；".join(p["error"] for p in errs)}
    gdir = os.path.join(case_dir, "gcode")
    backup = _backup(gdir)

    byfile = {}
    for p in preview:
        for c in p.get("changes", []):
            byfile.setdefault(p["nc"], []).append(c)

    changed = 0
    for rel, chgs in byfile.items():
        path = os.path.join(case_dir, rel)
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        for c in chgs:
            i = c["line"] - 1
            if lines[i] != c["before"]:
                return {"ok": False, "reason": "檔案已變動，請重新載入後再試（%s 第 %d 行）" % (rel, c["line"])}
            lines[i] = c["after"]
            changed += 1
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    # 標記：這個案子的 .nc 已被手動改過，與其 gen_gcode.py 不同步
    mark = os.path.join(case_dir, MARK)
    hist = []
    if os.path.isfile(mark):
        try:
            hist = json.load(open(mark, encoding="utf-8")).get("history", [])
        except Exception:
            hist = []
    hist.append({"backup": backup, "changed": changed, "note": note,
                 "files": sorted(byfile.keys())})
    with open(mark, "w", encoding="utf-8") as fh:
        json.dump({"edited": True,
                   "warning": "本案 .nc 已就地改參數，與 gen_gcode.py 不同步——"
                              "重跑生成器不會得到同樣結果。座標未被改動。",
                   "history": hist}, fh, ensure_ascii=False, indent=2)
    return {"ok": True, "backup": backup, "files": sorted(byfile.keys()), "changed": changed}


def restore(case_dir, backup_no):
    gdir = os.path.join(case_dir, "gcode")
    src = os.path.join(gdir, ".backup", str(backup_no))
    if not os.path.isdir(src):
        return {"ok": False, "reason": "找不到備份 %s" % backup_no}
    for f in os.listdir(src):
        shutil.copy2(os.path.join(src, f), os.path.join(gdir, f))
    return {"ok": True, "restored": backup_no}


if __name__ == "__main__":
    case, payload = sys.argv[1], json.loads(sys.stdin.read())
    act = payload.get("action", "plan")
    if act == "plan":
        print(json.dumps(plan_edits(case, payload["edits"]), ensure_ascii=False))
    elif act == "apply":
        print(json.dumps(apply_edits(case, payload["edits"], payload.get("note", "")), ensure_ascii=False))
    elif act == "restore":
        print(json.dumps(restore(case, payload["backup"]), ensure_ascii=False))
