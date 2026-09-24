/* ============================================================
   E01 CNC 切削模擬 — OP10 頂面 → OP20/OP21 端面（三工序連續）
   - 解析真實 FANUC G-code（G0/G1/G2/G3 含螺旋帶Z與只給I/J的整圓、
     G81/G82/G83/G84/G85 固定循環）
   - OP10：高度場材料移除；OP20/21：端面立夾鑽攻（精確圓孔）
   - 工序間自動「重新裝夾」翻面動畫，加工狀態全程保留
   ============================================================ */
'use strict';

/* ---------- 常數 ---------- */
const STOCK = { L: 288, W: 100, T: 28 };
const RES = 0.5;
const NX = Math.round(STOCK.L / RES) + 1;
const NY = Math.round(STOCK.W / RES) + 1;
const ZMIN = -STOCK.T;
const RAPID_F = 10000;
const SAFE_Z = 50;

const TOOLS = {
  1:  { dia: 16,  type: 'flat',  name: 'D16 粗銑立銑刀',   s: 'S2400', color: 0xd79c5a },
  2:  { dia: 12,  type: 'flat',  name: 'D12 精銑立銑刀',   s: 'S3200', color: 0x52b8d8 },
  3:  { dia: 10,  type: 'flat',  name: 'D10 立銑刀（沉頭）', s: 'S3500', color: 0x7fd0a2 },
  4:  { dia: 3,   type: 'drill', name: 'D3 中心鑽',        s: 'S2000', color: 0xe0d070 },
  5:  { dia: 5,   type: 'drill', name: 'D5.0 鑽頭',        s: 'S1400', color: 0xd88a6a },
  6:  { dia: 6.6, type: 'drill', name: 'D6.6 鑽頭',        s: 'S1100', color: 0xd8766a },
  7:  { dia: 7.8, type: 'drill', name: 'D7.8 鑽頭',        s: 'S950',  color: 0xcf6a80 },
  8:  { dia: 13.8,type: 'drill', name: 'D13.8 鑽頭',       s: 'S550',  color: 0xc46a9d },
  9:  { dia: 8,   type: 'ream',  name: 'D8H7 鉸刀',        s: 'S320',  color: 0x9d8fe0 },
  10: { dia: 14,  type: 'ream',  name: 'D14H7 鉸刀',       s: 'S180',  color: 0x8f9de0 },
  11: { dia: 6,   type: 'tap',   name: 'M6×1.0 剛性攻牙',  s: 'S400',  color: 0xe08fb6 },
};
const STEEL = [0.585, 0.63, 0.665];
const THRU  = [0.16, 0.18, 0.20];
const CONE = 0.6;

/* ---------- G-code 解析 ---------- */
function parseNC(text) {
  const src = text.split('\n');
  const moves = [], ops = [];
  let x = 0, y = 0, z = SAFE_Z, f = 300, tool = 0, motion = 1;
  let cycle = 0, cycR = 0, cycZ = 0, cycQ = 2, cycF = 100, initZ = SAFE_Z;

  function emit(nx, ny, nz, rapid, ln, feed) {
    const len = Math.hypot(nx - x, ny - y, nz - z);
    if (len > 1e-9) moves.push({ x0: x, y0: y, z0: z, x1: nx, y1: ny, z1: nz,
      rapid, f: rapid ? RAPID_F : (feed || f), tool, ln, len });
    x = nx; y = ny; z = nz;
  }
  function arc(nx, ny, nz, cw, R, I, J, ln) {
    let cx, cy;
    if (I !== null || J !== null) { cx = x + (I || 0); cy = y + (J || 0); }
    else {
      const dx = nx - x, dy = ny - y, d = Math.hypot(dx, dy), r = Math.abs(R);
      let h2 = r * r - d * d / 4; if (h2 < 0) h2 = 0;
      const h = Math.sqrt(h2) * (R >= 0 ? 1 : -1) * (cw ? -1 : 1);
      cx = x + dx / 2 - h * dy / d; cy = y + dy / 2 + h * dx / d;
    }
    const r = Math.hypot(x - cx, y - cy);
    let a0 = Math.atan2(y - cy, x - cx), a1 = Math.atan2(ny - cy, nx - cx);
    const full = Math.abs(nx - x) < 1e-9 && Math.abs(ny - y) < 1e-9;
    if (cw) { if (a1 >= a0 - 1e-9) a1 -= 2 * Math.PI; if (full) a1 = a0 - 2 * Math.PI; }
    else    { if (a1 <= a0 + 1e-9) a1 += 2 * Math.PI; if (full) a1 = a0 + 2 * Math.PI; }
    const z0a = z;                                  /* 螺旋：Z 沿弧線內插（G2/G3 帶 Z） */
    const n = Math.max(8, Math.ceil(Math.abs(a1 - a0) * r / 0.8));
    for (let i = 1; i <= n; i++) {
      const a = a0 + (a1 - a0) * i / n;
      emit(cx + r * Math.cos(a), cy + r * Math.sin(a), z0a + (nz - z0a) * i / n, false, ln);
    }
  }
  function runCycle(cx, cy, ln) {
    emit(cx, cy, z, true, ln);
    emit(cx, cy, cycR, true, ln);
    if (cycle === 83) {
      let cur = cycR;
      while (cur > cycZ + 1e-9) {
        const next = Math.max(cycZ, cur - cycQ);
        emit(cx, cy, next, false, ln, cycF);
        if (next > cycZ + 1e-9) { emit(cx, cy, cycR, true, ln); emit(cx, cy, next + 0.5, true, ln); }
        cur = next;
      }
      emit(cx, cy, cycR, true, ln);
    } else if (cycle === 84 || cycle === 85) {
      emit(cx, cy, cycZ, false, ln, cycF);
      emit(cx, cy, cycR, false, ln, cycF);
    } else {
      emit(cx, cy, cycZ, false, ln, cycF);
      emit(cx, cy, cycR, true, ln);
    }
    emit(cx, cy, initZ, true, ln);
  }

  for (let ln = 0; ln < src.length; ln++) {
    let line = src[ln].trim();
    if (!line || line === '%' || /^O\d+/.test(line.replace(/\(.*\)/, '').trim())) continue;
    const cm = line.match(/^\(---\s*(.*?)\s*---\)$/);
    if (cm) { ops.push({ label: cm[1], mi: moves.length, tool }); continue; }
    if (line.startsWith('(')) continue;
    line = line.replace(/\(.*?\)/g, ' ');

    const words = {}; const gcodes = [];
    line.replace(/([A-Z])\s*([-+]?[0-9.]+)/g, (_, l, v) => {
      if (l === 'G') gcodes.push(Math.round(parseFloat(v)));
      else words[l] = parseFloat(v);
      return '';
    });
    if (words.T !== undefined && /M\s*0*6/.test(line)) {
      tool = Math.round(words.T);
      const t = TOOLS[tool];
      ops.push({ label: `換刀 T${tool} — ${t ? t.name : ''}`, mi: moves.length, tool, isTool: true });
      cycle = 0; continue;
    }
    if (gcodes.includes(28)) { emit(x, y, SAFE_Z, true, ln); continue; }
    let cycleLine = false;
    for (const g of gcodes) {
      if (g >= 0 && g <= 3) motion = g;
      else if (g === 80) cycle = 0;
      else if (g === 81 || g === 82 || g === 83 || g === 84 || g === 85) {   /* G82 停留視同 G81 */
        cycle = g; initZ = z; cycleLine = true;
        if (words.R !== undefined) cycR = words.R;
        if (words.Z !== undefined) cycZ = words.Z;
        if (words.Q !== undefined) cycQ = words.Q;
        if (words.F !== undefined) cycF = words.F;
      }
    }
    if (words.F !== undefined) { f = words.F; if (cycle) cycF = words.F; }
    if (cycleLine) {
      /* FANUC:G8x 循環行本身即執行一孔;行內無 X/Y 時在「當前位置」執行(00L2 案教訓) */
      runCycle(words.X !== undefined ? words.X : x, words.Y !== undefined ? words.Y : y, ln);
      continue;
    }
    if (cycle && (words.X !== undefined || words.Y !== undefined)) {
      if (words.R !== undefined) cycR = words.R;
      if (words.Z !== undefined) cycZ = words.Z;
      if (words.Q !== undefined) cycQ = words.Q;
      runCycle(words.X !== undefined ? words.X : x, words.Y !== undefined ? words.Y : y, ln);
      continue;
    }
    /* 整圓（G2/G3 只給 I/J/R、無 X/Y/Z，如 `G3 I-7.2`）不可被「無座標字跳過」丟棄，
       否則穴的環繞銑削/沉頭圓弧插補整段消失（hardened-3op 案教訓） */
    const fullArc = motion >= 2 &&
      (words.I !== undefined || words.J !== undefined || words.R !== undefined);
    if (words.X === undefined && words.Y === undefined && words.Z === undefined && !fullArc) continue;
    const nx = words.X !== undefined ? words.X : x;
    const ny = words.Y !== undefined ? words.Y : y;
    const nz = words.Z !== undefined ? words.Z : z;
    if (motion === 0) emit(nx, ny, nz, true, ln);
    else if (motion === 1) emit(nx, ny, nz, false, ln);
    else arc(nx, ny, nz, motion === 2, words.R !== undefined ? words.R : null,
             words.I !== undefined ? words.I : null, words.J !== undefined ? words.J : null, ln);
  }
  let t = 0;
  for (const m of moves) { m.t0 = t; t += m.len / m.f; m.t1 = t; }
  return { moves, ops, total: t, src };
}

