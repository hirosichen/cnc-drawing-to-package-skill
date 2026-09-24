# -*- coding: utf-8 -*-
"""對任意既有案件（或單一 .nc）跑廠規斷言稽核。

預設唯讀，絕不寫入被稽核的案件。加 --json <路徑> 才會寫出機器可讀結果檔
（供 App 判定檢核旗標；案件不得手寫這個檔）。

用法：
    python3 audit_cli.py <案件資料夾或 .nc 檔> [...] [-v]
    python3 audit_cli.py <案件資料夾> --json <案件>/verification/audit.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ncparse  # noqa: E402
import rules  # noqa: E402

ORDER = {rules.FAIL: 0, rules.WARN: 1, rules.NA: 2, rules.PASS: 3}

HERE = os.path.dirname(os.path.abspath(__file__))


def core_version():
    try:
        with open(os.path.join(HERE, "VERSION")) as fh:
            return fh.read().strip()
    except OSError:
        return "unknown"


# 業界 NC 驗證鏈四段。前兩段本系統做得到；後三段做不到——
# 預設全 False，只有真的做了才由人翻成 True。這是誠實度聲明的資料來源。
DEFAULT_STAGES = {
    "geometry_self_check": None,        # 案內 verify_cad（由案件自己寫，非獨立）
    "shop_rule_audit": False,           # 共用核心廠規斷言——跑了就 True
    "independent_gcode_verify": False,  # 獨立 G-code 驗證（Vericut 等）
    "machine_dry_run": False,           # 機上空跑：Z 偏移＋低倍率＋單節
    "first_article": False,             # 首件檢驗
}


def nc_files(target):
    if os.path.isfile(target):
        return [target]
    gdir = os.path.join(target, "gcode")
    base = gdir if os.path.isdir(gdir) else target
    return sorted(os.path.join(base, n) for n in os.listdir(base) if n.lower().endswith(".nc"))


def collect(target):
    """回傳 (findings, tally)。NA 與 PASS 嚴格分開——查不了不等於通過。"""
    findings = []
    for f in nc_files(target):
        findings += rules.audit(ncparse.load(f))
    tally = {s: sum(1 for x in findings if x.status == s)
             for s in (rules.FAIL, rules.WARN, rules.NA, rules.PASS)}
    return findings, tally


def result_doc(findings, tally):
    """機器可讀結果檔——App 由此判定檢核旗標。"""
    return {
        "core_version": core_version(),
        "rules": sorted({x.rule.split()[0] for x in findings}),
        "tally": {k: tally[k] for k in (rules.FAIL, rules.WARN, rules.NA, rules.PASS)},
        "findings": [{"rule": x.rule, "status": x.status, "where": x.where, "detail": x.detail}
                     for x in sorted(findings, key=lambda x: (ORDER[x.status], x.rule))],
        "stages": {**DEFAULT_STAGES, "shop_rule_audit": True},
        "note": ("tally 的 NA＝無法檢核，不等於通過，不計入 PASS。"
                 "stages 中為 false 者代表尚未進行——本程式從未上機。"),
    }


def run(target, show_pass=False):
    name = os.path.basename(os.path.normpath(target))
    if not nc_files(target):
        print("  （無 .nc）")
        return {}, []
    findings, tally = collect(target)
    print("\n═══ %s ═══  FAIL %d ・ WARN %d ・ NA %d ・ PASS %d"
          % (name, tally[rules.FAIL], tally[rules.WARN], tally[rules.NA], tally[rules.PASS]))
    for x in sorted(findings, key=lambda x: (ORDER[x.status], x.rule)):
        if x.status in (rules.PASS, rules.WARN) and not show_pass:
            continue
        print("  [%s] %-28s %s" % (x.status, x.rule, x.where))
        print("        %s" % x.detail)
    return tally, findings


if __name__ == "__main__":
    argv = sys.argv[1:]
    out_json = None
    if "--json" in argv:
        i = argv.index("--json")
        out_json = argv[i + 1]
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("-")]
    show = "-v" in argv
    total, all_findings = {}, []
    for t in args:
        tally, findings = run(t, show)
        all_findings += findings
        for k, v in (tally or {}).items():
            total[k] = total.get(k, 0) + v
    if len(args) > 1:
        print("\n總計：FAIL %d ・ WARN %d ・ NA %d ・ PASS %d"
              % (total.get(rules.FAIL, 0), total.get(rules.WARN, 0),
                 total.get(rules.NA, 0), total.get(rules.PASS, 0)))
    if out_json:
        os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(result_doc(all_findings, {**{k: 0 for k in ORDER}, **total}),
                      fh, ensure_ascii=False, indent=2)
        print("\n結果檔 →", out_json)
