# -*- coding: utf-8 -*-
"""圖面↔孔群對應：把 DXF 的圓抽出來，並找出「圖面座標→機械座標」的變換。

為什麼不能只做一個全案變換（實測發現）：
  - 部品幾何常包在 BLOCK 裡，naive 的 group-code 解析抓不到（測試003 即是）
  - 一張圖裡部品會畫**很多次**（俯視／仰視／剖視），同一個實體孔在各視圖各出現一次，
    而某些孔只在某個視圖看得到 → 測試003 的 Ø8 圓 X 跨距 2600，部品只有 1000 長

所以改用**點集配對**：拿某個 OP 的 NC 孔位去圖上找最合的位置，並回報對上幾個。
對不上的照實說「無法對應」——畫錯位比不畫更危險。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ncparse  # noqa: E402

TOL = 0.6  # 配對容差 mm（圖面標註值與程式座標可能有微小取整差）


def read_circles(dxf_path):
    """讀 DXF 全部圓（含 BLOCK 展開）。回傳 [(x, y, dia, layer, handle)]"""
    try:
        import ezdxf
    except ImportError:
        return []
    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception:
        return []
    out = []

    def collect(container, depth=0):
        for e in container:
            try:
                t = e.dxftype()
            except Exception:
                continue
            if t == "CIRCLE":
                try:
                    out.append((float(e.dxf.center.x), float(e.dxf.center.y),
                                round(float(e.dxf.radius) * 2, 3),
                                str(e.dxf.layer), str(getattr(e.dxf, "handle", ""))))
                except Exception:
                    pass
            elif t == "INSERT" and depth < 4:
                # 部品幾何常包在 BLOCK 裡——不展開就抓不到（測試003 實例）
                try:
                    collect(e.virtual_entities(), depth + 1)
                except Exception:
                    pass

    collect(doc.modelspace())
    return out


def nc_holes(prog):
    """NC 的孔位清單 [(x, y, dia)]——同一孔只取一次，孔徑取造孔工步。"""
    seen = {}
    for b in prog.blocks:
        if b.is_spot or b.is_chamfer:
            continue
        d = b.dia or (b.thread[0] if b.thread else None)
        if not d:
            continue
        for xy in b.coords:
            seen.setdefault(xy, d)  # 先出現的造孔工步為準
    return [(x, y, d) for (x, y), d in seen.items()]


def _index_by_dia(circles):
    idx = {}
    for x, y, d, layer, h in circles:
        idx.setdefault(round(d, 2), []).append((x, y, layer, h))
    return idx


def fit_transform(holes, circles):
    """點集配對：找 (sx, tx, sy, ty) 讓最多 NC 孔對上同直徑的圖面圓。

    候選平移由「最稀有直徑」的孔×圓配對產生（候選數最少、鑑別度最高）。
    回傳 (best, matched, total)；best 為 None 代表對不上。
    """
    if not holes or not circles:
        return None, 0, len(holes)
    idx = _index_by_dia(circles)
    # 挑鑑別度最高的直徑：NC 有、圖面也有，且圖面該徑的圓最少
    cand_dias = [d for d in {round(h[2], 2) for h in holes} if idx.get(d)]
    if not cand_dias:
        return None, 0, len(holes)
    seed_d = min(cand_dias, key=lambda d: len(idx[d]))
    seed_holes = [h for h in holes if round(h[2], 2) == seed_d]

    best = None
    for sx in (1, -1):
        for sy in (1, -1):
            for hx, hy, _ in seed_holes[:8]:
                for cx, cy, _, _ in idx[seed_d]:
                    tx, ty = hx - sx * cx, hy - sy * cy
                    n = 0
                    for ox, oy, od in holes:
                        for px, py, _, _ in idx.get(round(od, 2), ()):
                            if abs(sx * px + tx - ox) <= TOL and abs(sy * py + ty - oy) <= TOL:
                                n += 1
                                break
                    if best is None or n > best[0]:
                        best = (n, {"sx": sx, "tx": round(tx, 4), "sy": sy, "ty": round(ty, 4)})
    if not best or best[0] == 0:
        return None, 0, len(holes)
    return best[1], best[0], len(holes)


def map_case(case_dir):
    """回傳可供 App 渲染的圖面對應資料。"""
    dwg = None
    ddir = os.path.join(case_dir, "drawing")
    if os.path.isdir(ddir):
        for n in sorted(os.listdir(ddir)):
            if n.lower().endswith(".dxf"):
                dwg = os.path.join(ddir, n)
                break
    if not dwg:
        return {"ok": False, "reason": "案內無 DXF 圖面——無法建立圖面對應"}

    circles = read_circles(dwg)
    if not circles:
        return {"ok": False, "reason": "DXF 讀不到圓實體（缺 ezdxf 或圖面無圓）"}

    gdir = os.path.join(case_dir, "gcode")
    ops = {}
    for n in sorted(os.listdir(gdir)) if os.path.isdir(gdir) else []:
        if not n.lower().endswith(".nc"):
            continue
        prog = ncparse.load(os.path.join(gdir, n))
        holes = nc_holes(prog)
        if not holes:
            continue
        tf, matched, total = fit_transform(holes, circles)
        op = prog.op or n
        entry = {
            "nc": "gcode/" + n,
            "matched": matched,
            "total": total,
            "confidence": "fitted" if tf else "unmatched",
            "transform": tf,
            "holes": [],
        }
        if tf:
            # 變換一旦確立就**只比位置**：圖上畫的直徑不一定等於程式用的刀徑
            # （測試002 的 M16 孔圖繪 Ø13.6、程式實鑽 Ø14）。把圖面直徑一併帶出來，
            # 不一致時反而是有用資訊，不是配對失敗。
            matched = 0
            for hx, hy, hd in holes:
                # 同心孔（如 Ø2 通氣孔畫在 Ø16.05 梢孔正中）位置都命中——
                # 取第一個會配錯，必須在同位置的候選裡挑**直徑最接近**的。
                cands = [(px, py, cd, layer, handle) for px, py, cd, layer, handle in circles
                         if abs(tf["sx"] * px + tf["tx"] - hx) <= TOL
                         and abs(tf["sy"] * py + tf["ty"] - hy) <= TOL]
                hit = None
                if cands:
                    px, py, cd, layer, handle = min(cands, key=lambda c: abs(c[2] - hd))
                    hit = {"handle": handle, "layer": layer, "drawnDia": cd}
                if hit:
                    matched += 1
                entry["holes"].append({"x": hx, "y": hy, "d": hd, "src": hit})
            entry["matched"] = matched
            entry["diaMismatch"] = [
                {"x": h["x"], "y": h["y"], "prog": h["d"], "drawn": h["src"]["drawnDia"]}
                for h in entry["holes"]
                if h["src"] and abs(h["src"]["drawnDia"] - h["d"]) > 0.05
            ]
        else:
            entry["holes"] = [{"x": x, "y": y, "d": d, "src": None} for x, y, d in holes]
        ops[op] = entry

    return {"ok": True, "file": os.path.relpath(dwg, case_dir),
            "circleCount": len(circles), "ops": ops}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    res = map_case(args[0])
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False))
    elif not res["ok"]:
        print("✗", res["reason"])
    else:
        print("圖面 %s（%d 個圓）" % (res["file"], res["circleCount"]))
        for op, e in res["ops"].items():
            pct = 100.0 * e["matched"] / e["total"] if e["total"] else 0
            print("  %-6s 孔 %3d 個 → 對上圖面 %3d 個（%.0f%%）%s"
                  % (op, e["total"], e["matched"], pct,
                     "" if e["confidence"] == "fitted" else "  ← 對不上，不可用於高亮"))