/* ---------- 三個工序（裝夾） ---------- */
const PROGS = [parseNC(NC0), parseNC(NC20), parseNC(NC21)];
const OFF = [0, PROGS[0].total, PROGS[0].total + PROGS[1].total];
const TOTAL = OFF[2] + PROGS[2].total;

const SETUPS = [
  { code: 'OP10', wcs: 'G54', file: 'O0010_OP10_TOP.nc',
    title: 'OP10 頂面全工序（平夾）',
    sub: 'O0010 · G54 左前角頂面 · 精密虎鉗×2 平夾 · FANUC 0i-MF',
    clampMsg: null,
    m2p: (mx, my, mz) => [mx, my, mz],
    basis: [[1,0,0],[0,1,0],[0,0,1]], pos: [0, 0, 0],
    camPos: [354, -240, 190], camTgt: [144, 50, -8] },
  /* 立起後機械X對到部品Y反向（右手系；兩孔對稱於Y50，加工結果不變） */
  { code: 'OP20', wcs: 'G55', file: 'O0020_OP20_END_A.nc',
    title: 'OP20 端面A M6×2（立夾）',
    sub: 'O0020 · G55 端面 X0端朝上 · 角板立夾＋壓板 · FANUC 0i-MF',
    clampMsg: ['重新裝夾 → OP20 端面A', '翻轉工件靠角板立夾，X0 端面朝上，G55 對刀'],
    m2p: (mx, my, mz) => [-mz, STOCK.W - mx, my - STOCK.T],
    holeX0: 0, holeDir: 1,
    basis: [[0,0,-1],[-1,0,0],[0,1,0]], pos: [STOCK.W, STOCK.T, 0],
    camPos: [230, -205, 195], camTgt: [50, 8, -55] },
  { code: 'OP21', wcs: 'G56', file: 'O0021_OP21_END_B.nc',
    title: 'OP21 端面B M6×2（立夾）',
    sub: 'O0021 · G56 端面 X288端朝上 · 角板立夾＋壓板 · FANUC 0i-MF',
    clampMsg: ['重新裝夾 → OP21 端面B', '翻轉工件靠角板立夾，X288 端面朝上，G56 對刀'],
    m2p: (mx, my, mz) => [STOCK.L + mz, mx, my - STOCK.T],
    holeX0: STOCK.L, holeDir: -1,
    basis: [[0,0,1],[1,0,0],[0,1,0]], pos: [0, STOCK.T, -STOCK.L],
    camPos: [230, -205, 195], camTgt: [50, 8, -55] },
];
for (const s of SETUPS) {
  const m = new THREE.Matrix4().makeBasis(
    new THREE.Vector3(...s.basis[0]), new THREE.Vector3(...s.basis[1]), new THREE.Vector3(...s.basis[2]));
  s.quat = new THREE.Quaternion().setFromRotationMatrix(m);
  s.posV = new THREE.Vector3(...s.pos);
}

/* ---------- 高度場（OP10） ---------- */
const Hgt = new Float32Array(NX * NY);
const Col = new Float32Array(NX * NY * 3);
let dirty = null;

function resetStock() {
  Hgt.fill(0);
  for (let i = 0; i < NX * NY; i++) { Col[3*i] = STEEL[0]; Col[3*i+1] = STEEL[1]; Col[3*i+2] = STEEL[2]; }
  dirty = [0, NX - 1, 0, NY - 1];
}
function mark(ix, iy) {
  if (!dirty) dirty = [ix, ix, iy, iy];
  else {
    if (ix < dirty[0]) dirty[0] = ix; if (ix > dirty[1]) dirty[1] = ix;
    if (iy < dirty[2]) dirty[2] = iy; if (iy > dirty[3]) dirty[3] = iy;
  }
}
function cutVertex(ix, iy, cz, cr, cg, cb) {
  if (cz < ZMIN) cz = ZMIN;
  const i = iy * NX + ix;
  if (cz < Hgt[i] - 1e-6) {
    Hgt[i] = cz;
    if (cz <= ZMIN + 1e-6) { Col[3*i] = THRU[0]; Col[3*i+1] = THRU[1]; Col[3*i+2] = THRU[2]; }
    else { Col[3*i] = cr; Col[3*i+1] = cg; Col[3*i+2] = cb; }
    mark(ix, iy);
  }
}
function carveCircle(cx, cy, r, zTip, cone, rgb) {
  const ix0 = Math.max(0, Math.floor((cx - r) / RES)), ix1 = Math.min(NX - 1, Math.ceil((cx + r) / RES));
  const iy0 = Math.max(0, Math.floor((cy - r) / RES)), iy1 = Math.min(NY - 1, Math.ceil((cy + r) / RES));
  for (let iy = iy0; iy <= iy1; iy++) {
    const py = iy * RES, dy = py - cy;
    for (let ix = ix0; ix <= ix1; ix++) {
      const px = ix * RES, dx = px - cx;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d <= r) cutVertex(ix, iy, cone ? zTip + cone * d : zTip, rgb[0], rgb[1], rgb[2]); // cone=錐尖斜率(0=平底)
    }
  }
}
function carveCapsule(x0, y0, z0, x1, y1, z1, r, cone, rgb) {
  const dx = x1 - x0, dy = y1 - y0;
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) { carveCircle(x0, y0, r, Math.min(z0, z1), cone, rgb); return; }
  const ix0 = Math.max(0, Math.floor((Math.min(x0, x1) - r) / RES));
  const ix1 = Math.min(NX - 1, Math.ceil((Math.max(x0, x1) + r) / RES));
  const iy0 = Math.max(0, Math.floor((Math.min(y0, y1) - r) / RES));
  const iy1 = Math.min(NY - 1, Math.ceil((Math.max(y0, y1) + r) / RES));
  const invL2 = 1 / (len * len), dz = z1 - z0, r2 = r * r;
  for (let iy = iy0; iy <= iy1; iy++) {
    const py = iy * RES;
    for (let ix = ix0; ix <= ix1; ix++) {
      const px = ix * RES;
      const t = ((px - x0) * dx + (py - y0) * dy) * invL2;
      const tc = t < 0 ? 0 : (t > 1 ? 1 : t);
      const qx = x0 + tc * dx - px, qy = y0 + tc * dy - py;
      if (qx * qx + qy * qy > r2) continue;
      const pxl = px - x0, pyl = py - y0;
      const cross = Math.abs(pxl * dy - pyl * dx) / len;
      const w = Math.sqrt(Math.max(0, r2 - cross * cross)) / len;
      let tA = t - w, tB = t + w;
      if (tA < 0) tA = 0; if (tB > 1) tB = 1;
      const cz = Math.min(z0 + tA * dz, z0 + tB * dz);
      cutVertex(ix, iy, cz, rgb[0], rgb[1], rgb[2]);
    }
  }
}

