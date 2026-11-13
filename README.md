# 投稿審查系統 (Python + SQL + HTML 雙分頁同步版)

本專案採用 **純 Python (`app.py`)** 搭配 **SQL 資料庫 (`database.sql` / `sqlite3`)** 與 **HTML5/CSS3 前端模板 (`templates/`)** 實作，**無須安裝任何第三方套件**，支援在同一個瀏覽器開啟兩個分頁同時操作「作者端」與「管理員/編輯端」！

---

## ✨ 本次更新重點

1. **首頁改為雙按鈕直達入口**：
   - 造訪首頁 `http://localhost:8000` 時，直接呈現 **「✍️ 作者介面」** 與 **「🔍 管理員 / 編輯介面」** 兩個大型入口按鈕，點擊即可直接進入對應工作台，無須繁瑣輸入帳密。
2. **支援多瀏覽器分頁同時操作（角色完全隔離、不互搶 Session）**：
   - 解決了傳統 Cookie Session 在同一瀏覽器開兩個分頁時，後登入的角色會覆蓋前一個分頁角色的問題。
   - 現在 **分頁 1 (`/author`)** 永遠鎖定為作者角色，**分頁 2 (`/editor`)** 永遠鎖定為編輯角色。
   - 當您在作者分頁點擊「送出審查」後，切換到編輯分頁按「重新整理 (F5)」或點擊右上角「🔄 刷新清單狀態」，即可立即看到剛送出的待審稿件，而且兩個分頁都不會發生角色跳轉！

---

## 🚀 本機執行步驟

1. 解壓縮 `submission_system_py.zip`。
2. 在終端機（CMD / PowerShell / Terminal）進入資料夾並執行**重設資料庫**（更新新版資料表結構）：
   ```bash
   cd submission_system_py
   python init_db.py
   ```
3. 啟動伺服器：
   ```bash
   python app.py
   ```
4. 打開瀏覽器：
   - 首頁入口：`http://localhost:8000`
   - 分頁 A（作者端）：`http://localhost:8000/author`
   - 分頁 B（管理員/編輯端）：`http://localhost:8000/editor`
