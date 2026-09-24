---
name: cnc-drawing-to-package
description: 台灣CNC代工廠標準流程：客戶圖面（DWG/DXF/PDF/照片）→ Build123d 3D建模 → E2E驗證 → G-code（依廠區設定檔） → Techpack PPT → 網頁3D切削模擬器 → OpenSpec規劃，全部放進一個標準案件資料夾。當使用者貼出客戶圖面說「幫我做3D檔/生成gcode/做techpack/建檔」、要「切削模擬/livecam/mastercam那種畫面」，要「實際量測3D並標註/和圖紙比對」，或提到「照既有案例流程」「做成加工資料包」時使用。Use when the user posts a machining drawing and asks for CAD model + G-code + techpack + cutting simulation.
---

# CNC 圖面 → 加工資料包（標準流程）

使用者是台灣 CNC 代工廠服務商。每張客戶圖面做成一個獨立標準資料夾，交付完整加工資料包。
**接到圖面先查已完成案例**（客戶專案根目錄下既有案件資料夾，原圖檔名/圖號比對；
本機若有 `local/refs.yaml` 也掃其 completed_cases）——同圖已判讀過就沿用其 params.py
判讀，不要重新猜圖。`local/` 為選用的本機備忘（不隨 skill 交付），沒有就照本文件從零做。

> **交付衛生**：本 skill 會複製給不同客戶。skill 本體（SKILL.md、toollib、simulator、shops/
> default+example）不得含任何客戶名稱、廠內路徑、機台規格；那些一律住在客戶側 shop.yaml
> 或本機 `local/`（交付前整個 local/ 排除）。交付前跑 `toollib/check_distributable.py`。

## 環境（先做，勿跳過）

- Python 環境：本機若有 `local/machine.md` 照其備忘；沒有就在**客戶專案根目錄**建 venv：
  ```bash
  python3 -m venv .venv && .venv/bin/pip install build123d python-pptx pyyaml shapely matplotlib
  ```
  之後全程用 `PY=.venv/bin/python`。OpenSpec CLI：`npm install -g @fission-ai/openspec`。
- 廠規稽核核心隨 skill 附帶於 `core/`（`audit_cli.py`／`independence.py`），不需另外安裝。

## 廠區設定檔（shop profile——廠規是資料，不寫死在本文件）

每個客戶一份 `shop.yaml`，住在**客戶專案根目錄**（與其刀具庫同住）。內含：機台
（控制器/軸數/**最高轉速上限 max_rpm**/行程）、刀具庫（路徑/**是否只可用庫內刀**/材質對表）、
工件原點策略與校正用語、粗精分離與留量、輸入格式優先序、保密要求、該客戶已完成案例。
欄位示範見 `shops/example.yaml`（全虛構）。

```bash
SP=~/.claude/skills/cnc-drawing-to-package/toollib/shop_profile.py
python3 $SP resolve <案件或工作目錄>          # 解析合併結果（JSON，含 _sources 追溯）
python3 $SP snapshot <案件資料夾> [--set machines.default.max_rpm=6000]   # 開案快照
python3 $SP validate <yaml檔>                 # 檢查 schema
```

- **優先序（高→低）**：對話明講（`--set`，當場生效並問要不要回寫客戶檔）＞ 案件內快照
  `shop_profile.yaml` ＞ 自案件向上找到的客戶 `shop.yaml` ＞ skill 內 `shops/default.yaml`。
- **開案第一步就 snapshot 進案件資料夾**，之後 cad/gcode/techpack 只讀快照（離線可重跑；
  日後客戶檔改了不會默默改舊案，要套新規則就 `snapshot --force` 後重跑管線）。
- **新客戶（找不到 shop.yaml）先問 5 題建檔**：①控制器？②最高轉速限制？③有無廠內刀具庫
  （有→路徑；無→restrict_to_library:false）④歸零習慣（角落/外框分中/單邊分中）？
  ⑤有無保密要求？→ 寫成客戶專案根目錄 `shop.yaml`，同客戶之後不再問。
- profile 管**廠規**；圖面推定（ASSUMED）照舊走回確清單——兩者不混。

## 刀具庫（實廠切削參數——S/F 一律先查庫，不用經驗值猜）

廠內刀具庫是一批 zip（內含 Big5 編碼 .TAB 固定欄寬表），**路徑取自 shop.yaml 的
`tool_library.path`**（使用者對話中另給路徑則優先）。查詢工具（本 skill 附屬，輸出 JSON）：

```bash
TL=~/.claude/skills/cnc-drawing-to-package/toollib/query_toollib.py
python3 $TL --lib <刀具庫路徑> list                 # 列出所有表（刀種×材質×筆數）
python3 $TL --lib <路徑> query 鑽尾 SKD11 8.5       # 刀種+材質+直徑 → S/F/Q/刀長…
python3 $TL --lib <路徑> tap M6                     # 攻牙表（F=S×螺距 剛性攻牙）
python3 $TL --lib <路徑> tools                      # 廠內刀號登錄（T號↔H補正↔規格）
```

