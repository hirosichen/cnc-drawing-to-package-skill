# -*- coding: utf-8 -*-
"""孔型格式（recipe）：載入格式庫、把既有工序鏈分類回某個格式。

為什麼要分類器：現有案件沒有 hole_plan.json，所以「這群孔套用了什麼格式」是未知的
（孔加工表目前顯示「格式回推不到」）。把既有工序鏈的**語意角色序列**比對格式庫，
就能講出「這群孔 ≈ 梢孔（預鑽→導正搪→鉸）」——使用者才看得懂它是什麼孔，
而不是一串刀號。

分類是**推定**，一律附相似度與依據；比不出來就說比不出來，不硬套。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_yaml(path):
    try:
        import yaml
    except ImportError:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except Exception:
        return None


def load_formats(case_dir=None):
    """shop_profile.yaml（案內快照）→ 廠 shop.yaml → 核心預設，先找到的為準。"""
    for cand in filter(None, [
        os.path.join(case_dir, "shop_profile.yaml") if case_dir else None,
        os.path.join(case_dir, "..", "shop.yaml") if case_dir else None,
    ]):
        d = _load_yaml(cand)
        if d and d.get("hole_formats"):
            return d["hole_formats"], _load_yaml(os.path.join(HERE, "formats.yaml")).get("roles", {}), cand
    d = _load_yaml(os.path.join(HERE, "formats.yaml")) or {}
    return d.get("hole_formats", []), d.get("roles", {}), "核心預設"


def role_of(block, roles):
    """把一個工步歸到語意角色（中心鑽／鑽孔／倒角／攻牙／鉸孔／搪孔…）。

    順序有意義：先認「描述關鍵字」再認循環碼——本廠倒角有用 G82 也有用 G81，
    只看循環碼會誤判（見 ncparse 的同一個教訓）。
    """
    desc = block.desc or ""
    # 描述關鍵字優先
    for rid, r in roles.items():
        for kw in r.get("match", []) or []:
            if kw in desc:
                return rid
    # 再看循環碼
    for rid, r in roles.items():
        if block.cycle in (r.get("cycles") or []):
            return rid
    return None


def chain_of(group_blocks, roles):
    """一群孔的語意角色序列（去掉認不出來的）"""
    out = []
    for b in group_blocks:
        r = role_of(b, roles)
        if r and (not out or out[-1] != r):
            out.append(r)
    return out


def _similarity(actual, want):
    """序列相似度：以「格式要求的工步有幾個真的出現且順序不亂」計。"""
    if not want:
        return 0.0
    i, hit = 0, 0
    for w in want:
        if w in actual[i:]:
            hit += 1
            i = actual.index(w, i) + 1
    extra = len(set(actual) - set(want))
    return hit / len(want) - 0.12 * extra


def classify(group_blocks, formats, roles):
    """回傳 (best_format, score, chain)。score < 0.6 視為比不出來。"""
    chain = chain_of(group_blocks, roles)
    if not chain:
        return None, 0.0, chain
    best, bs = None, -9
    for f in formats:
        want = list(f.get("steps") or [])
        s = _similarity(chain, want)
        if s > bs:
            best, bs = f, s
    return (best, round(bs, 2), chain) if bs >= 0.6 else (None, round(max(bs, 0), 2), chain)



# ---- 從孔加工表（plan）分類，並跨工序串接 ----

def _ckey(coords):
    return ";".join("%g,%g" % (float(x), float(y)) for x, y in sorted(coords or []))


# 造孔角色：出現這些＝這個 OP 自己在做孔，不是別人的精修尾段
_MAKING = {"drill", "predrill", "hd-drill", "cbore-drill", "flat"}


def _link_ops(gs_sorted, roles):
    """跨工序串接的安全條件。

    只靠座標相同會串錯——測試002 的 OP30（前側面）與 OP31（後側面）孔位對稱，
    經「機械X = 1300 − 部品x」映射後**機械座標集完全相同**，但那是不同的實體孔。

    規則：只有當後續 OP 是**純精修尾段**（只有鉸／搪／倒角，沒有任何造孔工步）
    才串起來——那正是梢孔（OP40 只鉸，因廠規鉸孔在研磨後）與背面倒角的形狀。
    兩邊都有完整造孔鏈＝各自獨立的孔群，不串。
    """
    if len(gs_sorted) < 2:
        return gs_sorted
    head = [gs_sorted[0]]
    for g in gs_sorted[1:]:
        chain = chain_of([_S(st) for st in (g.get("steps") or [])], roles)
        if set(chain) & _MAKING:
            continue  # 這個 OP 自己在造孔 → 不是尾段，不串
        head.append(g)
    return head


class _S:
    """把 plan 的工步包成分類器認得的形狀（不必重解析 .nc）"""
    def __init__(self, step):
        self.desc = step.get("label") or step.get("tool", {}).get("spec") or ""
        self.cycle = step.get("cycle") or ""


def _emit(gs_sorted, formats, roles, targets):
    """把一組（已串好的）孔群分類並產出結果 dict。"""
    nm = lambda c: roles.get(c, {}).get("name", c)
    blocks = [_S(st) for g in gs_sorted for st in (g.get("steps") or [])]
    f, score, chain = classify(blocks, formats, roles)
    want = list(f.get("steps") or []) if f else []
    res = {
        "formatId": f["id"] if f else "",
        "label": f["label"] if f else "",
        "type": f.get("type", "") if f else "",
        "score": score,
        "chain": [nm(c) for c in chain],
        "missing": [nm(w) for w in want if w not in chain],
        "extra": [nm(c) for c in chain if want and c not in want],
        "note": (f.get("note") or "").strip() if f else "",
        "ops": sorted({str(x.get("op")) for x in gs_sorted}),
    }
    return {g["id"]: dict(res) for g in targets}


def classify_plan(plan, case_dir=None):
    """輸入孔加工表，回傳 {群id: {formatId,label,score,chain,linkedFrom}}。

    **跨工序串接**：座標集合相同的孔群屬同一個 recipe——梢孔就是典型，
    預鑽在 OP10、鉸孔在 OP40（廠規：鉸孔必須在研磨之後）。逐 OP 看會兩邊都比不出來。
    """
    formats, roles, src = load_formats(case_dir)
    groups = plan.get("groups") or []
    bykey = {}
    for g in groups:
        bykey.setdefault(_ckey(g.get("coords")), []).append(g)

    out = {}
    for key, gs in bykey.items():
        if not key:
            continue
        gs_sorted = sorted(gs, key=lambda g: str(g.get("op")))
        linked = _link_ops(gs_sorted, roles)
        # 沒被串進來的（自己有造孔工步＝獨立特徵，如與梢孔同軸的 Ø2 通氣孔）
        # 必須各自分類，不能沾用串接後的結果
        for g in gs_sorted:
            if g in linked:
                continue
            out.update(_emit([g], formats, roles, [g]))
        out.update(_emit(linked, formats, roles, linked))
    return out, src, formats


if __name__ == "__main__":
    import json

    if "--classify" in sys.argv:
        payload = json.loads(sys.stdin.read())
        res, src, formats = classify_plan(payload.get("plan") or {}, payload.get("caseDir"))
        print(json.dumps({"ok": True, "source": src, "formats": formats, "byGroup": res},
                         ensure_ascii=False))
        sys.exit(0)

    import ncparse
    import compare

    case = sys.argv[1]
    formats, roles, src = load_formats(case)
    print("格式庫來源：%s（%d 個格式）\n" % (src, len(formats)))
    gdir = os.path.join(case, "gcode")
    for n in sorted(os.listdir(gdir)):
        if not n.lower().endswith(".nc"):
            continue
        prog = ncparse.load(os.path.join(gdir, n))
        for k, blocks in compare.hole_groups(prog).items():
            f, score, chain = classify(blocks, formats, roles)
            names = "→".join(roles.get(c, {}).get("name", c) for c in chain)
            print("   %-6s %3d 孔  %-26s  %s" % (prog.op or n, len(k), names,
                  ("≈ %s（%.2f）" % (f["label"], score)) if f else "✗ 比不出（%.2f）" % score))
