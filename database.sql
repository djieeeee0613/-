-- 投稿審查系統 SQL 資料庫綱要與資料
-- 此檔案為系統唯一資料來源 (PostgreSQL 語法，可直接匯入 Adminer) (每次註冊 / 投稿 / 審查後都會重新產生)
-- 預設帳號: author / 123 (作者)、manager / 123 (管理員)

CREATE SCHEMA IF NOT EXISTS public;
SET search_path TO public;

DROP TABLE IF EXISTS manuscripts;
DROP TABLE IF EXISTS users;

-- 1. 使用者資料表 (作者、管理員)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,   -- 登入帳號
    password_hash VARCHAR(200) NOT NULL DEFAULT '', -- 密碼雜湊 (pbkdf2_sha256: salt$hash)
    name VARCHAR(100) NOT NULL,             -- 顯示名稱
    role VARCHAR(20) NOT NULL CHECK (role IN ('author', 'editor')), -- 角色: author(作者), editor(管理員/編輯)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 稿件資料表 (類別、標題、文章內容、審查狀態)
CREATE TABLE manuscripts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1,     -- 作者 ID (關聯 users.id)
    author_name VARCHAR(100) NOT NULL DEFAULT '王小明', -- 作者名稱
    category VARCHAR(50) NOT NULL,          -- 類別
    title VARCHAR(200) NOT NULL,            -- 標題
    content TEXT NOT NULL,                  -- 文章內容
    status VARCHAR(20) NOT NULL DEFAULT '編輯中' CHECK (status IN ('編輯中', '審查中', '已通過')), -- 稿件審查狀態
    review_comment TEXT DEFAULT NULL,       -- 編輯審查意見 / 退回備註
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 3. users 資料
INSERT INTO users (id, username, password_hash, name, role, created_at) VALUES
(1, 'author', '19f8d9c693251a93$ace1f6b9393fd0db4ff8db469060605b36b018f1149773d6baa15d2bc5e8a0c5', '王小明', 'author', '2026-11-07 16:01:04'),
(2, 'manager', '91777707d82a8769$aaf1de191ba2a3a01f5a8f928be73a1afffd277292b832df1a8a68919e7ad980', '張主編', 'editor', '2026-11-07 16:01:04'),
(3, 'test', '8393c15b892461e8$4ccbc6499774dfab4aca29c94c14cf8a379868740777754b7a8a8ea673031030', 'test', 'author', '2026-11-09 17:09:16');
SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users));

-- 4. manuscripts 資料
INSERT INTO manuscripts (id, user_id, author_name, category, title, content, status, review_comment, created_at, updated_at) VALUES
(1, 1, '王小明', '文學小說', '《山城雨霧隨筆》', '細雨如絲，悄然落在石梯與青苔上。這座老舊山城的清晨，總有著獨特的靜謐氣息。老街街角飄著豆漿與炭火烤餅的香味，早起的老人拄著竹杖緩步而過。本文描繪山城的生活光景與歲月痕跡。', '審查中', NULL, '2026-11-05 09:30:00', '2026-11-09 17:10:17'),
(2, 1, '王小明', '科技新知', '《生成式AI在現代教育中的變革與挑戰》', '生成式AI技術正徹底顛覆傳統課堂教學模式。從個人化課業輔導、虛擬助教到程式碼即時偵錯，AI賦予學習者前所未有的自主探索能力。然而，學術誠信、評量標準與數位落差問題亦隨之浮現，教育界需要更具前瞻性的指引規範。', '已通過', '審查通過', '2026-11-06 14:15:00', '2026-11-09 17:11:36'),
(3, 1, '王小明', '藝術文化', '《臺灣傳統木雕工藝之美與當代轉型》', '三義與鹿港的木雕名匠們，代代相傳著精湛的雕琢技藝。隨著生活型態改變，年輕一代工藝師嘗試結合極簡設計與實用家具，讓傳統木雕重新走入現代都會生活，展現出溫潤的人文質地。', '已通過', '審查通過', '2026-11-07 10:20:00', '2026-11-10 11:48:21'),
(4, 1, '王小明', '時事評論', '《綠色能源轉型與電網韌性評估》', '邁向淨零碳排已成全球共識。然而在提高再生能源配比的過程中，儲能系統建設與智慧電網調度策略顯得至關重要。唯有穩健的基載調控與多元電力架構，方能兼顧能源安全與環境永續。', '已通過', '論證清晰，數據翔實，同意刊登發布。', '2026-11-04 16:45:00', '2026-11-04 16:45:00');
SELECT setval(pg_get_serial_sequence('manuscripts', 'id'), (SELECT MAX(id) FROM manuscripts));