- 庫內刀種與對應工法：`鑽尾`（麻花鑽 G83，Q=啄鑽深；欄含中心鑽深/鑽倒角深/攻倒角深/
  盲牙鑽加深）、`高速鑽`（捨棄式快速鑽 Ø24 以上，欄含通過長=貫穿超越量）、
  `鉸刀`（G85）、`攻牙`（G84/M29）、`粗搪`/`精搪`（搪孔，精搪 Q=精搪留量）。
  S=rpm、F=mm/min（攻牙表 F=S×螺距）。
- **材質對表取 shop.yaml `material_map`**（如 S50C→SS41 表、DC53→SKD11 表）；
  map 標 `assumed: true` 的材質（庫內無直接對應）在 tool_list.md 標 `ASSUMED` 列入回確。
- 查詢若回 `warning`（庫內無該刀徑、取最近值），必須把警告原文寫進 tool_list.md 備註。
- **T 號沿用廠內登錄**：`tools` 查得到的規格直接用廠內 T 號與 H 補正。
- **app 內登錄的刀具清單 `tool_library.tools`**（shop_profile 內嵌，每筆
  t/h/type/dia/flute_len/len/max_rpm/note；`h`＝刀長補正號——T↔H 制的廠
  （同 T 換規格換 H）程式內 G43 取 `h`，`t` 空＝刀號變動、現場指定並於
  tool_list.md 醒目提醒核對）：**T 號與規格以此為準**（優先於 .TAB 的
  TOOL4 登錄），S/F 仍查 .TAB 表（無 .TAB 才慣例估值＋ASSUMED）；`len`（伸出長）
  帶入 G43 刀長檢核；刀具自身 `max_rpm` 與機台上限取 min（P1 夾速規則同）。
- **`restrict_to_library: true` 的廠：只可用庫內刀（庫＝tools ∪ .TAB）**。庫外刀
  （端銑、倒角等庫內無登錄，或規格缺門如大號絲攻）＝「需採購」，必須**三處同時醒目**：
  tool_list.md 醒目欄、README ⚠清單、Techpack 紅字頁；S/F 照機台慣例估值並標明來源 ASSUMED。
- **刀長檢核**：庫表「刀長」欄帶入 G43 安全高度檢核（verify_gcode）——刀太長會撞，
  廠內刀具模組化即為此；庫外刀無刀長資料要在回確清單提醒現場確認。
- gen_gcode.py 內把查到的參數抄成常數並註明出處表名（如 `# 鑽尾-SS41-D1: Ø8.5`），
  不要在生成時 live 查庫——資料包要能離線重跑。

## 知識 wiki（知識庫/——持續編譯的 know-how，Obsidian 相容，兩層）

markdown wiki（`[[頁名]]` 互連；資料夾即合法 Obsidian vault），**兩層**：
- **本廠層**：cases 根目錄 `知識庫/`（與本廠 shop.yaml 同層）——廠內通用
  know-how：機台特性、夾治具技巧、校正 SOP、常見問題處置。
- **客戶層**：客戶專案根目錄 `知識庫/`——該客戶專屬：符號圖例、公差慣例、
  回確結論、交付偏好。

原則：**開案先查（query，兩層都讀）、交付後寫回（ingest，分流）、順手體檢
（lint）**——知識持續編譯，不要每案重翻歷史案猜一遍。
**Ingest 分流**：廠內通用事實入本廠層、客戶專屬入客戶層；分不清時入客戶層（保守）。