/* ---------- Three.js 場景 ---------- */
const vp = document.getElementById('viewport');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
vp.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101519);
scene.fog = new THREE.Fog(0x101519, 900, 1800);
const camera = new THREE.PerspectiveCamera(40, 1, 1, 4000);
camera.up.set(0, 0, 1);
camera.position.set(354, -240, 190);
const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.target.set(144, 50, -8);
controls.enableDamping = true; controls.dampingFactor = 0.12;
controls.maxPolarAngle = Math.PI * 0.52;

scene.add(new THREE.HemisphereLight(0xcfd8e3, 0x2a2f38, 0.75));
const sun = new THREE.DirectionalLight(0xffffff, 0.85);
sun.position.set(-180, -260, 420); scene.add(sun);
const sun2 = new THREE.DirectionalLight(0x88aacc, 0.25);
sun2.position.set(400, 300, 200); scene.add(sun2);

const grid = new THREE.GridHelper(1200, 60, 0x223040, 0x1a232e);
grid.rotation.x = Math.PI / 2;
grid.position.set(STOCK.L / 2, STOCK.W / 2, ZMIN - 22.05);
scene.add(grid);

/* 平夾虎鉗（OP10） */
const jawMat = new THREE.MeshPhongMaterial({ color: 0x39424c, shininess: 30 });
const flatJaws = new THREE.Group();
for (const jx of [52, 236]) for (const jy of [-13, 101]) {
  const jaw = new THREE.Mesh(new THREE.BoxGeometry(72, 12, 34), jawMat);
  jaw.position.set(jx, jy + 6, ZMIN - 22 + 17);
  flatJaws.add(jaw);
}
scene.add(flatJaws);
/* 立夾治具（OP20/21）：台面上的角板 + 底部墊塊 + 前側兩支壓板
   立起的工件佔 世界 x0..100 y0..28 z0..-288，背面(y=28)貼角板，底端坐墊塊 */
const endFixture = new THREE.Group();
{
  const plateMat = new THREE.MeshPhongMaterial({ color: 0x424b56, shininess: 25 });
  const clampMat = new THREE.MeshPhongMaterial({ color: 0x5a646f, shininess: 45 });
  const TABLE_Z = -302;
  /* 角板直立面（工件背面貼靠） */
  const face = new THREE.Mesh(new THREE.BoxGeometry(150, 22, 275), plateMat);
  face.position.set(50, STOCK.T + 11, TABLE_Z + 275 / 2);
  endFixture.add(face);
  /* 角板底腳（坐在台面上） */
  const foot = new THREE.Mesh(new THREE.BoxGeometry(150, 110, 14), plateMat);
  foot.position.set(50, STOCK.T + 55, TABLE_Z + 7);
  endFixture.add(foot);
  /* 三角肋板 ×2 */
  for (const rx of [-16, 116]) {
    const rib = new THREE.Mesh(new THREE.BoxGeometry(10, 88, 190), plateMat);
    rib.position.set(rx, STOCK.T + 22 + 44, TABLE_Z + 14 + 95);
    endFixture.add(rib);
  }
  /* 工件底部墊塊 */
  const riser = new THREE.Mesh(new THREE.BoxGeometry(104, 30, 14), plateMat);
  riser.position.set(50, STOCK.T / 2, -STOCK.L - 7);
  endFixture.add(riser);
  /* 橋式壓板 ×2：橫跨工件正面，兩端螺桿鎖回角板（避開端面加工區） */
  for (const cz of [-52, -178]) {
    const bar = new THREE.Mesh(new THREE.BoxGeometry(150, 12, 18), clampMat);
    bar.position.set(50, -6, cz);
    endFixture.add(bar);
    for (const sx of [-16, 116]) {
      const stud = new THREE.Mesh(new THREE.CylinderGeometry(4, 4, 46, 12), clampMat);
      stud.rotation.x = Math.PI / 2;                  // 軸向世界 Y
      stud.position.set(sx, 11, cz);
      endFixture.add(stud);
      const nut = new THREE.Mesh(new THREE.CylinderGeometry(7.5, 7.5, 8, 6), clampMat);
      nut.rotation.x = Math.PI / 2;
      nut.position.set(sx, -14, cz);
      endFixture.add(nut);
    }
  }
}
endFixture.visible = false;
scene.add(endFixture);

/* ---------- 工件群組（含頂面網格、側壁、底面、端面孔、刀路） ---------- */
const stockGroup = new THREE.Group();
scene.add(stockGroup);

const topGeo = new THREE.BufferGeometry();
{
  const pos = new Float32Array(NX * NY * 3);
  for (let iy = 0; iy < NY; iy++) for (let ix = 0; ix < NX; ix++) {
    const i = iy * NX + ix;
    pos[3*i] = ix * RES; pos[3*i+1] = iy * RES; pos[3*i+2] = 0;
  }
  const idx = new Uint32Array((NX - 1) * (NY - 1) * 6);
  let k = 0;
  for (let iy = 0; iy < NY - 1; iy++) for (let ix = 0; ix < NX - 1; ix++) {
    const a = iy * NX + ix, b = a + 1, c = a + NX, d = c + 1;
    idx[k++] = a; idx[k++] = b; idx[k++] = d;
    idx[k++] = a; idx[k++] = d; idx[k++] = c;
  }
  topGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  topGeo.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(NX * NY * 3), 3));
  topGeo.setAttribute('color', new THREE.BufferAttribute(Col, 3));
  topGeo.setIndex(new THREE.BufferAttribute(idx, 1));
}
stockGroup.add(new THREE.Mesh(topGeo, new THREE.MeshPhongMaterial({ vertexColors: true, shininess: 55, specular: 0x333944 })));

