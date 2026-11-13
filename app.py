#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投稿審查系統 (Submission Review System) - Python Web 後端與 HTML 渲染系統
========================================================================
更新重點：
1. 首頁 (/) 改為簡潔的「作者介面」與「管理員/編輯介面」兩個直達按鈕，免輸入帳密。
2. 採用「URL 路由角色隔離機制」取代單一瀏覽器共享 Cookie：
   - 分頁 A 開啟 `/author` 永遠保持【作者身份】
   - 分頁 B 開啟 `/editor` 永遠保持【管理員/編輯身份】
   在任一分頁點擊按鈕、送出表單或重新整理，都絕對不會把另一個分頁洗成相同角色，完美支援雙分頁同步模擬！

執行方式：
  python app.py
  或
  python3 app.py
接著開啟瀏覽器造訪 http://localhost:8000
"""

import os
import sys
import html
import sqlite3
import webbrowser
import secrets
from http.cookies import SimpleCookie
from datetime import datetime
from urllib.parse import parse_qs, urlparse, quote, unquote
from http.server import HTTPServer, BaseHTTPRequestHandler

from init_db import init_database, export_sql, hash_password, verify_password, get_conn, BASE_DIR

# 登入狀態：每個角色各用一個 Cookie (author_sid / editor_sid)，
# 因此同一瀏覽器可同時以作者與管理員身份開兩個分頁，互不覆蓋。
SESSIONS = {}  # token -> user_id
COOKIE_NAMES = {"author": "author_sid", "editor": "editor_sid"}

CATEGORIES = ['文學小說', '科技新知', '藝術文化', '時事評論', '綜合生活', '學術研究', '商業財經']


def get_db():
    """取得 SQLite 資料庫連線，並以 Row 字典格式回傳查詢結果"""
    return get_conn()


def esc(val) -> str:
    """防範 XSS 的 HTML 轉義輔助函式"""
    if val is None:
        return ""
    return html.escape(str(val), quote=True)


def load_template(name: str) -> str:
    path = os.path.join(BASE_DIR, "templates", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def render_status_badge(status: str) -> str:
    if status == '編輯中':
        return '<span class="badge-status badge-draft">✏️ 編輯中</span>'
    elif status == '審查中':
        return '<span class="badge-status badge-review">⏳ 審查中</span>'
    elif status == '已通過':
        return '<span class="badge-status badge-approved">✅ 已通過</span>'
    return esc(status)


def render_page(page_title: str, content_html: str, role=None, flash=None, user=None) -> bytes:
    """將頁面內容嵌入 templates/layout.html，依當前分頁路由決定角色顯示，不依賴共享 Cookie"""
    layout = load_template("layout.html")

    uname = esc(user["name"]) if user else ""
    if role == "author":
        nav_role_class = "role-author"
        nav_user_block = f"""
        <div class="nav-user">
          <span class="role-badge author">✍️ 當前分頁身份：作者 ({uname})</span>
          <a href="/editor" target="_blank" class="btn btn-sm btn-outline" title="在新分頁開啟編輯後台">↗ 開啟編輯分頁</a>
          <a href="/" class="btn btn-sm btn-outline">返回首頁</a>
          <a href="/logout?role=author" class="btn btn-sm btn-danger">登出</a>
        </div>
        """
    elif role == "editor":
        nav_role_class = "role-editor"
        nav_user_block = f"""
        <div class="nav-user">
          <span class="role-badge editor">🔍 當前分頁身份：管理員 ({uname})</span>
          <a href="/author" target="_blank" class="btn btn-sm btn-outline" title="在新分頁開啟作者後台">↗ 開啟作者分頁</a>
          <a href="/" class="btn btn-sm btn-outline">返回首頁</a>
          <a href="/logout?role=editor" class="btn btn-sm btn-danger">登出</a>
        </div>
        """
    else:
        nav_role_class = ""
        nav_user_block = """
        <div class="nav-user">
          <a href="/login" class="btn btn-sm btn-outline">登入</a>
          <a href="/register" class="btn btn-sm btn-primary">註冊</a>
        </div>
        """

    if flash and flash.get("message"):
        flash_block = f"""
        <div class="alert alert-{esc(flash.get('type', 'info'))}">
          <span>{esc(flash['message'])}</span>
        </div>
        """
    else:
        flash_block = ""

    full_html = (
        layout.replace("{{page_title}}", esc(page_title))
        .replace("{{nav_role_class}}", nav_role_class)
        .replace("{{nav_user_block}}", nav_user_block)
        .replace("{{flash_block}}", flash_block)
        .replace("{{content_block}}", content_html)
    )
    return full_html.encode("utf-8")


class SubmissionRequestHandler(BaseHTTPRequestHandler):
    """處理 HTTP GET 與 POST 請求的核心控制器 (支援多分頁角色獨立運作)"""

    def log_message(self, format, *args):
        sys.stdout.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def send_html(self, html_bytes: bytes, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.end_headers()
        self.wfile.write(html_bytes)

    def redirect(self, location: str, msg_type: str = None, message: str = None):
        if message:
            sep = "&" if "?" in location else "?"
            location = f"{location}{sep}msg_type={quote(msg_type or 'info')}&msg={quote(message)}"
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()

    def current_user(self, role):
        """依該角色的 Cookie 取得登入使用者 (未登入回傳 None)"""
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return None
        morsel = jar.get(COOKIE_NAMES[role])
        uid = SESSIONS.get(morsel.value) if morsel else None
        if uid is None:
            return None
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        conn.close()
        return user if user and user["role"] == role else None

    def redirect_with_cookie(self, location, cookie_name, token):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        if token is None:
            self.send_header("Set-Cookie", f"{cookie_name}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        else:
            self.send_header("Set-Cookie", f"{cookie_name}={token}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()

    def parse_post_data(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        parsed = parse_qs(raw_body, keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}

    # ---------------- GET 路由分發 ----------------
    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = {k: v[0] for k, v in parse_qs(parsed_url.query).items()}

        flash = None
        if "msg" in query:
            flash = {
                "type": query.get("msg_type", "info"),
                "message": unquote(query["msg"])
            }

        # 1. 靜態檔案 (CSS)
        if path == "/static/style.css":
            css_path = os.path.join(BASE_DIR, "static", "style.css")
            with open(css_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # 2. 首頁 / 登入選擇頁 (兩個大按鈕直接進入作者或管理員/編輯介面)
        if path == "/":
            tpl = load_template("login.html")
            return self.send_html(render_page("首頁", tpl, role=None, flash=flash))

        if path == "/login":
            return self.send_html(render_page("登入", load_template("login.html"), flash=flash))

        if path == "/register":
            return self.send_html(render_page("註冊", load_template("auth_register.html"), flash=flash))

        if path == "/logout":
            role = query.get("role", "")
            if role not in COOKIE_NAMES:
                return self.redirect("/")
            jar = SimpleCookie()
            try:
                jar.load(self.headers.get("Cookie", ""))
            except Exception:
                pass
            morsel = jar.get(COOKIE_NAMES[role])
            if morsel:
                SESSIONS.pop(morsel.value, None)
            return self.redirect_with_cookie("/login?msg_type=success&msg=" + quote("已登出。"), COOKIE_NAMES[role], None)

        # ---------------- 作者專區路由 (固定為作者角色，刷新或操作皆留在作者介面) ----------------
        if path.startswith("/author"):
            user = self.current_user("author")
            if not user:
                return self.redirect("/login", "warning", "請先以作者帳號登入。")
            # 3.1 查看投稿稿件清單 (類別、標題、審查狀態)
            if path == "/author":
                conn = get_db()
                rows = conn.execute("SELECT * FROM manuscripts WHERE user_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
                conn.close()

                count_total = len(rows)
                count_draft = sum(1 for r in rows if r["status"] == "編輯中")
                count_review = sum(1 for r in rows if r["status"] == "審查中")
                count_approved = sum(1 for r in rows if r["status"] == "已通過")

                if not rows:
                    table_rows = """
                    <tr>
                      <td colspan="6" style="text-align: center; padding: 3rem; color: var(--secondary);">
                        尚無投稿稿件，歡迎點擊右上角「新增投稿」開始撰寫！
                      </td>
                    </tr>
                    """
                else:
                    tr_list = []
                    for r in rows:
                        mid = r["id"]
                        title_esc = esc(r["title"])
                        comment_html = ""
                        if r["review_comment"]:
                            comment_html = f'<div style="font-size: 0.8rem; color: #b45309; margin-top: 0.25rem;">💬 審查意見：{esc(r["review_comment"])}</div>'

                        if r["status"] == "編輯中":
                            ops_html = f"""
                            <a href="/author/edit?id={mid}" class="btn btn-sm btn-primary">編輯</a>
                            <form method="POST" action="/author/submit" style="margin: 0;" onsubmit="return confirm('確定要將《{title_esc}》送出審查嗎？狀態將變更為「審查中」。');">
                              <input type="hidden" name="id" value="{mid}">
                              <button type="submit" class="btn btn-sm btn-warning">送出審查</button>
                            </form>
                            <form method="POST" action="/author/delete" style="margin: 0;" onsubmit="return confirm('確定要刪除編輯中稿件《{title_esc}》嗎？');">
                              <input type="hidden" name="id" value="{mid}">
                              <button type="submit" class="btn btn-sm btn-danger">刪除</button>
                            </form>
                            """
                        else:
                            ops_html = '<span style="font-size: 0.8rem; color: var(--secondary); padding: 0.2rem 0.5rem; background: var(--gray-100); border-radius: 4px;">已鎖定修改</span>'

                        tr_list.append(f"""
                        <tr>
                          <td style="color: var(--secondary); font-weight: 500;">#{mid}</td>
                          <td><span class="badge-cat">{esc(r['category'])}</span></td>
                          <td>
                            <div style="font-weight: 600; font-size: 1rem;">
                              <a href="/author/view?id={mid}" style="color: inherit; text-decoration: none;">{title_esc}</a>
                            </div>
                            {comment_html}
                          </td>
                          <td style="text-align: center;">{render_status_badge(r['status'])}</td>
                          <td style="font-size: 0.85rem; color: var(--secondary);">{esc(r['updated_at'])}</td>
                          <td style="text-align: right;">
                            <div style="display: inline-flex; gap: 0.35rem; align-items: center;">
                              <a href="/author/view?id={mid}" class="btn btn-sm btn-outline">檢視</a>
                              {ops_html}
                            </div>
                          </td>
                        </tr>
                        """)
                    table_rows = "\n".join(tr_list)

                tpl = load_template("author_dashboard.html")
                html_content = (
                    tpl.replace("{{count_total}}", str(count_total))
                    .replace("{{count_draft}}", str(count_draft))
                    .replace("{{count_review}}", str(count_review))
                    .replace("{{count_approved}}", str(count_approved))
                    .replace("{{table_rows}}", table_rows)
                )
                return self.send_html(render_page("作者稿件清單", html_content, role="author", flash=flash, user=user))

            # 3.2 新增投稿表單
            if path == "/author/new":
                cat_opts = "\n".join(f'<option value="{esc(c)}">{esc(c)}</option>' for c in CATEGORIES)
                tpl = load_template("author_form.html")
                html_content = (
                    tpl.replace("{{form_heading}}", "新增投稿稿件")
                    .replace("{{form_action}}", "/author/new")
                    .replace("{{author_name}}", esc(user["name"]))
                    .replace("{{category_options}}", cat_opts)
                    .replace("{{title}}", "")
                    .replace("{{content}}", "")
                )
                return self.send_html(render_page("新增投稿", html_content, role="author", flash=flash, user=user))

            # 3.3 編輯投稿表單 (僅狀態：編輯中 可編輯)
            if path == "/author/edit":
                mid = int(query.get("id", 0))
                conn = get_db()
                row = conn.execute("SELECT * FROM manuscripts WHERE id = ? AND user_id = ?", (mid, user["id"])).fetchone()
                conn.close()

                if not row:
                    return self.redirect("/author", "danger", "找不到該稿件。")

                if row["status"] != "編輯中":
                    return self.redirect("/author", "warning", f"該稿件目前處於「{row['status']}」狀態，僅「編輯中」稿件允許修改。")

                cat_opts = "\n".join(
                    f'<option value="{esc(c)}" {"selected" if c == row["category"] else ""}>{esc(c)}</option>'
                    for c in CATEGORIES
                )
                tpl = load_template("author_form.html")
                html_content = (
                    tpl.replace("{{form_heading}}", f"編輯投稿稿件 (#{mid})")
                    .replace("{{form_action}}", f"/author/edit?id={mid}")
                    .replace("{{author_name}}", esc(row["author_name"]))
                    .replace("{{category_options}}", cat_opts)
                    .replace("{{title}}", esc(row["title"]))
                    .replace("{{content}}", esc(row["content"]))
                )
                return self.send_html(render_page("編輯投稿", html_content, role="author", flash=flash, user=user))

            # 3.4 作者檢視稿件內容
            if path == "/author/view":
                mid = int(query.get("id", 0))
                conn = get_db()
                row = conn.execute("SELECT * FROM manuscripts WHERE id = ? AND user_id = ?", (mid, user["id"])).fetchone()
                conn.close()

                if not row:
                    return self.redirect("/author", "danger", "找不到指定稿件。")

                if row["status"] == "編輯中":
                    action_buttons = f"""
                    <a href="/author/edit?id={mid}" class="btn btn-primary">✏️ 編輯稿件</a>
                    <form method="POST" action="/author/submit" style="margin:0;" onsubmit="return confirm('確定要送出審查嗎？');">
                      <input type="hidden" name="id" value="{mid}">
                      <button type="submit" class="btn btn-warning">🚀 送出審查</button>
                    </form>
                    """
                else:
                    action_buttons = ""

                review_comment_block = ""
                if row["review_comment"]:
                    review_comment_block = f"""
                    <div style="margin-top: 1rem; padding: 0.85rem 1rem; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; color: #92400e; font-size: 0.9rem;">
                      <b>💬 編輯審查意見：</b>{esc(row['review_comment'])}
                    </div>
                    """

                tpl = load_template("author_view.html")
                html_content = (
                    tpl.replace("{{id}}", str(mid))
                    .replace("{{action_buttons}}", action_buttons)
                    .replace("{{category}}", esc(row["category"]))
                    .replace("{{status_badge}}", render_status_badge(row["status"]))
                    .replace("{{title}}", esc(row["title"]))
                    .replace("{{author_name}}", esc(row["author_name"]))
                    .replace("{{created_at}}", esc(row["created_at"]))
                    .replace("{{updated_at}}", esc(row["updated_at"]))
                    .replace("{{review_comment_block}}", review_comment_block)
                    .replace("{{content}}", esc(row["content"]))
                )
                return self.send_html(render_page("檢視稿件", html_content, role="author", flash=flash, user=user))

        # ---------------- 管理員 / 編輯專區路由 (固定為編輯角色，與作者分頁完全獨立) ----------------
        if path.startswith("/editor"):
            user = self.current_user("editor")
            if not user:
                return self.redirect("/login", "warning", "請先以管理員帳號登入。")
            # 4.1 查看待審查清單 (作者、類別、標題)
            if path == "/editor":
                tab = query.get("tab", "pending")
                conn = get_db()

                stats_row = conn.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN status = '審查中' THEN 1 ELSE 0 END) as count_pending,
                        SUM(CASE WHEN status = '已通過' THEN 1 ELSE 0 END) as count_approved,
                        SUM(CASE WHEN status = '編輯中' THEN 1 ELSE 0 END) as count_draft
                    FROM manuscripts
                """).fetchone()

                if tab == "all":
                    rows = conn.execute("SELECT * FROM manuscripts ORDER BY id DESC").fetchall()
                else:
                    tab = "pending"
                    rows = conn.execute("""
                        SELECT * FROM manuscripts
                        WHERE status = '審查中'
                        ORDER BY updated_at ASC, id ASC
                    """).fetchall()
                conn.close()

                if not rows:
                    empty_msg = "🎉 目前沒有待審查的稿件！(若作者端剛送出投稿，可點擊右上角「刷新清單狀態」)" if tab == "pending" else "目前尚無任何稿件紀錄。"
                    table_rows = f'<tr><td colspan="7" style="text-align: center; padding: 3rem; color: var(--secondary);">{empty_msg}</td></tr>'
                else:
                    tr_list = []
                    for r in rows:
                        mid = r["id"]
                        btn_cls = "btn-primary" if r["status"] == "審查中" else "btn-outline"
                        btn_txt = "🔍 查看並審查" if r["status"] == "審查中" else "👁️ 查看內容"
                        tr_list.append(f"""
                        <tr>
                          <td style="color: var(--secondary);">#{mid}</td>
                          <td style="font-weight: 600;">👤 {esc(r['author_name'])}</td>
                          <td><span class="badge-cat">{esc(r['category'])}</span></td>
                          <td>
                            <div style="font-weight: 600; font-size: 1rem;">
                              <a href="/editor/review?id={mid}" style="color: inherit; text-decoration: none;">{esc(r['title'])}</a>
                            </div>
                          </td>
                          <td style="text-align: center;">{render_status_badge(r['status'])}</td>
                          <td style="font-size: 0.85rem; color: var(--secondary);">{esc(r['updated_at'])}</td>
                          <td style="text-align: right;">
                            <a href="/editor/review?id={mid}" class="btn btn-sm {btn_cls}">{btn_txt}</a>
                          </td>
                        </tr>
                        """)
                    table_rows = "\n".join(tr_list)

                tpl = load_template("editor_dashboard.html")
                html_content = (
                    tpl.replace("{{current_tab}}", esc(tab))
                    .replace("{{count_pending}}", str(stats_row["count_pending"] or 0))
                    .replace("{{count_approved}}", str(stats_row["count_approved"] or 0))
                    .replace("{{count_draft}}", str(stats_row["count_draft"] or 0))
                    .replace("{{count_total}}", str(stats_row["total"] or 0))
                    .replace("{{tab_pending_cls}}", "btn-primary" if tab == "pending" else "btn-outline")
                    .replace("{{tab_all_cls}}", "btn-primary" if tab == "all" else "btn-outline")
                    .replace("{{table_rows}}", table_rows)
                )
                return self.send_html(render_page("編輯審查後台", html_content, role="editor", flash=flash, user=user))

            # 4.2 查看稿件內容 & 審查通過/退回介面
            if path == "/editor/review":
                mid = int(query.get("id", 0))
                conn = get_db()
                row = conn.execute("SELECT * FROM manuscripts WHERE id = ?", (mid,)).fetchone()
                conn.close()

                if not row:
                    return self.redirect("/editor", "danger", "找不到指定稿件。")

                review_comment_block = ""
                if row["review_comment"]:
                    review_comment_block = f"""
                    <div style="margin-top: 1.25rem; padding: 0.85rem 1rem; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; color: #92400e; font-size: 0.9rem;">
                      <b>💬 目前審查備註：</b>{esc(row['review_comment'])}
                    </div>
                    """

                if row["status"] == "審查中":
                    decision_block = f"""
                    <p style="color: var(--secondary); font-size: 0.9rem; margin-bottom: 1.25rem;">
                      請詳閱上述稿件內容後，選擇<b>「選擇通過」</b>或<b>「退回稿件」</b>：
                    </p>
                    <form method="POST" action="/editor/decision">
                      <input type="hidden" name="id" value="{mid}">
                      <div class="form-group">
                        <label class="form-label" for="review_comment">審查意見 / 退回修改建議 (選填)：</label>
                        <textarea name="review_comment" id="review_comment" class="form-control" style="min-height: 90px;" placeholder="例如：論點清晰，同意通過刊登。或：請補充第二段之實證數據後再次送審。"></textarea>
                      </div>
                      <div style="display: flex; gap: 1rem; flex-wrap: wrap; justify-content: flex-end;">
                        <button type="submit" name="decision" value="reject" class="btn btn-warning" style="padding: 0.65rem 1.5rem; font-size: 1rem;" onclick="return confirm('確定要退回此稿件嗎？狀態將由「審查中」變更為「編輯中」。');">
                          ↩️ 退回稿件 (審查中 &rarr; 編輯中)
                        </button>
                        <button type="submit" name="decision" value="approve" class="btn btn-success" style="padding: 0.65rem 1.5rem; font-size: 1rem;" onclick="return confirm('確定要通過此稿件嗎？狀態將由「審查中」變更為「已通過」。');">
                          ✅ 選擇通過 (審查中 &rarr; 已通過)
                        </button>
                      </div>
                    </form>
                    """
                else:
                    decision_block = f"""
                    <div style="padding: 1rem; background: var(--gray-100); border-radius: var(--radius-sm); color: var(--gray-700);">
                      ℹ️ 此稿件目前處於<b>「{esc(row['status'])}」</b>狀態，非待審查稿件。
                    </div>
                    """

                tpl = load_template("editor_review.html")
                html_content = (
                    tpl.replace("{{id}}", str(mid))
                    .replace("{{category}}", esc(row["category"]))
                    .replace("{{status_badge}}", render_status_badge(row["status"]))
                    .replace("{{title}}", esc(row["title"]))
                    .replace("{{author_name}}", esc(row["author_name"]))
                    .replace("{{created_at}}", esc(row["created_at"]))
                    .replace("{{updated_at}}", esc(row["updated_at"]))
                    .replace("{{content}}", esc(row["content"]))
                    .replace("{{review_comment_block}}", review_comment_block)
                    .replace("{{decision_block}}", decision_block)
                )
                return self.send_html(render_page("審閱稿件內容", html_content, role="editor", flash=flash, user=user))

        # 404
        self.send_html(render_page("找不到頁面", '<div class="card"><h3>404 找不到該頁面</h3><p><a href="/">返回首頁</a></p></div>'), status=404)

    # ---------------- POST 路由分發 (所有動作皆導回該分頁所屬角色路由) ----------------
    def do_POST(self):
        try:
            self._handle_post()
        finally:
            try:
                export_sql()  # 資料庫有異動就同步到 database.sql
            except Exception as e:
                print(f"[警告] 同步 database.sql 失敗: {e}")

    def _handle_post(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = {k: v[0] for k, v in parse_qs(parsed_url.query).items()}
        form = self.parse_post_data()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 0. 登入 / 註冊
        if path == "/login":
            username = form.get("username", "").strip()
            password = form.get("password", "")
            role = form.get("role", "author")
            conn = get_db()
            u = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            conn.close()
            if not u or not verify_password(password, u["password_hash"]) or u["role"] != role:
                return self.redirect("/login", "danger", "帳號、密碼或所選身份錯誤。")
            token = secrets.token_urlsafe(24)
            SESSIONS[token] = u["id"]
            dest = "/editor" if u["role"] == "editor" else "/author"
            return self.redirect_with_cookie(dest, COOKIE_NAMES[u["role"]], token)

        if path == "/register":
            username = form.get("username", "").strip()
            name = form.get("name", "").strip()
            password = form.get("password", "")
            confirm = form.get("confirm", "")
            if not username or not name or not password:
                return self.redirect("/register", "danger", "請完整填寫帳號、顯示名稱與密碼。")
            if len(username) > 50 or len(name) > 100:
                return self.redirect("/register", "danger", "帳號或名稱過長。")
            if password != confirm:
                return self.redirect("/register", "danger", "兩次輸入的密碼不一致。")
            conn = get_db()
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                conn.close()
                return self.redirect("/register", "danger", "此帳號已被使用，請換一個。")
            conn.execute("INSERT INTO users (username, password_hash, name, role, created_at) VALUES (?, ?, ?, 'author', ?)",
                         (username, hash_password(password), name, now_str))
            conn.commit()
            conn.close()
            return self.redirect("/login", "success", "註冊成功，請登入。")

        # 1. 作者操作路由 (操作後永遠導回 /author，不影響任何其他分頁)
        if path.startswith("/author"):
            user = self.current_user("author")
            if not user:
                return self.redirect("/login", "warning", "請先以作者帳號登入。")
            # 1.1 新增投稿
            if path == "/author/new":
                author_name = user["name"]
                category = form.get("category", "").strip()
                title = form.get("title", "").strip()
                content = form.get("content", "").strip()
                submit_mode = form.get("submit_mode", "draft")

                if not category or not title or not content:
                    return self.redirect("/author/new", "danger", "請完整填寫類別、標題與文章內容。")

                status = "審查中" if submit_mode == "submit" else "編輯中"
                conn = get_db()
                conn.execute(
                    "INSERT INTO manuscripts (user_id, author_name, category, title, content, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user["id"], author_name, category, title, content, status, now_str, now_str)
                )
                conn.commit()
                conn.close()

                msg = f"投稿《{title}》已建立並送出審查 (狀態：審查中)！" if status == "審查中" else f"投稿《{title}》已儲存為草稿 (狀態：編輯中)。"
                return self.redirect("/author", "success", msg)

            # 1.2 編輯投稿
            if path == "/author/edit":
                mid = int(query.get("id", 0))
                author_name = user["name"]
                category = form.get("category", "").strip()
                title = form.get("title", "").strip()
                content = form.get("content", "").strip()
                submit_mode = form.get("submit_mode", "draft")

                conn = get_db()
                row = conn.execute("SELECT * FROM manuscripts WHERE id = ? AND user_id = ?", (mid, user["id"])).fetchone()
                if not row or row["status"] != "編輯中":
                    conn.close()
                    return self.redirect("/author", "danger", "僅「編輯中」的稿件可進行修改。")

                new_status = "審查中" if submit_mode == "submit" else "編輯中"
                conn.execute(
                    "UPDATE manuscripts SET author_name = ?, category = ?, title = ?, content = ?, status = ?, updated_at = ? WHERE id = ? AND status = '編輯中'",
                    (author_name, category, title, content, new_status, now_str, mid)
                )
                conn.commit()
                conn.close()

                msg = f"稿件《{title}》已更新並送出審查 (編輯中 => 審查中)！" if new_status == "審查中" else f"稿件《{title}》修改已儲存 (狀態：編輯中)。"
                return self.redirect("/author", "success", msg)

            # 1.3 送出投稿：編輯中 => 審查中
            if path == "/author/submit":
                mid = int(form.get("id", 0))
                conn = get_db()
                row = conn.execute("SELECT * FROM manuscripts WHERE id = ? AND user_id = ?", (mid, user["id"])).fetchone()
                if not row or row["status"] != "編輯中":
                    conn.close()
                    return self.redirect("/author", "warning", "僅「編輯中」的稿件可以送出審查。")

                conn.execute(
                    "UPDATE manuscripts SET status = '審查中', updated_at = ? WHERE id = ? AND status = '編輯中'",
                    (now_str, mid)
                )
                conn.commit()
                conn.close()
                return self.redirect("/author", "success", f"稿件《{row['title']}》已成功送出投稿 (狀態：編輯中 => 審查中)！")

            # 1.4 刪除編輯中稿件
            if path == "/author/delete":
                mid = int(form.get("id", 0))
                conn = get_db()
                row = conn.execute("SELECT * FROM manuscripts WHERE id = ? AND user_id = ?", (mid, user["id"])).fetchone()
                if not row or row["status"] != "編輯中":
                    conn.close()
                    return self.redirect("/author", "danger", "僅「編輯中」的稿件可以刪除！")

                conn.execute("DELETE FROM manuscripts WHERE id = ? AND status = '編輯中'", (mid,))
                conn.commit()
                conn.close()
                return self.redirect("/author", "success", f"已刪除編輯中稿件《{row['title']}》。")

        # 2. 管理員/編輯操作路由 (操作後永遠導回 /editor，不影響作者分頁)
        if path == "/editor/decision":
            if not self.current_user("editor"):
                return self.redirect("/login", "warning", "請先以管理員帳號登入。")
            mid = int(form.get("id", 0))
            decision = form.get("decision", "")
            review_comment = form.get("review_comment", "").strip()

            conn = get_db()
            row = conn.execute("SELECT * FROM manuscripts WHERE id = ?", (mid,)).fetchone()
            if not row or row["status"] != "審查中":
                conn.close()
                return self.redirect("/editor", "warning", "該稿件並非處於「審查中」狀態，無法執行審核。")

            if decision == "approve":
                comment = review_comment if review_comment else "審查通過"
                conn.execute(
                    "UPDATE manuscripts SET status = '已通過', review_comment = ?, updated_at = ? WHERE id = ?",
                    (comment, now_str, mid)
                )
                conn.commit()
                conn.close()
                return self.redirect("/editor", "success", f"稿件《{row['title']}》已選擇通過 (狀態：審查中 => 已通過)！")

            elif decision == "reject":
                comment = review_comment if review_comment else "退回修改"
                conn.execute(
                    "UPDATE manuscripts SET status = '編輯中', review_comment = ?, updated_at = ? WHERE id = ?",
                    (comment, now_str, mid)
                )
                conn.commit()
                conn.close()
                return self.redirect("/editor", "warning", f"稿件《{row['title']}》已退回作者修改 (狀態：審查中 => 編輯中)！")

        self.redirect("/")


def run_server(port=8000, open_browser=True):
    init_database(force_reset=False)

    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, SubmissionRequestHandler)
    url = f"http://localhost:{port}"

    print("=" * 66)
    print("  🐍 投稿審查系統 (Python + SQL + HTML) 已啟動！")
    print(f"  👉 首頁入口: {url}  (登入: author/123、manager/123)")
    print(f"  ✍️ 作者專區分頁網址: {url}/author")
    print(f"  🔍 編輯專區分頁網址: {url}/editor")
    print("  💡 支援同時開多個瀏覽器分頁同步操作，各分頁角色完全獨立不互蓋！")
    print("  (按 Ctrl + C 可停止伺服器)")
    print("=" * 66)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[訊息] 伺服器已關閉。")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    no_browser = "--no-browser" in sys.argv
    run_server(port=port, open_browser=not no_browser)