- **工序型知識可畫流程圖**：製程路線、工序鏈、決策規則（如 M0 換刀）用
  ```mermaid flowchart 圍欄表達——App 知識頁與 Obsidian 都會渲染成圖；
  圖旁保留文字條列（圖給人看、文字給 AI 讀與 grep），節點標籤一律加引號。
- 結構：`index.md`（目錄，每頁一行摘要）＋`log.md`（時序紀錄）＋主題頁。
  **頁面分類由 agent 自行組織與演進**——ingest 時依知識實際形狀決定開新頁、
  寫進既有頁、併頁或拆頁（lint 順手做）；不預設固定分類、不建空白佔位頁
  （沒內容就不開頁；`[[連結]]` 指向未建頁＝標記「值得寫」）。頁間以
  `[[連結]]` 互指，index.md 隨結構同步更新。
- **Query（開案判讀前）**：兩層各讀 `index.md` 挑相關頁；wiki 記載的慣例**直接沿用**
  並標來源（`（知識庫：符號圖例）`／`（本廠知識庫：機台特性）`），該項不再列回確；
  wiki 沒有的照常判讀。
- **Ingest（交付後）**：本案**新確立**的事實寫回——回確結論（客戶裁決的
  符號/公差意義）、新慣例、材質對表補充；逐條標來源案件（`（案：E01-…）`）；
  更新 index.md 摘要行與 log.md。**推定（ASSUMED）不入 wiki**——只寫確立事實。
- **Lint（交付順手）**：新寫入與既有頁矛盾（同符號兩案不同判讀）→ 兩處都標
  `⚠待澄清`，下次開案列回確請客戶裁決，不逕自覆寫；孤兒頁（無任何 `[[連結]]`
  進出）補連結或併頁。
- **來源紀律（每條知識都可追蹤）**：每條事實必標來源——頁內以引用區塊
  `> 來源：口述 YYYY-MM-DD／檔案 <路徑>／案：<案件>` 標示（app 會特別渲染）；
  另維護 `資料來源.md` 總表頁（ingest 時登錄一列：日期｜來源｜落地位置｜影響頁面），
  讓「這條知識哪來的」一查就有。**來源檔案本體一律複製保存**（不能只留轉錄）：
  照片→`機台資料/銘牌照片/`、標準圖→`圖面判讀規則/`、表格→`刀具資料/` 等
  對應資料夾，總表登錄實際路徑。
- 衛生：知識庫住客戶資料夾（交付衛生鐵則不變）；NDA/匿名客戶的頁內
  不得出現終端客戶名（以件號代稱）。

## 標準資料夾結構

```
<件號>-<材質>-<零件名>/
├── README.md                   # 零件摘要、資料夾說明、⚠生產前必辦、保密聲明、重跑指令
├── shop_profile.yaml           # ★開案快照（generator 只讀此檔）
├── drawing/original_drawing.*  # 客戶原始圖面（建檔用，一定要複製進來；可多檔：
│                               #   original_drawing-2.* … 為同件多頁/多視角，判讀須全讀）
├── openspec/changes/<id>/      # proposal / design（含尺寸判讀表+推定表）/ specs / tasks
├── cad/
│   ├── params.py               # ★ 單一尺寸來源，所有尺寸只定義在這裡
│   ├── build_cad.py            # Build123d 建模，輸出 STEP/STL + 四視圖 png
│   └── <件號>_<名>.step/.stl + view_{top,side,end,iso}.png
├── verification/
│   ├── verify_cad.py           # 獨立重載 STEP 的幾何檢核
│   ├── verify_gcode.py         # G-code 座標/深度/結構/轉速上限/行程檢核
│   ├── visual_compare.png      # 原圖 vs 渲染視覺比對
│   └── report.md
├── gcode/
│   ├── gen_gcode.py            # 由 params.py＋shop_profile.yaml 生成，不手寫座標
│   ├── O00xx_OPxx_*.nc         # 每個工序/裝夾一支程式
│   └── tool_list.md            # 刀具表（T號、規格、S/F、限速欄、來源欄）
├── techpack/
│   ├── gen_ppt.py              # python-pptx 生成
│   └── <件號>_Techpack.pptx    # 繁中現場作業指導書（含各OP校正基準段）
├── simulation/
│   ├── <件號>-cam-sim.html     # 網頁 3D 切削模擬器（單一檔案，離線可開）
│   └── src/                    # cam_markup.html + cam_app.js（重組用原始碼）
└── measurement-3d/             # 3D 實測標註：照圖面逐標註量測（見 4b，每案必做）
    ├── measure_3d.py           # 獨立重載 STEP 逐標註實測
    ├── annotated_{top,front}_view.png  # 實測標註圖（方向對齊原圖面）
    ├── compare_with_drawing.png / report.md / measurements.json