const walls = [];
function makeWall(count, getXY, nrm) {
  const g = new THREE.BufferGeometry();
  const pos = new Float32Array(count * 6), nor = new Float32Array(count * 6), col = new Float32Array(count * 6);
  for (let i = 0; i < count; i++) {
    const [px, py] = getXY(i);
    pos[6*i] = px; pos[6*i+1] = py; pos[6*i+2] = 0;
    pos[6*i+3] = px; pos[6*i+4] = py; pos[6*i+5] = ZMIN;
    for (const o of [0, 3]) {
      nor[6*i+o] = nrm[0]; nor[6*i+o+1] = nrm[1]; nor[6*i+o+2] = 0;
      col[6*i+o] = STEEL[0]*0.82; col[6*i+o+1] = STEEL[1]*0.82; col[6*i+o+2] = STEEL[2]*0.82;
    }
  }
  const idx = new Uint32Array((count - 1) * 6);
  let k = 0;
  for (let i = 0; i < count - 1; i++) {
    const a = 2*i, b = a+1, c = a+2, d = a+3;
    idx[k++] = a; idx[k++] = c; idx[k++] = b;
    idx[k++] = b; idx[k++] = c; idx[k++] = d;
  }
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  stockGroup.add(new THREE.Mesh(g, new THREE.MeshPhongMaterial({ vertexColors: true, shininess: 40, side: THREE.DoubleSide })));
  return g;
}
walls.push({ g: makeWall(NY, i => [0, i * RES], [-1, 0]),        hIdx: i => i * NX });
walls.push({ g: makeWall(NY, i => [STOCK.L, i * RES], [1, 0]),   hIdx: i => i * NX + NX - 1 });
walls.push({ g: makeWall(NX, i => [i * RES, 0], [0, -1]),        hIdx: i => i });
walls.push({ g: makeWall(NX, i => [i * RES, STOCK.W], [0, 1]),   hIdx: i => (NY - 1) * NX + i });
{
  const bot = new THREE.Mesh(new THREE.PlaneGeometry(STOCK.L, STOCK.W),
    new THREE.MeshPhongMaterial({ color: 0x707a85, shininess: 45, side: THREE.DoubleSide }));
  bot.position.set(STOCK.L / 2, STOCK.W / 2, ZMIN - 0.01);
  bot.rotation.x = Math.PI;
  stockGroup.add(bot);
}

function updateNormalsRegion(x0, x1, y0, y1) {
  const nor = topGeo.attributes.normal.array;
  const ax0 = Math.max(0, x0 - 1), ax1 = Math.min(NX - 1, x1 + 1);
  const ay0 = Math.max(0, y0 - 1), ay1 = Math.min(NY - 1, y1 + 1);
  for (let iy = ay0; iy <= ay1; iy++) for (let ix = ax0; ix <= ax1; ix++) {
    const i = iy * NX + ix;
    const hl = Hgt[iy * NX + Math.max(0, ix - 1)], hr = Hgt[iy * NX + Math.min(NX - 1, ix + 1)];
    const hd = Hgt[Math.max(0, iy - 1) * NX + ix], hu = Hgt[Math.min(NY - 1, iy + 1) * NX + ix];
    const nx = (hl - hr) / (2 * RES), ny = (hd - hu) / (2 * RES);
    const il = 1 / Math.sqrt(nx * nx + ny * ny + 1);
    nor[3*i] = nx * il; nor[3*i+1] = ny * il; nor[3*i+2] = il;
  }
}
function flushGeometry() {
  if (!dirty) return;
  const pos = topGeo.attributes.position.array;
  for (let iy = dirty[2]; iy <= dirty[3]; iy++)
    for (let ix = dirty[0]; ix <= dirty[1]; ix++) {
      const i = iy * NX + ix;
      pos[3*i+2] = Hgt[i];
    }
  updateNormalsRegion(dirty[0], dirty[1], dirty[2], dirty[3]);
  topGeo.attributes.position.needsUpdate = true;
  topGeo.attributes.normal.needsUpdate = true;
  topGeo.attributes.color.needsUpdate = true;
  for (const w of walls) {
    const p = w.g.attributes.position.array, n = p.length / 6;
    for (let i = 0; i < n; i++) p[6*i+2] = Hgt[w.hIdx(i)];
    w.g.attributes.position.needsUpdate = true;
  }
  dirty = null;
}

/* ---------- 端面孔（OP20/21，精確圓柱） ---------- */
const holesGroup = new THREE.Group();
stockGroup.add(holesGroup);
const holes = new Map();   // key -> {r, depth, dir, x0, py, pz, bore, cap, ring}
const boreMat = new THREE.MeshPhongMaterial({ color: 0x14171c, shininess: 10, side: THREE.DoubleSide });

function holeCut(setup, mx, my, tool, depth) {
  const t = TOOLS[tool]; if (!t || depth <= 0) return;
  const key = setup.code + ':' + mx.toFixed(1) + ',' + my.toFixed(1);
  let h = holes.get(key);
  const [px, py, pz] = setup.m2p(mx, my, 0);
  if (!h) {
    h = { r: 0, depth: 0, dir: setup.holeDir, x0: setup.holeX0, py, pz,
          bore: null, cap: null, ring: null };
    holes.set(key, h);
  }
  const toolR = t.dia / 2;
  const newR = t.type === 'tap' ? Math.max(h.r, 2.5) : Math.max(h.r, toolR);
  const newD = Math.max(h.depth, depth);
  const ringColor = t.color;
  if (newR !== h.r || !h.bore) {
    for (const m of ['bore', 'cap', 'ring']) if (h[m]) { holesGroup.remove(h[m]); h[m].geometry.dispose(); }
    const rotCap = h.dir > 0 ? -Math.PI / 2 : Math.PI / 2;
    const boreGeo = new THREE.CylinderGeometry(1, 1, 1, 20, 1, true)
      .translate(0, 0.5, 0).rotateZ(h.dir > 0 ? -Math.PI / 2 : Math.PI / 2);
    h.bore = new THREE.Mesh(boreGeo, boreMat);
    h.cap = new THREE.Mesh(new THREE.CircleGeometry(1, 20).rotateY(rotCap), boreMat);
    h.ring = new THREE.Mesh(new THREE.RingGeometry(1, 1.3, 24).rotateY(rotCap),
      new THREE.MeshBasicMaterial({ color: ringColor, side: THREE.DoubleSide }));
    for (const m of [h.bore, h.cap, h.ring]) holesGroup.add(m);
    h.r = newR;
  }
  h.ring.material.color.setHex(ringColor);
  h.depth = newD;
  h.bore.position.set(h.x0, h.py, h.pz);
  h.bore.scale.set(h.depth, h.r, h.r);
  h.cap.position.set(h.x0 + h.dir * h.depth, h.py, h.pz);
  h.cap.scale.set(1, h.r, h.r);
  h.ring.position.set(h.x0 - h.dir * 0.05, h.py, h.pz);
  h.ring.scale.set(1, h.r, h.r);
}
function clearHoles() {
  for (const h of holes.values())
    for (const m of ['bore', 'cap', 'ring']) if (h[m]) { holesGroup.remove(h[m]); h[m].geometry.dispose(); }
  holes.clear();
}

