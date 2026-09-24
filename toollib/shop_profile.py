#!/usr/bin/env python3
"""廠區設定檔（shop profile）載入器 — cnc-drawing-to-package skill 附屬。

廠規是資料不是規則文字：每個客戶一份 shop.yaml，住在客戶專案根目錄
（與其刀具庫同住），skill 內只有 shops/default.yaml 通用預設。

解析優先序（高→低）：
  1. 對話覆寫（--set key.path=value，開案當下使用者明講的調整）
  2. 案件內快照 <案件>/shop_profile.yaml（離線重跑用，一經快照即固定）
  3. 客戶檔：自案件資料夾向上尋找最近的 shop.yaml
  4. skill 內 shops/default.yaml

用法：
  python3 shop_profile.py resolve <案件或工作目錄> [--set machines.default.max_rpm=6000]...
      解析合併結果，輸出 JSON（含 _sources 追溯各層來源）
  python3 shop_profile.py snapshot <案件資料夾> [--set ...]
      解析並把結果寫成 <案件>/shop_profile.yaml 快照（已存在則報錯，--force 覆寫）
  python3 shop_profile.py validate <yaml檔>
      檢查單一檔案 schema（未知鍵警告、必要型別錯誤）
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：python3 -m pip install --no-cache-dir pyyaml")

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_YAML = SKILL_DIR / "shops" / "default.yaml"
SNAPSHOT_NAME = "shop_profile.yaml"
CUSTOMER_NAME = "shop.yaml"

# schema v1：鍵 → 期望型別（dict 代表往下巢狀；tuple 為可接受型別）
SCHEMA = {
    "schema": (int,),
    "name": (str,),
    "machines": {
        "*": {  # 機台代號（default 或自訂）
            "controller": (str,),
            "axes": (int,),
            "max_rpm": (int, type(None)),
            "travel": {"x": (int, float), "y": (int, float), "z": (int, float)},
            "rigid_tap": (bool,),
        }
    },
    "tool_library": {
        "path": (str, type(None)),
        "restrict_to_library": (bool,),
        "material_map": {"*": (str, dict)},
        # app 內登錄的廠內刀具清單（每筆 t/type/dia/flute_len/len/max_rpm/note）；
        # T 號與規格以此為準，S/F 仍查 .TAB 表；restrict 時「庫」= tools ∪ .TAB
        "tools": (list,),
    },
    "fixtures": {  # 夾具庫（app 維護）：G-code 安全高度避讓 clamp_height、開口檢查 max_opening
        "default": (str, type(None)),
        "items": {
            "*": {
                "type": (str,),  # vise|magnet|vacuum|plate|chuck|custom
                "clamp_height": (int, float),
                "max_opening": (int, float),
                "jaw_width": (int, float),
                "note": (str,),
            }
        },
    },
    "workholding": {
        "origin_strategies": (list,),
        "default_origin": (str,),
        "leveling": (str,),
    },
    "process": {
        "rough_finish_split": (bool,),
        "rough_wall_allowance": (int, float),
        "grind_allowance_per_face": (int, float),
        "tight_tol_hole": (str,),
    },
    "input": {"drawing_preference": (list,)},
    "confidentiality": {"nda": (bool,), "anonymize": (bool,)},
    "examples": (list,),  # 該客戶已完成案例（路徑），開案先查沿用判讀
    "notes": (str,),
}


def deep_merge(base, over):
    """over 疊在 base 上（dict 遞迴、其餘覆蓋）。"""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(base[k], v) if k in base else v
    return out


def validate(data, schema=SCHEMA, path=""):
    """回傳警告清單（不中斷）：未知鍵、型別不符。"""
    warns = []
    if not isinstance(data, dict):
        return [f"{path or '(root)'}: 應為對映（mapping），得到 {type(data).__name__}"]
    for key, val in data.items():
        spec = schema.get(key, schema.get("*"))
        here = f"{path}.{key}" if path else key
        if spec is None:
            warns.append(f"未知鍵（忽略不中斷）: {here}")
        elif isinstance(spec, dict):
            warns += validate(val, spec, here)
        elif not isinstance(val, spec):
            names = "/".join(t.__name__ for t in spec)
            warns.append(f"型別不符: {here} 應為 {names}，得到 {type(val).__name__}")
    return warns


def find_customer_yaml(start: Path):
    """自 start 向上尋找最近的 shop.yaml（不進入家目錄之上）。"""
    cur = start.resolve()
    home = Path.home().resolve()
    while True:
        cand = cur / CUSTOMER_NAME
        if cand.is_file():
            return cand
        if cur == cur.parent or cur == home.parent:
            return None
        cur = cur.parent


def load_yaml(p: Path):
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def apply_sets(profile, sets):
    for expr in sets:
        if "=" not in expr:
            sys.exit(f"--set 格式錯誤（key.path=value）: {expr}")
        keypath, raw = expr.split("=", 1)
        try:
            val = yaml.safe_load(raw)
        except yaml.YAMLError:
            val = raw
        node = profile
        keys = keypath.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = val
    return profile


def resolve(start: Path, sets):
    sources = []
    profile = load_yaml(DEFAULT_YAML)
    sources.append(str(DEFAULT_YAML))

    snap = start / SNAPSHOT_NAME
    if snap.is_file():  # 已快照的案件：以快照為準（不再讀客戶檔）
        profile = deep_merge(profile, load_yaml(snap))
        sources.append(str(snap) + "（案件快照）")
    else:
        cust = find_customer_yaml(start)
        if cust:
            profile = deep_merge(profile, load_yaml(cust))
            sources.append(str(cust) + "（客戶檔）")
        else:
            sources.append("（找不到客戶 shop.yaml——用通用預設，建議先做新客戶問答建檔）")

    if sets:
        profile = apply_sets(profile, list(sets))
        sources.append(f"（對話覆寫 --set ×{len(sets)}）")

    warns = validate(profile)
    profile["_sources"] = sources
    if warns:
        profile["_warnings"] = warns
    return profile


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["resolve", "snapshot", "validate"])
    ap.add_argument("target", help="案件/工作目錄（resolve/snapshot）或 yaml 檔（validate）")
    ap.add_argument("--set", action="append", default=[], help="對話覆寫，如 machines.default.max_rpm=6000")
    ap.add_argument("--force", action="store_true", help="snapshot 已存在時覆寫")
    a = ap.parse_args()
    target = Path(a.target)

    if a.cmd == "validate":
        warns = validate(load_yaml(target))
        print(json.dumps({"file": str(target), "warnings": warns, "ok": not warns}, ensure_ascii=False, indent=1))
        return

    if not target.is_dir():
        sys.exit(f"目錄不存在: {target}")
    profile = resolve(target, a.set)

    if a.cmd == "resolve":
        print(json.dumps(profile, ensure_ascii=False, indent=1))
        return

    # snapshot
    snap = target / SNAPSHOT_NAME
    if snap.exists() and not a.force:
        sys.exit(f"快照已存在（用 --force 覆寫）: {snap}")
    clean = {k: v for k, v in profile.items() if not k.startswith("_")}
    with open(snap, "w", encoding="utf-8") as f:
        f.write("# 開案快照——本案件所有 generator 只讀此檔（離線可重跑）。\n")
        f.write("# 要套用新廠規：更新客戶 shop.yaml 後重跑 snapshot --force 並重跑管線。\n")
        yaml.safe_dump(clean, f, allow_unicode=True, sort_keys=False)
    print(f"已快照 → {snap}")
    for w in profile.get("_warnings", []):
        print(f"⚠ {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