```

## 流程

### 0. 讀圖判讀
- **輸入格式優先序照 shop.yaml `drawing_preference`（預設 DWG/DXF＞PDF＞照片）**。
  照片建檔必附警語：拍照有陰影、上下面輪廓投影重疊易誤判（把非通孔判成通孔）、
  無尺寸線的孔座標為推定——幾何置信度低，**需客戶審圖回確後才可開工**；
  可要求補 DWG/DXF 提升判讀置信度。
- 逐一列出圖面**已標尺寸**與**未標而需推定**的尺寸。推定值一律標 `ASSUMED`。
- 判讀材質與工法路線：淬硬模具鋼（SKD11/DC53 等）一律「軟態加工留磨量 → 熱處理 → 研磨」；
  預硬鋼（PDS3 等）直接加工，研磨面留磨量。
- **緊公差/色標孔＝二次加工特徵**（shop.yaml `tight_tol_hole: second-op`）：圖面標色或
  帶公差的準孔，規劃成「預鑽留量 → 精鉸/精搪」，一次鑽到位不允許；無色標之牙孔/
  一般光孔照標準工序。
- 公差用語：**1條 = 0.01mm**（客戶說 7 條 = ±0.07）。H7 等配合面：CNC 單邊留
  `grind_allowance_per_face`（預設 0.05~磨量策略見 profile），研磨到公差中間值。
- **∧/∨ 輪廓雙義陷阱**：前視圖肋/槽位的 ∧ 三線對「切入的 V 溝」與「留下的實體
  山型（三角柱、其上開放）」兩解**幾何完全相同**——不可只憑前視圖判。裁決鍵＝
  **他視圖該稜線的實/虛線型**（頂稜實線=俯視可見=實體山型；虛線=藏於材料下=溝）；
  輔以貫穿特徵的全厚虛線互相印證。實體/切除判錯＝整包重做，拿不準列 ASSUMED 回確。
- **客戶自訂符號圖例（銷孔等）**：客戶提供的符號對照圖（同一符號各家畫法不同）
  存到**客戶專案根目錄 `圖面判讀規則/`**（原檔＋判讀規則 md＋個案畫法對照表），
  並在客戶 shop.yaml notes 留指標；開案判讀前先讀。顏色類符號只有 DWG/DXF 可靠，
  照片/PDF 丟失顏色時相關判讀一律列回確。無文字標註的成組同心圓先對照銷孔圖例，
  再考慮沉頭/魚眼——別急著用投影慣例硬猜。

### 1. OpenSpec 規劃
- `openspec` 建立 change（proposal/design/specs/tasks），design.md 內放「尺寸判讀表」與「ASSUMED 推定表」。
- 跑 `openspec validate` 通過後才開始建模。

### 2. params.py（單一尺寸來源）
- 檔頭 docstring 寫明座標系與 G-code 原點約定——**原點策略取 shop.yaml
  `default_origin`**（corner-front-left 角落／stock-center 外框分中／edge-center 單邊分中），
  廠內習慣依件而異時開案問一句；機械 Z 與模型 Z 的關係一併寫明。
- 每個尺寸一行、附中文註解；推定值行尾標 `# ASSUMED`。
- **cad / gcode / techpack 全部 import params，不得重複硬編尺寸。**

### 3. Build123d 建模
- **客戶有給 3D 檔（drawing/ 內含 STP/STEP）時：直接 import 進 build123d 作為
  幾何唯一來源**——不做視覺判讀猜測、無尺寸 ASSUMED；params.py 自 STEP 量測回填；
  2D 圖面/照片僅用於公差、符號、材質、表面處理等標註比對（衝突列回確）。
  出錯率最低——客戶（如科技廠）能給 STP 就優先要 STP。
- 純 2D 案：`build_cad.py` 輸出 STEP + STL + 四張視圖（top/side/end/iso）。
- 渲染後**自己看圖**與原圖面逐特徵比對（槽、穴、孔數、倒角位置），不符就改再跑。

### 4. 案內自檢（不過就修，直到全 PASS——但這只是最低門檻，見鐵則 3）

- **檢核與生成分家（鐵則）**：案件 **SHALL NOT 自寫規則斷言**。廠規與安全規則
  （攻牙 `F=S×P`、公制底孔≈大徑−螺距、L/D→循環選型、盲孔殘餘壁厚、轉速上限、
  貫穿深含鑽尖、剛攻前置 M29、鉸孔在研磨後、非固定刀 M0）**只有一份實作**，
  住 skill 附帶的共用核心 `core/`，用 `audit_cli.py` 跑：

  ```bash
  CORE=~/.claude/skills/cnc-drawing-to-package/core
  python3 $CORE/audit_cli.py <案件資料夾> --json <案件>/verification/audit.json
  ```

  案內 `verify_gcode.py` **只放本案特有的事實斷言**（如「孔口倒角 17 孔」
  「梢孔中心距 700」「刀路涵蓋 4 沉頭位」）。判別準則：**這條斷言換一個案子還成立嗎？**
  成立＝規則（歸核心），不成立＝事實（可留案內）。
  交付前跑 `python3 $CORE/independence.py <案件>` 自檢有沒有重寫廠規；有就搬進核心或刪掉。

- `verify_cad.py`：**獨立重新載入 STEP**（不 import 建模物件），檢核 bbox、槽寬/深、孔徑、孔位、體積等，輸出 N/N PASS。
- `visual_compare.png`：原圖與渲染並排比對圖。
- 結果寫進 `verification/report.md`。

### 4b. 3D 實測標註（每案必做，與 E2E 驗證一起完成）

參考實作（本機有 `local/refs.yaml` 時）：**measure-3d**；沒有就照上述要點自寫。
與 verify_cad.py 的差別：不只 PASS/FAIL，而是**照原圖面的每一個標註**量出實測值、
畫成工程圖式的標註視圖給客戶對照（對外交付等級）。輸出放獨立資料夾 `measurement-3d/`。

