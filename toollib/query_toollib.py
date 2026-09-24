#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刀具庫 .TAB 查詢工具（cnc-drawing-to-package skill 附屬）

刀具庫格式：資料夾內一批 zip（或已解開的 .TAB），檔名 <刀種>-<材質>-<代號>.zip，
zip 內為 Big5 編碼的固定欄寬文字表（第一欄=刀徑或牙規，之後 S/F/Q/刀長…）。
TOOL4.zip 為刀號登錄表（T號 ↔ H補正 ↔ 規格）。

用法：
  query_toollib.py --lib <刀具庫路徑> list
  query_toollib.py --lib <路徑> query <刀種> <材質> <直徑>   # 例: query 鑽尾 SKD11 8.5
  query_toollib.py --lib <路徑> tap <牙規>                   # 例: tap M6
  query_toollib.py --lib <路徑> tools                        # TOOL4 刀號登錄表
  query_toollib.py --lib <路徑> dump                         # 全部輸出成 JSON

輸出一律 JSON（stdout）。查無完全相同刀徑時回最近值並附 warning，
呼叫端（gen_gcode.py / tool_list.md）必須把 warning 寫進備註。
"""
import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

DEFAULT_LIB = None  # 刀具庫路徑取自客戶 shop.yaml tool_library.path，以 --lib 傳入

# 檔名 <刀種>-<材質>-<代號>；攻牙-T1 這種只有兩段（無材質，通用）
NAME_RE = re.compile(r"^(?P<type>[^-]+)(?:-(?P<material>[A-Za-z0-9]+))?-(?P<code>[A-Za-z]+\d+)$")

def normalize_material(m):
    """表名材質正規化（庫內有 SS413 這種疑似 SS41 的變體）。"""
    if not m:
        return None
    m = m.upper()
    if m.startswith("SS41"):
        return "SS41"
    if m.startswith("SKD11"):
        return "SKD11"
    return m

def read_tab_bytes(path: Path):
    """回傳 (表名, bytes)。zip 取第一個 .TAB；裸 .TAB 直接讀。"""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.upper().endswith(".TAB")]
            if not names:
                return None
            return path.stem, z.read(names[0])
    if path.suffix.upper() == ".TAB":
        return path.stem, path.read_bytes()
    return None

TOOL_ROW_RE = re.compile(r"^(?P<tool>T\S+)\s+(?:(?P<h>H\d+)\s+)?(?P<size>\S+)\s+(?P<type>\d)\s*(?:\[\s*(?P<comment>[^\]]*)\]?)?\s*$")

def parse_tool_registry(name, lines):
    """TOOL4 刀號登錄表：T號 ↔ H補正 ↔ 規格（尾欄為 [ ... ] 註記）。"""
    rows, warnings = [], []
    for ln in lines[1:]:
        if set(ln.strip()) <= set("- "):
            continue
        m = TOOL_ROW_RE.match(ln.strip())
        if m:
            d = m.groupdict()
            d["comment"] = (d["comment"] or "").strip()
            rows.append(d)
        else:
            warnings.append(f"無法解析，略過: {ln.strip()!r}")
    return {"name": name, "type": "刀號登錄", "material": None,
            "columns": ["tool", "h", "size", "type", "comment"],
            "rows": rows, "warnings": warnings}

def parse_table(name: str, raw: bytes):
    """解析一張 .TAB 成 {name, type, material, columns, rows, warnings}。"""
    text = raw.decode("big5", errors="replace")
    text = text.replace("\x1a", "")  # DOS EOF 記號
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return None
    if lines[0].lstrip().startswith("Tool Number"):
        return parse_tool_registry(name, lines)
    header = re.split(r"\s{2,}", lines[0].strip())
    ncols_hint = len(header)
    warnings, rows = [], []

    def push_row(tokens):
        row = {}
        for i, tok in enumerate(tokens):
            key = header[i] if i < len(header) else f"extra{i}"
            try:
                row[key] = float(tok)
            except ValueError:
                row[key] = tok
        rows.append(row)

    for ln in lines[1:]:
        if set(ln.strip()) <= set("- "):  # 分隔線
            continue
        if ln.strip().startswith(header[0].split()[0]):  # 換頁重複的表頭
            continue
        tokens = ln.split()
        # 修復來源檔偶發的「兩列黏成一行」（換行遺失，如 "…2.5  5.27.0  1400…"）
        while len(tokens) > ncols_hint:
            glued = tokens[ncols_hint - 1]
            m = re.match(r"^(\d+\.)(\d+(?:\.\d+)?)$", glued)
            if m:
                push_row(tokens[: ncols_hint - 1] + [m.group(1)])
                tokens = [m.group(2)] + tokens[ncols_hint:]
            else:
                warnings.append(f"欄數異常無法解析，整行略過: {ln.strip()!r}")
                tokens = []
                break
        if tokens:
            if len(tokens) < 2:
                warnings.append(f"欄數不足，略過: {ln.strip()!r}")
            else:
                push_row(tokens)

    m = NAME_RE.match(name)
    ttype = m.group("type") if m else name
    material = normalize_material(m.group("material")) if m else None
    return {
        "name": name,
        "type": ttype,
        "material": material,
        "columns": header,
        "rows": rows,
        "warnings": warnings,
    }

def load_library(lib: Path):
    tables = {}
    for p in sorted(lib.iterdir()):
        if p.name.startswith("."):
            continue
        got = read_tab_bytes(p) if p.is_file() else None
        if not got and p.is_dir():  # 已解開的資料夾
            for q in sorted(p.glob("*.TAB")):
                got = read_tab_bytes(q)
                break
        if not got:
            continue
        t = parse_table(*got)
        if t:
            tables[t["name"]] = t
    return tables

def find_table(tables, ttype, material):
    material = normalize_material(material)
    cands = [t for t in tables.values() if t["type"] == ttype]
    if not cands:
        return None, f"刀具庫無「{ttype}」表；現有刀種: {sorted({t['type'] for t in tables.values()})}"
    exact = [t for t in cands if t["material"] == material]
    if exact:
        return exact[0], None
    no_mat = [t for t in cands if t["material"] is None]
    if no_mat:
        return no_mat[0], None  # 通用表（如攻牙-T1）
    return None, (f"「{ttype}」無材質 {material} 的表；現有材質: "
                  f"{sorted({t['material'] for t in cands})}。"
                  f"依 skill 規則就近取表並標 ASSUMED。")

def query_dia(table, dia):
    key = table["columns"][0]
    numeric = [(r, r[key]) for r in table["rows"] if isinstance(r.get(key), float)]
    if not numeric:
        return {"error": f"表 {table['name']} 第一欄非數值刀徑"}
    best = min(numeric, key=lambda rv: abs(rv[1] - dia))
    out = {"table": table["name"], "requested_dia": dia, "row": best[0]}
    if abs(best[1] - dia) > 1e-6:
        out["warning"] = (f"庫內無 Ø{dia} 完全相符，取最近 Ø{best[1]}；"
                          f"S/F 需依刀徑比例換算或標 ASSUMED 回確")
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lib", default=DEFAULT_LIB, required=DEFAULT_LIB is None,
                    help="刀具庫資料夾路徑（客戶 shop.yaml tool_library.path）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    q = sub.add_parser("query")
    q.add_argument("type"); q.add_argument("material"); q.add_argument("dia", type=float)
    tp = sub.add_parser("tap")
    tp.add_argument("spec", help="牙規，如 M6 或 M6*P1.0")
    sub.add_parser("tools")
    sub.add_parser("dump")
    args = ap.parse_args()

    lib = Path(args.lib).expanduser()
    if not lib.is_dir():
        print(json.dumps({"error": f"刀具庫路徑不存在: {lib}"}, ensure_ascii=False)); sys.exit(1)
    tables = load_library(lib)
    if not tables:
        print(json.dumps({"error": f"{lib} 內找不到任何 .TAB/.zip 刀具表"}, ensure_ascii=False)); sys.exit(1)

    if args.cmd == "list":
        out = [{"name": t["name"], "type": t["type"], "material": t["material"],
                "rows": len(t["rows"]), "columns": t["columns"],
                "warnings": t["warnings"]} for t in tables.values()]
    elif args.cmd == "query":
        table, err = find_table(tables, args.type, args.material)
        out = {"error": err} if err else query_dia(table, args.dia)
    elif args.cmd == "tap":
        table, err = find_table(tables, "攻牙", None)
        if err:
            out = {"error": err}
        else:
            key = table["columns"][0]
            spec = args.spec.upper()
            hits = [r for r in table["rows"]
                    if isinstance(r.get(key), str) and r[key].upper().startswith(spec)]
            out = ({"table": table["name"], "row": hits[0]} if hits
                   else {"error": f"攻牙表無 {args.spec}；現有: {[r[key] for r in table['rows']]}"})
    elif args.cmd == "tools":
        t = tables.get("TOOL4")
        out = t if t else {"error": "庫內無 TOOL4 刀號登錄表"}
    else:  # dump
        out = list(tables.values())
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
