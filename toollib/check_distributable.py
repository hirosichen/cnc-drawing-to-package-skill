#!/usr/bin/env python3
"""交付衛生檢查 — skill 打包給新客戶前必跑，全過才能交付。

規則：
  1. skill 本體（除 local/ 與 openspec/ 之外）不得含絕對使用者路徑（/Users/、/home/）。
  2. shops/ 只允許 default.yaml 與 example.yaml。
  3. 不得含客戶識別字串——內建通用規則＋local/blocklist.txt（每行一個關鍵字，
     本檔不隨包交付，客戶名單寫在這裡）。
  4. local/ 與 openspec/ 屬本機/規劃資料：打包時整個排除（本工具只提醒，不掃描其內容）。

用法：python3 check_distributable.py [--skill-dir 路徑]
結束碼：0=可交付；1=有違規（逐條列出）。
"""
import argparse
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {"local", "openspec", "__pycache__", ".git"}
ALLOWED_SHOPS = {"default.yaml", "example.yaml"}
TEXT_EXT = {".md", ".py", ".yaml", ".yml", ".js", ".html", ".json", ".txt"}
PATH_RE = re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skill-dir", default=str(SKILL_DIR))
    a = ap.parse_args()
    root = Path(a.skill_dir).resolve()

    blocklist = []
    bl_file = root / "local" / "blocklist.txt"
    if bl_file.is_file():
        blocklist = [l.strip() for l in bl_file.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.startswith("#")]

    violations = []

    shops = root / "shops"
    if shops.is_dir():
        extra = {p.name for p in shops.iterdir() if p.is_file()} - ALLOWED_SHOPS
        for name in sorted(extra):
            violations.append(f"shops/{name}: 客戶檔不得放在 skill 內（應在客戶專案根目錄）")

    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts) or not p.is_file():
            continue
        if p.suffix.lower() not in TEXT_EXT:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = PATH_RE.search(line)
            if m:
                violations.append(f"{rel}:{i}: 絕對使用者路徑 {m.group(0)}")
            for kw in blocklist:
                if kw.lower() in line.lower():
                    violations.append(f"{rel}:{i}: 客戶識別字串「{kw}」")

    if (root / "local").is_dir():
        print("ℹ local/ 存在（本機備忘）——打包時整個排除，不隨 skill 交付。")
    if (root / "openspec").is_dir():
        print("ℹ openspec/ 存在（skill 自身規劃文件）——打包時建議排除。")

    if violations:
        print(f"✗ 不可交付：{len(violations)} 項違規")
        for v in violations:
            print("  -", v)
        sys.exit(1)
    print("✓ 可交付：skill 本體無客戶資料、無絕對路徑、shops/ 乾淨。")


if __name__ == "__main__":
    main()