- **量測**：獨立重載 STEP（不 import params），用 OCC 幾何逐面/逐孔實測：
  - 外形：bbox、指定法向平面的 center/頂點（端面高、稜線位置、削斜下緣）、面法向夾角（斜面角）。
  - 孔系：圓柱面依「半徑＋軸線」分組（同軸多片面合併），量孔徑/軸位置/軸向範圍（貫穿判定）。
  - 斜面上的孔：圖面標的是「軸線與斜面交點」，用軸線∩斜面平面求出再比對。
  - 攻牙孔模型只有底孔：量底孔徑＋鑽深，報告備註「牙型由 CAM 攻出」，勿判 FAIL。
- **判定公差照圖面精度欄**：X.XX→±0.01、X.X→±0.1、X→±0.2；圖面明標 ±0.1 者從之；
  孔位用已回確的一般位置公差。圖面自相矛盾（如標 30.00° 但座標鏈反算 29.9888°）：
  照座標建模、實測值列出差異、備註說明矛盾，公差內仍判一致。
- **標註圖**：matplotlib 畫線框（部品邊線取樣投影、丟掉一個座標軸），每個尺寸標
  「圖面值＋實測值」，綠=一致、紅=不符；**方向對齊原圖面**（invert axis 翻軸）。坑：
  - 圓柱側面無 BRep 邊線（軸向 X 的孔在俯視、軸向 Z 的孔在前視）→ 手動補虛線輪廓。
  - `invert_xaxis()` 後 text 的 ha/va 仍是螢幕方向：遠側標籤要換邊（ha left↔right），
    否則延伸線會劃過文字。
  - 字型缺字：PingFang TC 沒有 ✓（會變豆腐框）→ 用「OK/NG」。
  - 產出後**自己看圖**修標籤碰撞（標題、頂部座標鏈、引線互壓），改到乾淨為止。
- **交付**：`report.md` 逐項比對表（圖面值/實測/差/公差/判定/備註）＋
  `compare_with_drawing.png`（原圖裁切 vs 標註圖並排）＋ `measurements.json` 原始數據。

### 5. G-code（依廠區設定檔）
- **選機台**：`machines` 有 named entries（多機台廠）時，依工件行程/軸數需求選定
  目標機台（使用者對話指定優先；行程全不足→列回確）；本節所有上限/行程/控制器
  取**該台**值（未列的鍵承襲 default），Techpack 首頁與 README 記載目標機台。
- 控制器照選定機台 `controller`（fanuc-0i-mf：G43 刀長補正、G83 啄鑽、G84 剛性攻牙 M29、
  G85 鉸孔、口袋斜坡下刀；三菱/Siemens 模板待有實機需求再加——非 FANUC 機台被選中時
  要在 README/Techpack 醒目標註「程式模板為 FANUC 慣例，上機前需現場轉換確認」）。
- **夾具（fixtures）**：shop_profile `fixtures.items` 有登錄時，每個裝夾自庫選用
  （`default` 優先；**工件寬 > max_opening 換開口足夠的夾具**，全不足→列回確）；
  安全高度/下刀規劃**避讓 `clamp_height`**（verify_gcode 一併檢核），Techpack 各 OP
  裝夾段記載選用夾具代號與開口設定。無登錄照舊：虎鉗假設＋ASSUMED 列回確。
- **轉速上限（P1）**：所有 S 值 = `min(庫值/慣例值, machines.max_rpm)`。**被夾到上限的刀，
  F 按轉速等比例下修**（保持每刃進給不變，防燒刀）；tool_list.md 加「限速」欄記
  原值→夾後值；gen_gcode.py 內把 MAX_RPM 抄成常數註明出處（shop_profile.yaml）。
- 慣例：沉頭/精孔可用小一號刀圓弧插補避免讓刀；H7 面程式內建磨量（profile 留量值）。
- **粗/精分離（P4）**：`rough_finish_split: true` 時一般外形粗銑壁留
  `rough_wall_allowance`（預設 0.2）→ 精修；緊公差孔照流程 0 的二次加工規劃。
- 每個裝夾一支程式（頂面 OP10、端面 OP20/OP21…），`tool_list.md` 列 T 號/規格/S/F/
  限速/來源欄。
- **S/F 與 T 號先查刀具庫**（見「刀具庫」節）：孔加工類（鑽/鉸/攻/搪）一律用庫值；
  庫外刀種或無對應材質才用慣例估值並標 ASSUMED（restrict_to_library 廠＝需採購三處醒目）。
- `verify_gcode.py` 檢核：孔位座標、深度、程式結構＋**任何 S > max_rpm 判 FAIL**、
  **XY 座標超 travel 判 FAIL**、G43 安全高度對庫表刀長檢核，輸出 N/N PASS。