/* ---------- 切削分派 ---------- */
function carveMove(si, m, s0, s1) {
  if (m.rapid || !m.tool) return;
  const t = TOOLS[m.tool]; if (!t) return;
  if (si === 0) {
    const r = t.dia / 2;
    // 錐尖斜率：鑽/中心鑽 118°≈0.6、倒角刀 90°含角=1.0、其餘（含捨棄式平底鑽）平底
    const cone = (t.type === 'drill' || t.type === 'center') ? CONE
               : (t.type === 'chamfer') ? 1.0 : 0;
    const c = new THREE.Color(t.color);
    const az = m.z0 + (m.z1 - m.z0) * s0, bz = m.z0 + (m.z1 - m.z0) * s1;
    if (Math.min(az, bz) >= 0) return;
    carveCapsule(m.x0 + (m.x1 - m.x0) * s0, m.y0 + (m.y1 - m.y0) * s0, az,
                 m.x0 + (m.x1 - m.x0) * s1, m.y0 + (m.y1 - m.y0) * s1, bz,
                 r, cone, [c.r, c.g, c.b]);
  } else {
    const zLow = Math.min(m.z0 + (m.z1 - m.z0) * s0, m.z0 + (m.z1 - m.z0) * s1);
    if (zLow < 0) holeCut(SETUPS[si], m.x1, m.y1, m.tool, -zLow);
  }
}

/* ---------- 刀具模型（擬真外觀：依刀種程序化建構） ----------
   z=0 為刀尖切削點，往 +Z 疊到刀把。TOOLS.type 支援：
   flat 立銑刀 / ball 球刀 / drill 麻花鑽 / udrill 捨棄式快速鑽 /
   ream 鉸刀 / tap 絲攻 / center 中心鑽 / chamfer 倒角刀 /
   bore 粗搪(雙刃) / finebore 精搪(單刃微調) / face 面銑刀盤 */
let toolGroup = null, toolSpin = null;

const toolMat = {
  steel:   () => new THREE.MeshPhongMaterial({ color: 0xcdd2d9, shininess: 130, specular: 0x999999 }),
  carbide: () => new THREE.MeshPhongMaterial({ color: 0x596069, shininess: 100, specular: 0x777777 }),
  flute:   () => new THREE.MeshPhongMaterial({ color: 0x272c33, shininess: 55 }),
  gold:    () => new THREE.MeshPhongMaterial({ color: 0xd9b64e, shininess: 120, specular: 0x997722 }),
  body:    () => new THREE.MeshPhongMaterial({ color: 0x6c7480, shininess: 85 }),
  holder:  () => new THREE.MeshPhongMaterial({ color: 0x2f363e, shininess: 60 }),
};
/* 沿 Z 疊圓柱/圓錐（r0 底、r1 頂），回傳頂端 z */
function tStack(spin, r0, r1, h, z, mat, seg) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r0, h, seg || 28), mat);
  m.rotation.x = Math.PI / 2; m.position.z = z + h / 2;
  spin.add(m);
  return z + h;
}
/* 螺旋管（螺旋槽/牙紋）：radius 纏繞半徑、tubeR 管徑、z0→z1 共 turns 圈 */
function tHelix(spin, radius, tubeR, z0, z1, turns, phase, mat) {
  const pts = [], N = Math.max(16, Math.round(turns * 22));
  for (let i = 0; i <= N; i++) {
    const u = i / N, a = phase + u * turns * Math.PI * 2;
    pts.push(new THREE.Vector3(radius * Math.cos(a), radius * Math.sin(a), z0 + (z1 - z0) * u));
  }
  spin.add(new THREE.Mesh(
    new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), N, tubeR, 6, false), mat));
}
/* 縱向直槽（鉸刀等）：繞 Z 均佈 n 條細桿 */
function tStraightFlutes(spin, n, radius, tubeR, z0, len, mat) {
  for (let k = 0; k < n; k++) {
    const a = k * Math.PI * 2 / n;
    const g = new THREE.Mesh(new THREE.CylinderGeometry(tubeR, tubeR, len, 6), mat);
    g.rotation.x = Math.PI / 2;
    g.position.set(radius * Math.cos(a), radius * Math.sin(a), z0 + len / 2);
    spin.add(g);
  }
}
/* 捨棄式刀片：金色小方塊 */
function tInsert(spin, w, h, th, x, y, z, rotZ) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, th, h), toolMat.gold());
  m.position.set(x, y, z + h / 2); m.rotation.z = rotZ || 0;
  spin.add(m);
}
/* 刀尖圓錐（尖朝 -Z，尖點落在 z）：回傳頂端 z */
function tTipCone(spin, r, h, z, mat) {
  const tip = new THREE.Mesh(new THREE.ConeGeometry(r, h, 28), mat);
  tip.rotation.x = -Math.PI / 2; tip.position.z = z + h / 2;
  spin.add(tip);
  return z + h;
}

