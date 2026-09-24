# cnc-drawing-to-package — Claude Code skill

台灣 CNC 代工廠標準流程：客戶圖面（DWG/DXF/PDF/照片）→ Build123d 3D 建模 → E2E 驗證
→ G-code（依廠區設定檔）→ Techpack PPT → 網頁 3D 切削模擬器 → OpenSpec 規劃，
全部放進一個標準案件資料夾。

## 安裝

```bash
git clone https://github.com/hirosichen/cnc-drawing-to-package-skill.git \
  ~/.claude/skills/cnc-drawing-to-package
npm install -g @fission-ai/openspec
```

重開 Claude Code 後，`/cnc-drawing-to-package` 會出現在 skill 清單。

## 使用

在客戶專案資料夾內啟動 `claude`，把圖面放進資料夾後說：

> 圖面在 original_drawing.png，幫我做 3D 檔、生成 gcode、做 techpack 與切削模擬

首次會問 5 題建立該客戶的 `shop.yaml`（控制器／轉速上限／刀具庫／歸零習慣／保密要求）。

## 內容

| 路徑 | 說明 |
|---|---|
| `SKILL.md` | 流程本體 |
| `toollib/` | 廠區設定檔解析、刀具庫查詢、交付衛生檢查 |
| `core/` | 廠規稽核核心（`audit_cli.py`、`independence.py`） |
| `simulator/` | 網頁切削模擬器範本（Three.js 內嵌） |
| `shops/` | `default.yaml` 保底值、`example.yaml` 全虛構範例 |

skill 本體不含任何客戶資料；客戶事實只住客戶側 `shop.yaml`。