### 5b. Mastercam 交棒（客戶用 Mastercam 時做；參考實作 refs → mastercam-import）
- 案件加 `mastercam/export_mastercam.py`：讀 **params.py＋shop_profile.yaml**（尺寸唯一
  來源不變），匯出 `mastercam/package.json`——中性交棒格式 **schema `mc-package/1`**，
  頂層鍵：`part / coordinate / stock / levels / tools / geometry / operations / not_imported`。
  - 座標一律 **G-code 座標**（同 gen_gcode.py 原點），深度/磨量補償同式；
    槽/外形輪廓一律 **CCW** 匯出（Mastercam 端串連方向可預期）。
  - 匯不進去的特徵（角落 C1、翻面 OP 等）列 `not_imported`，外掛總結對話框會提示現場手建。
  - **自檢**：孔數/輪廓段數/刀具數/深度逐項對 gen_gcode.py 比對，PASS 才交棒。
- Mastercam 端由 **BestAI CAM NET-Hook 外掛**（組件名 BestAICam，原名 McPackageImport；通用，與案件無關）匯入：
  機床群組→素材→分層幾何→刀具(T/H 照 tool_list)→鑽/攻/挖槽/外形工法→Regenerate。
  外掛開發與常駐部署見 **mastercam-nethook skill**（含 FT 註冊三陷阱與 scaffold）。
- 匯入後現場必核對：Pocket 步距/壁留/下刀為 Mastercam 預設值需開參數頁確認、
  補正方向 Backplot 確認、Verify 手動跑、後處理 NC 與案件 `gcode/*.nc` 逐段比對。

### 6. Techpack PPT（繁中）
- `gen_ppt.py` 生成給現場員工的作業指導書：零件概要、工序流程、裝夾示意、逐工序刀具/轉速/進給、
  量測重點（H7 面、磨量）、**紅字「圖面未載明需客戶回確」清單（編號 A1..An）**＋
  庫外刀需採購紅字。
- **各 OP 首頁加「校正基準」段（P3）**：本工序歸零點（照 params.py 原點宣告）、壓板/
  夾持位置、何時校水平（取 shop.yaml `leveling` 用語：如「每工序裝夾後校水平；
  翻面/立夾必重校」）。
- **「驗證程度」頁（必加，與 README 同源）**：把流程 8 那段做成一頁；
  **「本程式從未上機」與 ❌ 三項上機前必辦一律紅字**——現場師傅拿到的是這份簡報，
  不是 README，他必須看得到這條程式驗到哪、還缺什麼才能開。
- 生成後轉 PDF **逐頁目檢版面**（文字溢出、圖片位置），有問題修 gen_ppt.py 重生成。

### 7. 網頁切削模擬器（Mastercam 式驗證畫面）
- 以本 skill 資料夾 `simulator/` 的範本為基礎（本機有 `local/refs.yaml` 時可參考 first-full-package）：
  - `cam_markup.template.html`：UI 版面（深色 CAM HMI 風、繁中、含手機斷點），改標題/零件資訊即可。
  - `cam_app.template.js`：G-code 解析（G0/G1/G2/G3 含**螺旋帶Z**與**只給I/J的整圓**、
    G81/G82/G83/G84/G85 固定循環）＋高度場材料移除＋播放控制。每個案子需要改的只有頂部區塊：
    `STOCK`（素材尺寸）、`TOOLS`（刀具表：直徑/類型/轉速/顏色）、
    刀具 `type` 支援擬真外觀：`flat` 立銑刀(4刃螺旋)/`ball` 球刀/`drill` 麻花鑽(118°尖+雙螺旋槽)/
    `udrill` 捨棄式快速鑽(平底+雙刀片)/`ream` 鉸刀(直槽)/`tap` 絲攻(牙紋+方頭)/`center` 中心鑽/
    `chamfer` 倒角刀(90°錐)/`bore` 粗搪(雙刃搪頭)/`finebore` 精搪(單刃+微調環)/`face` 面銑刀盤——
    **依 tool_list.md 選對 type**（鉸刀標成 drill 會多出鑽尖，客戶一眼看穿）；高度場錐尖斜率
    已依 type 自動取值（drill/center 0.6、chamfer 1.0、其餘平底）、
    `SETUPS`（每個裝夾的 NC 檔、機械↔部品座標映射 `m2p`、工件姿態 `basis/pos`、鏡頭 `camPos/camTgt`）。
- **先 grep 全部 NC 檔比對解析器支援清單**（`G8[0-9]`、`G0[23]`、`G4[13]`、`G68`、`G91` 等），
  有不支援的語法先補解析器再組裝——缺語法不會報錯，會**默默不切或亂切**
  （hardened-3op 教訓：`G3 I-7.2` 整圓曾被「無座標字跳過」規則丟棄，大沉穴整個沒挖）。
