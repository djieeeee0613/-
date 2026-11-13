#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投稿審查系統 - SQL 資料庫初始化 / 同步程式
不再有 database.db 檔：啟動時把 database.sql 載入記憶體中的 SQLite，
每次寫入後 export_sql() 把全部資料寫回 database.sql。
database.sql 採 PostgreSQL 語法，可直接用 Adminer 匯入；載入記憶體時會自動轉成 SQLite 語法。
"""

import os
import hashlib
import hmac
import secrets
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQL_PATH = os.path.join(BASE_DIR, "database.sql")

SCHEMA_SQL = """-- 投稿審查系統 SQL 資料庫綱要與資料
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
"""

TABLE_ORDER = ["users", "manuscripts"]


def hash_password(password: str, salt: str = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), stored)


def _sql_literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def export_sql():
    """把資料庫目前內容傾印成 database.sql (綱要 + INSERT)，寫入暫存檔後再取代，避免寫到一半損毀"""
    conn = get_conn()
    parts = [SCHEMA_SQL]
    for i, table in enumerate(TABLE_ORDER, start=3):
        cur = conn.execute(f"SELECT * FROM {table} ORDER BY id")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        parts.append(f"\n-- {i}. {table} 資料\n")
        if rows:
            values = ",\n".join("(" + ", ".join(_sql_literal(v) for v in r) + ")" for r in rows)
            parts.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{values};\n")
            parts.append(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}));\n")
    tmp = SQL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(parts))
    os.replace(tmp, SQL_PATH)



def _to_sqlite(sql: str) -> str:
    """PostgreSQL 語法 -> SQLite 語法 (僅需轉換少數語法)"""
    sql = sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("TIMESTAMP", "DATETIME")
    return "\n".join(l for l in sql.splitlines() if not l.startswith(("SELECT setval", "SET ", "CREATE SCHEMA")))


class _Shared:
    """共用同一個記憶體連線；呼叫 close() 不會真的關閉"""
    def __init__(self, conn):
        self._c = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._c, name)


_CONN = None


def get_conn():
    global _CONN
    if _CONN is None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        with open(SQL_PATH, "r", encoding="utf-8") as f:
            conn.executescript(_to_sqlite(f.read()))
        conn.commit()
        _CONN = _Shared(conn)
    return _CONN


def init_database(force_reset=False):
    """載入 database.sql 並以 PostgreSQL 格式重新寫回 (確保格式統一)"""
    get_conn()
    export_sql()
    print(f"[完成] 資料已從 {SQL_PATH} 載入 (無 .db 檔，資料變更會直接寫回此 SQL 檔)")


if __name__ == "__main__":
    init_database()
