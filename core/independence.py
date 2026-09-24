# -*- coding: utf-8 -*-
"""檢核獨立性稽核：抓出案件自己重寫的「規則」斷言。

判別準則（design D4）：**這條斷言換一個案子還成立嗎？**
  成立 → 規則，只能有一份實作，歸共用核心
  不成立 → 事實（綁這張圖），可以留在案內

為什麼要自動化：手工掃三案就發現 F=S×P 被寫了四遍、貫穿深度含鑽尖四遍、
鉸孔在研磨後三遍——全是廠規、全已寫在知識庫、全由寫錯的人自己驗。
不自動抓，下一個案子照樣重來一遍。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 案件斷言文字命中這些樣式 → 屬「規則」，核心已有或應有
RULE_PATTERNS = [
    ("R1 剛性攻牙 F=S×P", re.compile(r"F\s*=\s*S\s*[×xX*]|剛攻\s*F|F=S×|剛性攻牙")),
    ("R3 循環選型 L/D", re.compile(r"L/D|深徑比")),
    ("R4 盲孔殘餘壁厚", re.compile(r"殘餘壁|留\s*1\.5|留\s*1\.0")),
    ("R5 轉速上限", re.compile(r"S\s*[>≤<]\s*\d{4}|MAX_RPM|轉速上限|Smax", re.I)),
    ("R7 剛攻前置 M29", re.compile(r"M29")),
    ("R8 貫穿深度含鑽尖", re.compile(r"貫穿深|貫穿\s*\d+\.?\d*\s*\+\s*尖|\+\s*尖\d")),
    ("（未進核心）Q 取刀具庫值", re.compile(r"Q\s*=\s*[\d.]+（庫值）|Q＝庫值|庫值）")),
    ("R9 鉸孔在研磨之後", re.compile(r"研磨後|位於研磨之後|鉸孔移\s*OP")),
    ("R10 非固定刀 M0 換刀", re.compile(r"M0\s*停機|前有\s*M0|皆有\s*M0|M0\s*鐵則|倉外刀.*M0")),
    ("（未進核心）G43 三鐵律", re.compile(r"換刀後.*G43|G43\s*H\s*號|G49")),
    ("（未進核心）固定循環以 G80 結束", re.compile(r"G80\s*結束")),
    ("（未進核心）刀長檢核", re.compile(r"刀長檢核|刀長\s*[≤<]")),
    ("（未進核心）夾持淨空", re.compile(r"夾持淨空|鉗口|壓板.*淨空")),
    ("（未進核心）刀號分區 T3~T22／T100", re.compile(r"倉外刀用\s*T100|固定倉用\s*T3|T3~T22")),
    ("（未進核心）程式結構", re.compile(r"程式結構")),
]

# 明顯屬「事實」的訊號：帶具體座標／數量的斷言，換個案子就不成立
FACT_HINT = re.compile(r"[×x]\s*\d+\b|\b\d{2,4}\s*/\s*\d{2,4}\b|位\s*\d+")

# 斷言函式名各案不一：測試001/002/004 用 check()，測試003 用 ck()/ckv()。
# 必須用詞邊界綁定，否則 `hole_check("O0010.nc", ...)` 會被當成斷言，
# 把**檔名**讀成斷言文字——那會讓整個偵測靜默失效（回報「0 處重寫」）。
# 斷言多為 f-string（ck(f"{tag} …")），故引號前需容許 f/rf/fr 前綴——
# 少了它同樣會靜默漏掉全部斷言。
ASSERT_RE = re.compile(
    r'(?<![A-Za-z0-9_])(?:check|ck|ckv|assert_\w+)\(\s*[frb]{0,2}(["\'])(.+?)\1', re.S)


def scan_text(text):
    """回傳 (rules_found, facts, total)。rules_found: [(規則名, 斷言文字)]"""
    asserts = [m.group(2) for m in ASSERT_RE.finditer(text)]
    rules_found, facts = [], []
    for a in asserts:
        hit = next((name for name, rx in RULE_PATTERNS if rx.search(a)), None)
        if hit:
            rules_found.append((hit, a))
        elif FACT_HINT.search(a):
            facts.append(a)
        else:
            facts.append(a)  # 判不出來一律當事實——不誣賴案件
    return rules_found, facts, len(asserts)


def scan_case(case_dir):
    out = {"files": [], "rules": [], "facts": 0, "total": 0}
    vdir = os.path.join(case_dir, "verification")
    if not os.path.isdir(vdir):
        return out
    for n in sorted(os.listdir(vdir)):
        if not n.endswith(".py"):
            continue
        p = os.path.join(vdir, n)
        try:
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        r, f, t = scan_text(text)
        if t:
            out["files"].append(n)
            out["rules"] += [(n,) + x for x in r]
            out["facts"] += len(f)
            out["total"] += t
    return out


def report(case_dir):
    name = os.path.basename(os.path.normpath(case_dir))
    res = scan_case(case_dir)
    if not res["total"]:
        print("\n═══ %s ═══  （verification/ 內無斷言）" % name)
        return res
    n = len(res["rules"])
    print("\n═══ %s ═══  斷言 %d 條：疑似重寫廠規 %d ・ 案件事實 %d"
          % (name, res["total"], n, res["facts"]))
    if not n:
        print("  ✅ 未發現案件自行實作規則斷言")
        return res
    by_rule = {}
    for fname, rule, txt in res["rules"]:
        by_rule.setdefault(rule, []).append((fname, txt))
    for rule, items in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        print("  ⚠ %s ← 案內重寫 %d 處" % (rule, len(items)))
        for fname, txt in items:
            print("      %s: %s" % (fname, txt[:70]))
    return res


if __name__ == "__main__":
    targets = [a for a in sys.argv[1:] if not a.startswith("-")]
    tot = 0
    for t in targets:
        tot += len(report(t)["rules"])
    if len(targets) > 1:
        print("\n總計疑似重寫廠規：%d 處" % tot)
        print("判別準則：這條斷言換一個案子還成立嗎？成立＝規則（歸核心），不成立＝事實（留案內）。")