function buildTool(tn) {
  if (toolGroup) { scene.remove(toolGroup); toolGroup.traverse(o => { if (o.geometry) o.geometry.dispose(); }); }
  toolGroup = new THREE.Group();
  const t = TOOLS[tn];
  if (t) {
    const spin = new THREE.Group();
    const r = t.dia / 2, type = t.type || 'flat';
    const steel = toolMat.steel(), carbide = toolMat.carbide(), flute = toolMat.flute();
    let fl = Math.max(26, t.dia * 2.2);          // 刃長
    let shankR = Math.max(r * 0.8, 4);           // 柄徑
    let z = 0;                                   // 已疊高度

    if (type === 'drill') {                      // 麻花鑽：118° 鑽尖＋雙螺旋槽
      z = tTipCone(spin, r * 0.99, r * CONE, 0, steel);
      const top = tStack(spin, r * 0.97, r * 0.97, fl, z, steel);
      const turns = fl / (t.dia * 1.9);
      tHelix(spin, r * 0.93, r * 0.20, z + r * 0.2, top - r * 0.1, turns, 0, flute);
      tHelix(spin, r * 0.93, r * 0.20, z + r * 0.2, top - r * 0.1, turns, Math.PI, flute);
      z = top; shankR = Math.max(r, 3);
    } else if (type === 'udrill') {              // 捨棄式快速鑽：平底雙刀片＋鋼體螺旋槽
      const bodyL = Math.max(fl, t.dia * 1.6);
      tInsert(spin, r * 0.6, r * 0.42, r * 0.24, r * 0.30, 0, 0.2, 0.25);          // 中心刃
      tInsert(spin, r * 0.6, r * 0.42, r * 0.24, -(r * 0.72), 0, 0.2, -0.25);      // 外周刃
      z = tStack(spin, r * 0.95, r * 0.95, bodyL, r * 0.42, toolMat.body());
      const turns = bodyL / (t.dia * 2.6);
      tHelix(spin, r * 0.90, r * 0.13, r * 0.8, z - r * 0.2, turns, 0, flute);
      tHelix(spin, r * 0.90, r * 0.13, r * 0.8, z - r * 0.2, turns, Math.PI, flute);
      shankR = Math.max(r * 0.85, 6);
    } else if (type === 'ball') {                // 球刀：半球刃＋螺旋槽
      const ball = new THREE.Mesh(new THREE.SphereGeometry(r, 24, 16), carbide);
      ball.position.z = r; spin.add(ball);
      z = tStack(spin, r, r, fl - r, r, carbide);
      const turns = fl / (t.dia * 2.6);
      for (let k = 0; k < 2; k++) tHelix(spin, r * 0.96, r * 0.09, r, z - r * 0.1, turns, k * Math.PI, flute);
    } else if (type === 'ream') {                // 鉸刀：細長本體＋6 條直槽＋前導角
      fl = Math.max(30, t.dia * 3);
      z = tStack(spin, r * 0.88, r, r * 0.35, 0, steel);
      z = tStack(spin, r, r, fl, z, steel);
      tStraightFlutes(spin, 6, r * 0.97, Math.max(r * 0.07, 0.3), r * 0.35, fl, flute);
      shankR = Math.max(r * 0.72, 3);
    } else if (type === 'tap') {                 // 絲攻：先端錐＋牙紋螺旋＋方頭柄
      const lead = r * 1.3, thr = fl * 0.8;
      z = tStack(spin, r * 0.55, r * 0.92, lead, 0, steel);
      z = tStack(spin, r * 0.88, r * 0.88, thr, z, steel);
      const pitch = Math.max(t.dia * 0.16, 0.8);
      tHelix(spin, r * 0.93, Math.max(r * 0.09, 0.35), lead * 0.35, z - pitch * 0.5, (z - lead * 0.35) / pitch, 0, steel);
      z = tStack(spin, r * 0.55, r * 0.55, r * 1.2, z, steel);   // 頸
      shankR = Math.max(r * 0.8, 3.2);
      z = tStack(spin, shankR, shankR, 14, z, steel);
      const sq = new THREE.Mesh(new THREE.BoxGeometry(shankR * 1.15, shankR * 1.15, 5), steel);
      sq.position.z = z - 2.5; spin.add(sq);     // 方頭（傳動端）
    } else if (type === 'center') {              // 中心鑽：細導桿尖＋60° 錐＋粗本體
      const pr = Math.max(r * 0.42, 0.8);
      z = tTipCone(spin, pr, pr * 1.1, 0, steel);
      z = tStack(spin, pr, pr, pr * 2.2, z, steel);
      z = tStack(spin, pr, r, (r - pr) * 1.73, z, steel);        // 60° 錐面
      z = tStack(spin, r, r, Math.max(t.dia * 1.2, 8), z, steel);
      shankR = r;
    } else if (type === 'chamfer') {             // 倒角刀：90° 含角錐＋細頸（錐形輪廓才明顯）
      const ct = Math.max(r * 0.15, 0.6);
      z = tStack(spin, ct, r, r - ct, 0, carbide);            // 45°/邊 錐面
      z = tStack(spin, r, r, Math.max(r * 0.22, 2), z, carbide);  // 刃帶
      z = tStack(spin, r * 0.55, r * 0.55, Math.max(r * 0.9, 6), z, carbide);  // 縮頸
      shankR = Math.max(r * 0.6, 5);
    } else if (type === 'bore') {                // 粗搪：對稱雙刀片搪頭＋搪桿
      const headR = r * 0.78, headH = Math.max(t.dia * 0.35, 10);
      tInsert(spin, r * 0.30, r * 0.45, r * 0.16, r - r * 0.14, 0, 0);
      tInsert(spin, r * 0.30, r * 0.45, r * 0.16, -(r - r * 0.14), 0, 0);
      z = tStack(spin, headR, headR, headH, r * 0.18, toolMat.body());
      z = tStack(spin, Math.max(r * 0.45, 6), Math.max(r * 0.45, 6), Math.max(fl, 40), z, toolMat.body());   // 搪桿
      shankR = 0;                                // 搪桿直上刀把，不加柄
    } else if (type === 'finebore') {            // 精搪：單刃＋微調刻度環
      const headH = Math.max(t.dia * 0.4, 9);
      tInsert(spin, r * 0.26, r * 0.4, r * 0.14, r - r * 0.13, 0, 0);
      z = tStack(spin, r * 0.7, r * 0.7, headH, r * 0.16, toolMat.body());
      z = tStack(spin, r * 0.8, r * 0.8, 3.5, z,
        new THREE.MeshPhongMaterial({ color: t.color, shininess: 90 }));  // 微調環（識別色）
      z = tStack(spin, Math.max(r * 0.5, 5), Math.max(r * 0.5, 5), Math.max(fl * 0.8, 30), z, toolMat.body());   // 搪桿
      shankR = 0;
    } else if (type === 'face') {                // 面銑刀盤：盤體＋周圈刀片
      const dh = Math.max(t.dia * 0.3, 12), nIns = Math.max(4, Math.round(t.dia / 12));
      for (let k = 0; k < nIns; k++) {
        const a = k * Math.PI * 2 / nIns;
        tInsert(spin, r * 0.14, dh * 0.45, r * 0.10, (r - r * 0.06) * Math.cos(a), (r - r * 0.06) * Math.sin(a), 0, a);
      }
      z = tStack(spin, r * 0.96, r * 0.88, dh, dh * 0.12, toolMat.body(), 40);
      z = tStack(spin, Math.max(r * 0.3, 8), Math.max(r * 0.3, 8), 12, z, toolMat.holder());
      shankR = 0;
    } else {                                     // flat 立銑刀：碳化鎢＋4 刃螺旋槽
      z = tStack(spin, r, r, fl, 0, carbide);
      const turns = fl / (t.dia * 2.6);
      for (let k = 0; k < 4; k++)
        tHelix(spin, r * 0.96, Math.max(r * 0.09, 0.3), r * 0.15, z - r * 0.1, turns, k * Math.PI / 2, flute);
    }

    if (shankR > 0) z = tStack(spin, shankR, shankR, 16, z, steel);     // 柄
    const ring = new THREE.MeshPhongMaterial({ color: t.color, shininess: 90 });
    z = tStack(spin, Math.max(shankR, r * 0.5, 4) + 0.9, Math.max(shankR, r * 0.5, 4) + 0.9, 2.5, z, ring); // 識別色環
    const nutR = Math.max(shankR + 3.5, r * 0.55, 9);
    z = tStack(spin, nutR, nutR * 0.92, 10, z, toolMat.body(), 12);     // 筒夾螺帽（12 邊壓花）
    const hR = Math.max(nutR + 3, 14);
    z = tStack(spin, hR, hR, 6, z, toolMat.holder());                   // 刀把 V 型法蘭
    z = tStack(spin, hR * 0.92, hR * 0.55, 22, z, toolMat.holder());    // BT 錐柄
    toolGroup.add(spin);
    toolSpin = spin;
  }
  scene.add(toolGroup);
}
buildTool(0);

/* ---------- 刀路軌跡（存工件座標，跟著工件翻轉） ---------- */
const MAXSEG = (PROGS[0].moves.length + PROGS[1].moves.length + PROGS[2].moves.length) * 2 + 32;
const pathPos = new Float32Array(MAXSEG * 3);
const pathCol = new Float32Array(MAXSEG * 3);
let pathN = 0;
const pathGeo = new THREE.BufferGeometry();
pathGeo.setAttribute('position', new THREE.BufferAttribute(pathPos, 3));
pathGeo.setAttribute('color', new THREE.BufferAttribute(pathCol, 3));
pathGeo.setDrawRange(0, 0);
const pathLines = new THREE.LineSegments(pathGeo,
  new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55 }));