- 呈現原則：主裝夾用高度場逐刀削料＋逐刀著色；翻面裝夾依內容選擇——端面鑽攻類
  （first-full-package）用精確圓柱孔；**背面倒角/淺加工類（hardened-3op）加第二片
  「底面高度場」**（翻面後往上切，牆面下緣跟著底面場更新）；工序間做「重新裝夾」
  翻轉動畫，前工序切削結果保留在工件上跟著翻。
- **車床件用「軸向切片雙輪廓場」變體**（本機有 `local/refs.yaml` 時可參考 lathe）：
  Router[]/Rinner[] 每切片外/內半徑＋逐刀色，旋轉網格由輪廓走訪重建（法向量必須由
  **輪廓切線**算，端面/半徑階梯才不會全黑）；解析器 lathe 模式（X=直徑、U/W 增量、
  T0101 換刀、F mm/rev×節奏比例）；OD/面車刀做「前方掃描填充」、搪/鑽只切當前切片；
  **每刀後跑「斷面分離落料」**（自夾持側走訪，越過全斷截面的材料清除，否則面車貫通後
  會殘留幽靈料環）。三爪卡盤 CylinderGeometry 預設軸向是 Y——立式(VMC) 要
  rotation.x=π/2，臥式(車床)要 rotation.z=π/2，忘了轉會變成插在工件上的大圓盤。
  **OD/端面車刀模型：刀柄徑向朝外（+r 往刀塔）、整體偏「已加工側」（機械+Z）幾 mm、
  各件交疊無縫、只有刀尖一小片彩色刀片**——兩種都錯過：沿軸向水平的柄，縱車時刀尖騎在
  外圓母線上會有半根埋進料裡；貼著刀尖平面的徑向柄，面車時會掃到前方未車除的料
  （lathe 案客戶連抓兩次包的教訓）。搪桿/U鑽是軸向工具，桿身沿 +Z 走孔內屬正常。
- 淬硬鋼「熱處理＋研磨」夾在兩工序之間時，做成轉場事件：頂/底面高度場各削去磨量、
  換研磨面色（保留更深的既有特徵），轉場訊息寫明 HRC 與研磨尺寸（hardened-3op 參考）。
- **傾斜治具（正弦虎鉗）姿態的銑削：每柱切到 max(刀底平面, 刀圓柱近側牆面) 的統一公式**
  （sine-vise 參考實作）——面銑取平面項、側銑垂直牆取牆項（牆＝部品內的陡斜平面），
  分層側銑自動接到牆底角；足跡判定要用「切削點高度」的機械座標，牆上緣才不會漏切。
  **程式裡有的切削不可只顯示刀路不削料**——最終形狀少一面精修，客戶一眼就抓包。
- 刀具建議：倒角/雕刻刀在 TOOLS 用**有效切削徑**（如 Ø12 45° 倒角刀切深 2 時有效 Ø6）
  而非柄徑，錐角係數 1.0；否則高度場切痕過寬。
- **鐵則：`SETUPS.basis`（部品→世界）與 `m2p`（機械→部品）必須是右手系旋轉**——
  左手系（鏡射）映射物理上不存在，會產生歪斜的不可能姿態。驗證：三個 basis 向量
  `ex×ey` 必須等於 `ez`。翻面後機械軸常會對到部品軸的**反向**。
- 組裝（Three.js 與 NC 內容全部內嵌，成品離線可開、可發 Artifact 給客戶看）：
  ```bash
  python3 ~/.claude/skills/cnc-drawing-to-package/simulator/assemble.py \
    --markup cam_markup.html --app cam_app.js \
    --nc NC0=gcode/O0010_OP10_TOP.nc --nc NC20=gcode/O0020_....nc \
    --out simulation/<件號>-cam-sim.html
  ```
  markup/app 在 scratchpad 改好後，**複製一份進 `simulation/src/`**（README 的重跑指令
  指向它；scratchpad 是 session 專屬，不留檔日後無法重組）。成品進 `simulation/`。
- 交付前必測：本地 server 開頁（勿用 file://）、播放全程含自動翻面、工序跳轉、
  進度條快轉、console 無錯誤；G-code 檢核 PASS 後最終形狀應與 STEP 一致。
- 測試注意：無頭瀏覽器對同一大型 WebGL 頁多次 navigate 會累積退化到個位數 fps
  （SwiftShader context 堆積）——變慢先關分頁開新分頁再量，勿誤判成程式問題。
- 交付時明講：「請開 `simulation/<件號>-cam-sim.html`（約幾百 KB 那個），
  `src/` 內是原始碼殼、按鈕不會動」——使用者開錯檔會回報「沒有按鈕可以按」。

