#!/usr/bin/env python3
"""組裝單一檔案的 CNC 切削模擬器 HTML（Three.js 與 NC 程式全部內嵌）。

用法：
  python3 assemble.py --markup cam_markup.html --app cam_app.js \
      --nc NC0=gcode/O0010_OP10_TOP.nc --nc NC20=gcode/O0020_OP20_END_A.nc \
      --out simulation/<件號>-cam-sim.html

--nc 可重複，NAME 對應 app.js 內引用的全域常數（如 const PROGS = [parseNC(NC0), ...]）。
函式庫（three.min.js / OrbitControls.js）預設取自本腳本所在資料夾。
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def rd(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--markup', required=True)
    ap.add_argument('--app', required=True)
    ap.add_argument('--nc', action='append', default=[], metavar='NAME=PATH')
    ap.add_argument('--lib', default=HERE, help='three.min.js / OrbitControls.js 所在資料夾')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    three = rd(os.path.join(a.lib, 'three.min.js'))
    orbit = rd(os.path.join(a.lib, 'OrbitControls.js'))
    app = rd(a.app)
    for name, s in [('three', three), ('orbit', orbit), ('app', app)]:
        assert '</script' not in s.lower(), f'{name} 內含 </script>，會截斷 HTML'

    nc_defs = ''
    for spec in a.nc:
        name, path = spec.split('=', 1)
        nc_defs += f'const {name} = ' + json.dumps(rd(path)) + ';\n'

    html = ('<meta charset="utf-8">\n' + rd(a.markup)
            + '\n<script>\n' + three + '\n</script>\n'
            + '<script>\n' + orbit + '\n</script>\n'
            + '<script>\n' + nc_defs + app + '\n</script>\n')
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'OK {a.out} {len(html)} bytes')


if __name__ == '__main__':
    main()