stockGroup.add(pathLines);
const RAPID_RGB = [0.88, 0.34, 0.34];
function pushPath(si, m) {
  if (pathN + 2 > MAXSEG) return;
  let rgb;
  if (m.rapid) rgb = RAPID_RGB;
  else { const c = new THREE.Color(TOOLS[m.tool] ? TOOLS[m.tool].color : 0xffffff); rgb = [c.r, c.g, c.b]; }
  const m2p = SETUPS[si].m2p;
  for (const [px, py, pz] of [m2p(m.x0, m.y0, m.z0), m2p(m.x1, m.y1, m.z1)]) {
    pathPos[3*pathN] = px; pathPos[3*pathN+1] = py; pathPos[3*pathN+2] = pz;
    pathCol[3*pathN] = rgb[0]; pathCol[3*pathN+1] = rgb[1]; pathCol[3*pathN+2] = rgb[2];
    pathN++;
  }
  pathGeo.attributes.position.needsUpdate = true;
  pathGeo.attributes.color.needsUpdate = true;
  pathGeo.setDrawRange(0, pathN);
}

/* ---------- UI 建置 ---------- */
const $ = id => document.getElementById(id);
const gpane = $('gcode');
const glinesBySetup = [];
const gfrags = PROGS.map((p, si) => {
  const frag = document.createDocumentFragment();
  const arr = [];
  p.src.forEach((s, i) => {
    const d = document.createElement('div');
    d.className = 'gl' + (/^\s*\(/.test(s) ? ' cmt' : '');
    d.innerHTML = `<span class="ln">${i + 1}</span>`;
    d.appendChild(document.createTextNode(s));
    frag.appendChild(d); arr.push(d);
  });
  glinesBySetup.push(arr);
  return frag;
});
let glines = glinesBySetup[0];
gpane.appendChild(gfrags[0]);

/* 工序清單（三工序合併，含裝夾標頭） */
const oplist = $('oplist');
const opsAll = [];
SETUPS.forEach((s, si) => {
  const h = document.createElement('div');
  h.className = 'ophead';
  h.textContent = `${s.title} — ${s.wcs}`;
  h.onclick = () => jumpToGlobal(si, 0);
  oplist.appendChild(h);
  s.headEl = h;
  PROGS[si].ops.forEach(op => {
    const d = document.createElement('div');
    d.className = 'op';
    const t = TOOLS[op.tool];
    d.innerHTML = `<span class="dot" style="background:${t ? '#' + t.color.toString(16).padStart(6, '0') : '#555'}"></span>` +
      `<span class="tno">T${op.tool || '–'}</span><span>${op.label}</span>`;
    const rec = { si, mi: op.mi, label: op.label, el: d, key: si * 1e6 + op.mi };
    d.onclick = () => jumpToGlobal(si, op.mi);
    oplist.appendChild(d);
    opsAll.push(rec);
  });
});
const legend = $('legend');
Object.entries(TOOLS).forEach(([n, t]) => {
  const d = document.createElement('div');
  d.className = 'li'; d.id = 'lg' + n;
  d.innerHTML = `<i style="background:#${t.color.toString(16).padStart(6, '0')}"></i>T${n} ${t.name}`;
  legend.appendChild(d);
});
/* 裝夾頁籤 */
const stabs = [];
SETUPS.forEach((s, si) => {
  const b = document.createElement('button');
  b.className = 'stab';
  b.textContent = s.code;
  b.title = s.title;
  b.onclick = () => jumpToGlobal(si, 0);
  $('setups').appendChild(b);
  stabs.push(b);
});

/* ---------- 模擬狀態 ---------- */
let si = 0, mi = 0, ms = 0;
let playing = false, speed = 60;
let curTool = -1, curLn = -1, curOpKey = -2;
let transition = null;   // {t: 0..1, dur, fromQ,toQ,fromP,toP, camF,camT,tgtF,tgtT, resume}
let finished = false;

function setTool(tn) {
  if (tn === curTool) return;
  curTool = tn; buildTool(tn);
  const t = TOOLS[tn];
  $('toolswatch').style.background = t ? '#' + t.color.toString(16).padStart(6, '0') : '#666';
  $('toolinfo').textContent = t ? `T${tn} ${t.name} · ${t.s}` : '待機';
  document.querySelectorAll('#legend .li').forEach(el => el.classList.remove('on'));
  const lg = $('lg' + tn); if (lg) lg.classList.add('on');
}
function applySetupUI() {
  const s = SETUPS[si];
  $('setupsub').textContent = s.sub;
  $('gtitle').textContent = 'G-code — ' + s.file;
  gpane.textContent = '';
  glines = glinesBySetup[si];
  const frag = document.createDocumentFragment();
  glines.forEach(d => frag.appendChild(d));
  gpane.appendChild(frag);
  curLn = -1;
  stabs.forEach((b, i) => {
    b.classList.toggle('cur', i === si);
    b.classList.toggle('done', i < si || (finished && i <= si));
  });
}
function snapPose() {
  const s = SETUPS[si];
  stockGroup.quaternion.copy(s.quat);
  stockGroup.position.copy(s.posV);
  flatJaws.visible = si === 0;
  endFixture.visible = si !== 0;
  grid.position.z = si === 0 ? ZMIN - 22.05 : -302.05;
  grid.position.x = si === 0 ? STOCK.L / 2 : 50;
  grid.visible = true;
}
function startTransition(nsi, dur, resume, showMsg) {
  const s = SETUPS[nsi];
  transition = {
    t: 0, dur,
    fromQ: stockGroup.quaternion.clone(), toQ: s.quat,
    fromP: stockGroup.position.clone(), toP: s.posV,
    camF: camera.position.clone(), camT: new THREE.Vector3(...s.camPos),
    tgtF: controls.target.clone(), tgtT: new THREE.Vector3(...s.camTgt),
    resume,
  };
  flatJaws.visible = false; endFixture.visible = false; grid.visible = false;
  if (showMsg && s.clampMsg) {
    $('clampmsg').innerHTML = s.clampMsg[0] + '<small>' + s.clampMsg[1] + '</small>';
    $('clampmsg').style.display = 'block';
  }
}
function tickTransition(dtMs) {
  if (!transition) return;
  transition.t += dtMs / transition.dur;
  let k = Math.min(1, transition.t);
  k = k * k * (3 - 2 * k);
  stockGroup.quaternion.copy(transition.fromQ).slerp(transition.toQ, k);
  stockGroup.position.lerpVectors(transition.fromP, transition.toP, k);
  camera.position.lerpVectors(transition.camF, transition.camT, k);
  controls.target.lerpVectors(transition.tgtF, transition.tgtT, k);
  if (transition.t >= 1) {
    const res = transition.resume;
    transition = null;
    snapPose();
    $('clampmsg').style.display = 'none';
    if (res) setPlaying(true);
  }
}

function toolAtMove(p, i) {
  if (!p.moves.length) return 0;
  return p.moves[Math.min(i, p.moves.length - 1)].tool;
}
function toolPos() {
  const p = PROGS[si];
  if (mi >= p.moves.length) {
    const m = p.moves[p.moves.length - 1];
    return [m.x1, m.y1, m.z1, m];
  }
  const m = p.moves[mi];
  return [m.x0 + (m.x1 - m.x0) * ms, m.y0 + (m.y1 - m.y0) * ms, m.z0 + (m.z1 - m.z0) * ms, m];
}
function fmt(min) {
  const s = Math.round(min * 60);
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
function updateHUD(px, py, pz, m) {
  $('drox').textContent = px.toFixed(3);
  $('droy').textContent = py.toFixed(3);
  $('droz').textContent = pz.toFixed(3);
  $('drof').textContent = SETUPS[si].wcs + (m ? (m.rapid ? ' · G0 快速' : ' · F' + m.f) : ' · F —');
  if (m && m.ln !== curLn) {
    if (curLn >= 0 && glines[curLn]) glines[curLn].classList.remove('cur');
    curLn = m.ln;
    const el = glines[curLn];
    if (el) {
      el.classList.add('cur');
      $('droln').textContent = 'N' + (curLn + 1);
      gpane.scrollTop = el.offsetTop - gpane.clientHeight / 2;
    }
  }
  const gk = si * 1e6 + mi;
  let cur = null;
  for (const op of opsAll) { if (op.key <= gk) cur = op; else break; }
  const ck = cur ? cur.key : -1;
  if (ck !== curOpKey) {
    for (const op of opsAll) {
      op.el.classList.toggle('cur', op.key === ck);
      op.el.classList.toggle('done', op.key < ck);
    }
    curOpKey = ck;
    $('opnametext').textContent = cur ? `${SETUPS[cur.si].code}｜${cur.label}` : '尚未開始';
    if (cur) cur.el.scrollIntoView({ block: 'nearest' });
  }
  const p = PROGS[si];
  const tin = mi >= p.moves.length ? p.total : (p.moves[mi].t0 + (p.moves[mi].t1 - p.moves[mi].t0) * ms);
  const t = OFF[si] + tin;
  $('progfill').style.width = (t / TOTAL * 100) + '%';
  $('timedisp').textContent = fmt(t) + ' / ' + fmt(TOTAL);
}

/* ---------- 播放 ---------- */
function step(dtMs) {
  const p = PROGS[si];
  let budget = 3200;
  let dt = dtMs / 60000 * speed;
  while (dt > 0 && mi < p.moves.length && budget > 0) {
    const m = p.moves[mi];
    const remLen = m.len * (1 - ms);
    const remT = remLen / m.f;
    if (dt >= remT) {
      carveMove(si, m, ms, 1);
      if (!m.rapid) budget -= remLen;
      pushPath(si, ms === 0 ? m : { ...m, x0: m.x0+(m.x1-m.x0)*ms, y0: m.y0+(m.y1-m.y0)*ms, z0: m.z0+(m.z1-m.z0)*ms });
      dt -= remT; mi++; ms = 0;
      if (mi < p.moves.length) setTool(p.moves[mi].tool);
    } else {
      const ns = ms + (dt / remT) * (1 - ms);
      carveMove(si, m, ms, ns);
      if (!m.rapid) budget -= m.len * (ns - ms);
      ms = ns; dt = 0;
    }
  }
  if (mi >= p.moves.length) {
    if (si < SETUPS.length - 1) {
      setPlaying(false);
      si++; mi = 0; ms = 0;
      applySetupUI();
      setTool(0);
      startTransition(si, 1600, true, true);
    } else {
      finished = true;
      setPlaying(false);
      applySetupUI();
      $('btnPlay').textContent = '✓ 全部加工完成';
    }
  }
}

/* ---------- 跳轉 ---------- */
function finishSetupInstant() {
  const p = PROGS[si];
  while (mi < p.moves.length) {
    const m = p.moves[mi];
    carveMove(si, m, ms, 1);
    if (ms === 0) pushPath(si, m);
    mi++; ms = 0;
  }
}
function hardReset() {
  resetStock(); clearHoles();
  pathN = 0; pathGeo.setDrawRange(0, 0);
  si = 0; mi = 0; ms = 0; finished = false;
  transition = null;
  $('clampmsg').style.display = 'none';
  snapPose(); applySetupUI();
  flushGeometry();
  setTool(0);
  if (curLn >= 0 && glines[curLn]) glines[curLn].classList.remove('cur');
  curLn = -1; curOpKey = -2;
}
function jumpToGlobal(tsi, tmi) {
  const back = tsi < si || (tsi === si && (tmi < mi || (tmi === mi && ms > 0)));
  const wasSi = si;
  if (back) hardReset();
  while (si < tsi) {
    finishSetupInstant();
    si++; mi = 0; ms = 0;
    applySetupUI();
  }
  const p = PROGS[si];
  while (mi < tmi && mi < p.moves.length) {
    const m = p.moves[mi];
    carveMove(si, m, ms, 1);
    if (ms === 0) pushPath(si, m);
    mi++; ms = 0;
  }
  flushGeometry();
  setTool(toolAtMove(p, mi));
  if (si !== wasSi || back) {
    applySetupUI();
    startTransition(si, 700, false, false);
  }
  setPlaying(false);
  const [px, py, pz, m] = toolPos();
  if (toolGroup) toolGroup.position.set(px, py, pz);
  updateHUD(px, py, pz, m);
}
function seekFrac(fr) {
  const t = Math.min(TOTAL - 1e-9, Math.max(0, fr * TOTAL));
  let tsi = 0;
  for (let i = SETUPS.length - 1; i >= 0; i--) if (t >= OFF[i]) { tsi = i; break; }
  const tin = t - OFF[tsi];
  let idx = PROGS[tsi].moves.findIndex(m => m.t1 >= tin);
  if (idx < 0) idx = PROGS[tsi].moves.length;
  jumpToGlobal(tsi, idx);
}
function setPlaying(pl) {
  playing = pl;
  $('btnPlay').textContent = pl ? '⏸ 暫停' : (finished ? '✓ 全部加工完成' : '▶ 開始加工');
}

/* ---------- 控制列 ---------- */
$('btnPlay').onclick = () => {
  if (finished) { hardReset(); updateHUD(0, 0, SAFE_Z, null); }
  if (transition) return;
  setPlaying(!playing);
};
$('btnReset').onclick = () => { hardReset(); setPlaying(false); updateHUD(0, 0, SAFE_Z, null); $('opnametext').textContent = '尚未開始'; };
const spd = $('speed');
function applySpeed() {
  speed = Math.round(Math.pow(10, spd.value / 100 * 3.3));
  $('speedout').textContent = '×' + speed;
}
spd.oninput = applySpeed; applySpeed();
$('progbar').onclick = e => {
  const r = e.currentTarget.getBoundingClientRect();
  seekFrac((e.clientX - r.left) / r.width);
};
$('tgPath').onchange = e => { pathLines.visible = e.target.checked; };

/* ---------- 主迴圈 ---------- */
function resize() {
  const w = vp.clientWidth, h = vp.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h; camera.updateProjectionMatrix();
}
addEventListener('resize', resize); resize();

let last = performance.now();
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(50, now - last); last = now;
  if (transition) tickTransition(dt);
  else if (playing) { step(dt); flushGeometry(); }
  const [px, py, pz, m] = toolPos();
  if (toolGroup) {
    toolGroup.position.set(px, py, pz);
    toolGroup.visible = !transition;
    if (toolSpin && playing) toolSpin.rotation.z += dt * 0.04;
  }
  if (!transition) updateHUD(px, py, pz, m);
  controls.update();
  renderer.render(scene, camera);
}
snapPose(); applySetupUI(); hardReset();
updateHUD(0, 0, SAFE_Z, null);
requestAnimationFrame(frame);