### 8. README + 交付總結
- README.md：零件摘要、檔案表、⚠生產前必辦（回確清單＋庫外刀需採購）、重跑指令。
- **「本資料包的驗證程度」段（必載，README／Techpack／App 三處同源）**：
  數字取自 `verification/audit.json`（共用核心產出），**不是固定文案**——
  兩個案子結果不同，這段就必須不同。

  ```
  本資料包的驗證程度
  ─────────────────────────────────
  ✅ 已完成
     案內自檢（幾何 30/30・實測 36/36・G-code N/N）
       ⚠ 由產出本案的同一次作業自己寫，不具技術獨立性（IEEE 1012）
     廠規斷言稽核（共用核心 v<版本>）  R1..R10  FAIL 0 / WARN 13 / NA 7
  ⚠ 無法檢核 7 項——查不了不等於通過：
     R4 盲孔殘餘壁厚｜OP30／OP31 側面工序：Z 打進的不是板厚…
  ❌ 尚未進行（上機前必辦，缺一不可）
     獨立 G-code 驗證（Vericut 等：驗 post 後真的要跑的碼，含機台/夾具/行程）
     機上空跑（Z 偏移＋低快速倍率＋單節執行，開門看刀尖）
     首件檢驗
  ─────────────────────────────────
  ⚠ 本程式從未上機。
  ```

  **「無法檢核」必須逐條列原因**——那是最容易被讀成「沒問題」的一欄。
- **回確表固定四欄** `| # | 項目 | 推定值 | 圖 |`：每題產一張**位置示意圖**
  `confirm/<編號>.png`（從 `drawing/original_drawing.png` 裁切該特徵局部＋紅框/紅圈
  標出位置，matplotlib 即可；一題多處全框），圖欄填 `![](confirm/A1.png)`。
  BestAI CAM 回確卡會顯示推定值與縮圖——現場師傅要能一眼看出「這題在圖上講哪裡」。
  找不到對應區域的抽象題（如一般公差）圖欄留空。
- **保密聲明段（P6）**：shop.yaml `nda: true` 時 README 加「本資料包與原始圖面屬客戶
  機密，不得提供第三方或外流」；`anonymize: true` 時檔名/報告以件號代客戶名稱、
  報告不出現客戶名。
- 最後回覆使用者：交付表格 + 公差策略 + **醒目警告哪些尺寸是推定、回確前不得開工**
  + **驗證程度摘要**（已完成／無法檢核／尚未進行三段，並明講從未上機）。
  不得以「驗證完成」「可直接開工」作結——見鐵則 3。

## 尺寸變更時的重跑管線

```bash
PY=.venv/bin/python   # 客戶專案根目錄 venv（見「環境」節）
$PY cad/build_cad.py
$PY verification/verify_cad.py
$PY gcode/gen_gcode.py
$PY verification/verify_gcode.py
$PY techpack/gen_ppt.py
$PY measurement-3d/measure_3d.py
```

改尺寸只改 `cad/params.py`，跑完全部同步。**G-code 有變動時，模擬器 HTML 也要重跑
`simulator/assemble.py` 重組**（NC 內容是內嵌的，不會自動更新）。
廠規變更（如換機台改轉速上限）：改客戶 shop.yaml → `shop_profile.py snapshot --force`
→ 重跑管線。

## 鐵則

1. 推定尺寸必標 ASSUMED 並集中列表，回確前不得開工——這是客戶明確要求。
2. 原始圖面一定複製到 `drawing/` 附在資料包內（建檔用）。
3. **案內自檢四項（幾何檢核／G-code 檢核／視覺比對／3D 實測標註）全 PASS 是交付的
   最低門檻，不是「驗證完成」。** 這四項都由產出本案的同一次作業自己寫，依 IEEE 1012
   不具技術獨立性——它抓得到「做的跟想的不一樣」（數量／座標算錯），抓不到「想錯了」
   （深度公式、循環選型、廠規理解錯誤）。故交付物一律另載「驗證程度」段（見流程 8），
   明列**尚未進行**的獨立 G-code 驗證／機上空跑／首件檢驗，並明講本程式從未上機。
   **禁止**在 README、Techpack 或對使用者的回覆中出現「驗證完成」「可直接開工」
   「全部通過」這類會被讀成充分條件的表述。
4. 全程繁體中文（程式註解、報告、PPT、回覆）。
5. 孔加工類（鑽/鉸/攻/搪）的 S/F 與 T 號一律查廠內刀具庫（見「刀具庫」節），不用經驗值猜；
   庫內沒有的才估值並標 ASSUMED。
6. **開案先解析廠區設定檔並快照**；S 值一律 ≤ max_rpm（夾速時 F 等比例下修）；
   restrict_to_library 廠的庫外刀三處醒目標示需採購。
7. **skill 本體不留客戶資料**：客戶事實只進客戶側 shop.yaml 與 `local/`（不隨 skill 交付）；
   交付前跑 `toollib/check_distributable.py` 過了才能給。
