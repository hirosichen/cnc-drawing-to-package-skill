# -*- coding: utf-8 -*-
"""hole_plan.json（schema hole-plan/1）產出。

契約的意義：孔加工表要能講出「這群孔套用什麼格式、深度怎麼算出來的」，
而不是只能從 .nc 反推。有了它，換格式與重生才有依據。

**座標不進計畫檔**——尺寸唯一來源恆為 params.py。計畫只存孔群參數與工序鏈，
另附 coords 純供 UI 呈現（見 types.d.ts 的註記）。
"""
import json
import os

SCHEMA = "hole-plan/1"


class Step:
    def __init__(self, seq, label, t, h, spec, cycle, z, nc,
                 r=None, q=None, s=None, f=None, depth=None, registered=True):
        self.d = {
            "seq": seq, "label": label, "cycle": cycle, "z": z, "nc": nc,
            "tool": {"t": t, "h": "H%02d" % h if isinstance(h, int) else str(h),
                     "spec": spec, "registered": registered},
        }
        for k, v in (("r", r), ("q", q), ("s", s), ("f", f)):
            if v is not None:
                self.d[k] = v
        if depth is not None:
            self.d["depth"] = depth.as_dict() if hasattr(depth, "as_dict") else depth


class Group:
    def __init__(self, gid, label, count, dia, feature, op,
                 through=None, format_id="", format_label="", params_ref="",
                 drawing_ref="", coords=None):
        self.d = {
            "id": gid, "label": label, "count": count, "dia": dia,
            "feature": feature, "op": op, "formatId": format_id,
            "steps": [],
        }
        if through is not None:
            self.d["through"] = through
        if format_label:
            self.d["formatLabel"] = format_label
        if params_ref:
            self.d["paramsRef"] = params_ref
        if drawing_ref:
            self.d["drawingRef"] = drawing_ref
        if coords:
            self.d["coords"] = [[float(x), float(y)] for x, y in coords]

    def add(self, step):
        self.d["steps"].append(step.d)
        return self


class Plan:
    def __init__(self, part_no="", machine="", core_version=""):
        self.d = {
            "schema": SCHEMA, "origin": "generated", "editable": True,
            "partNo": part_no, "machine": machine,
            "coreVersion": core_version,
            "groups": [], "uncovered": [],
        }

    def add(self, group):
        self.d["groups"].append(group.d)
        return self

    def uncovered(self, reason, where=""):
        """核心涵蓋不到、由案件手寫的段落——必須吵，不能靜默繞過。"""
        self.d["uncovered"].append({"reason": reason, "where": where})
        return self

    def write(self, gcode_dir):
        p = os.path.join(gcode_dir, "hole_plan.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(self.d, fh, ensure_ascii=False, indent=2)
        return p

    def as_dict(self):
        return self.d


def check_against_nc(plan_dict, gcode_dir):
    """交叉檢核：計畫宣告的每個工步，在對應 .nc 內都要找得到同樣的循環與深度。

    這是契約的自我防護——計畫與程式若不同步，孔加工表就會騙人。
    """
    import ncparse

    problems = []
    cache = {}
    for g in plan_dict.get("groups", []):
        for st in g.get("steps", []):
            rel = st.get("nc", "")
            path = os.path.join(os.path.dirname(gcode_dir.rstrip("/")), rel) \
                if not os.path.isabs(rel) else rel
            if not os.path.isfile(path):
                path = os.path.join(gcode_dir, os.path.basename(rel))
            if not os.path.isfile(path):
                problems.append("%s：找不到 %s" % (g["id"], rel))
                continue
            prog = cache.get(path) or cache.setdefault(path, ncparse.load(path))
            hit = [b for b in prog.blocks
                   if b.cycle == st.get("cycle")
                   and st.get("z") is not None and b.z is not None
                   and abs(b.z - st["z"]) < 0.001]
            if not hit:
                problems.append("%s／%s：.nc 內找不到 %s Z%s"
                                % (g["id"], st.get("label", ""), st.get("cycle"), st.get("z")))
    return problems
