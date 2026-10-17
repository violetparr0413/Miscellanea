#!/usr/bin/env python3

import json
import math
import re
import sqlite3
import time

import requests

SECTION_URL = "https://section.blog.naver.com/ajax/OfficialBlogList.naver"
BLOG_URL = (
    "https://blog.naver.com/PostList.naver"
    "?blogId={blog_id}"
    "&widgetTypeCall=true"
    "&from=section"
    "&topReferer=https%3A%2F%2Fsection.blog.naver.com%2FOfficialBlog.naver%3FcurrentPage%3D1"
    "&trackingCode=blog_etc"
    "&directAccess=true"
)
FOLLOWER_URL = (
    "https://blog.naver.com/connect/WidgetAddedMeAsBuddyViewAsync.nhn"
    "?blogId={blog_id}"
    "&groupId=null"
    "&currentPage={page}"
    "&authCode={auth_code}"
    "&widgetSeq=1"
)

DB_FILE = "blogs.db"
MAX_DEPTH = 9
REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36"
    )
}


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

def init_db(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blog_emails (
            idx       INTEGER PRIMARY KEY,
            blog_id   TEXT NOT NULL UNIQUE,
            email     TEXT,
            parent_idx INTEGER REFERENCES blog_emails(idx)
        )
        """
    )

    # 기존 blogs.db에도 parent_idx 열을 추가한다.
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(blog_emails)")
    }
    if "parent_idx" not in columns:
        conn.execute(
            "ALTER TABLE blog_emails ADD COLUMN parent_idx INTEGER "
            "REFERENCES blog_emails(idx)"
        )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_blog_emails_parent_idx "
        "ON blog_emails(parent_idx)"
    )

    # id=1인 단일 행만 사용한다. current_page는 공식 블로그 목록 페이지다.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS status (
            id           INTEGER PRIMARY KEY CHECK (id = 1),
            current_page INTEGER NOT NULL DEFAULT 1 CHECK (current_page >= 1),
            blog_id      TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO status (id, current_page, blog_id) VALUES (1, 1, '')"
    )
    conn.commit()


def is_blog_exists(conn, blog_id):
    row = conn.execute(
        "SELECT 1 FROM blog_emails WHERE blog_id = ? LIMIT 1",
        (blog_id,),
    ).fetchone()
    return row is not None


def get_blog_idx(conn, blog_id):
    row = conn.execute(
        "SELECT idx FROM blog_emails WHERE blog_id = ? LIMIT 1",
        (blog_id,),
    ).fetchone()
    return row[0] if row else None


def save_blog(conn, blog_id, email, parent_idx=None):
    conn.execute(
        """
        INSERT OR IGNORE INTO blog_emails (blog_id, email, parent_idx)
        VALUES (?, ?, ?)
        """,
        (blog_id, email, parent_idx),
    )

    # 기존 행에 부모가 아직 기록되지 않았을 때만 처음 발견한 부모를 기록한다.
    if parent_idx is not None:
        conn.execute(
            """
            UPDATE blog_emails
               SET parent_idx = ?
             WHERE blog_id = ? AND parent_idx IS NULL
            """,
            (parent_idx, blog_id),
        )

    idx = get_blog_idx(conn, blog_id)
    conn.commit()
    return idx


def load_status(conn):
    row = conn.execute(
        "SELECT current_page, blog_id FROM status WHERE id = 1"
    ).fetchone()
    if not row:
        return 1, ""
    return max(1, int(row[0])), row[1] or ""


def save_status(conn, current_page, blog_id=""):
    conn.execute(
        "UPDATE status SET current_page = ?, blog_id = ? WHERE id = 1",
        (current_page, blog_id),
    )
    conn.commit()


# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------

def fetch(url, referer=None):
    headers = HEADERS.copy()
    if referer:
        headers["Referer"] = referer

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=20,
            verify=True,
        )
        response.raise_for_status()
        time.sleep(REQUEST_DELAY)
        return response.text
    except requests.RequestException as exc:
        print(f"[ERROR] GET {url}: {exc}")
        return None


# ------------------------------------------------------------
# Step 1: official blog list
# ------------------------------------------------------------

def fetch_official_page(page):
    url = f"{SECTION_URL}?pageNo={page}"
    referer = f"{SECTION_URL}?pageNo={max(page - 1, 1)}"
    return fetch(url, referer)


def parse_official_page(html):
    if not html:
        return None

    prefix = ")]}',"
    if html.startswith(prefix):
        html = html[len(prefix):]

    try:
        return json.loads(html)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Official JSON parse error: {exc}")
        return None


def extract_official_blogs(data):
    try:
        blog_list = data["result"]["blogList"]
    except (KeyError, TypeError):
        return []

    return [item.get("blogId") for item in blog_list if item.get("blogId")]


def get_official_total_pages(data):
    try:
        return int(data["result"]["totalPageNo"])
    except (KeyError, TypeError, ValueError):
        return 0


# ------------------------------------------------------------
# Step 2: blog page, email and authCode
# ------------------------------------------------------------

def fetch_blog_page(blog_id):
    url = BLOG_URL.format(blog_id=blog_id)
    referer = (
        "https://section.blog.naver.com/"
        "OfficialBlog.naver?currentPage=1"
    )
    return fetch(url, referer)


def extract_email(html):
    if not html:
        return None

    pattern = r"[a-zA-Z0-9._%+-]+@naver\.com"
    match = re.search(pattern, html)
    return match.group(0) if match else None


def extract_auth_code(html):
    if not html:
        return None

    pattern = (
        r'src="/connect/WidgetView\.naver\?blogId=[^&"]+'
        r'&widgetSeq=1'
        r'&authCode=([^"&]+)"'
    )
    match = re.search(pattern, html)
    return match.group(1) if match else None


# ------------------------------------------------------------
# Step 3: follower JSON
# ------------------------------------------------------------

def fetch_followers_page(blog_id, auth_code, page):
    url = FOLLOWER_URL.format(
        blog_id=blog_id,
        page=page,
        auth_code=auth_code,
    )
    referer = f"https://blog.naver.com/PostList.naver?blogId={blog_id}"
    return fetch(url, referer)


def parse_followers_page(html):
    if not html:
        return None
    try:
        return json.loads(html)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Follower JSON parse error: {exc}")
        return None


def extract_followers(data):
    try:
        buddies = data["result"]["buddies"]
        count_per_page = int(buddies["countPerPage"])
        total_count = int(data["result"]["buddyCount"])
        follower_list = buddies["list"]
    except (KeyError, TypeError, ValueError):
        return 0, 0, []

    total_pages = math.ceil(total_count / count_per_page) if count_per_page else 0
    blog_ids = [item.get("blogId") for item in follower_list if item.get("blogId")]
    return total_count, total_pages, blog_ids


# ------------------------------------------------------------
# Recursive processing
# ------------------------------------------------------------

def process_blog(conn, blog_id, depth, parent_idx=None):
    # 이미 저장된 블로그라도 부모 관계가 아직 없다면 첫 부모를 기록한다.
    if is_blog_exists(conn, blog_id):
        if parent_idx is not None:
            conn.execute(
                """
                UPDATE blog_emails
                   SET parent_idx = ?
                 WHERE blog_id = ? AND parent_idx IS NULL
                """,
                (parent_idx, blog_id),
            )
            conn.commit()

        print(f"[SKIP] {blog_id} (already exists)")
        return

    print(f"[BLOG] {blog_id} (depth={depth})")

    html = fetch_blog_page(blog_id)
    if not html:
        return

    email = extract_email(html)
    print(f"email: {email}")

    this_idx = save_blog(conn, blog_id, email, parent_idx)

    if depth > MAX_DEPTH:
        print(f"[DEPTH] {blog_id} (depth={depth})")
        return

    auth_code = extract_auth_code(html)
    if not auth_code:
        print(f"[WARN] authCode not found: {blog_id}")
        return

    html = fetch_followers_page(blog_id, auth_code, 1)
    data = parse_followers_page(html)
    if not data:
        return

    total_count, total_pages, follower_ids = extract_followers(data)
    print(f"[FOLLOWER] {blog_id}: {total_count} users, {total_pages} pages")

    for follower_id in follower_ids:
        process_blog(conn, follower_id, depth + 1, parent_idx=this_idx)

    for page in range(2, total_pages + 1):
        html = fetch_followers_page(blog_id, auth_code, page)
        data = parse_followers_page(html)
        if not data:
            continue

        _, _, follower_ids = extract_followers(data)
        for follower_id in follower_ids:
            process_blog(conn, follower_id, depth + 1, parent_idx=this_idx)


# ------------------------------------------------------------
# Main: resume official-list traversal from status
# ------------------------------------------------------------

def main():
    conn = sqlite3.connect(DB_FILE)

    try:
        init_db(conn)

        start_page, resume_blog_id = load_status(conn)

        # 첫 페이지로 totalPageNo를 알아낸다.
        first_html = fetch_official_page(1)
        first_data = parse_official_page(first_html)
        if not first_data:
            print("[ERROR] Could not load official blog page 1; progress unchanged.")
            return

        total_pages = get_official_total_pages(first_data)
        if total_pages <= 0:
            print("[ERROR] Invalid total page count; progress unchanged.")
            return

        print(f"[OFFICIAL] total pages: {total_pages}")
        print(f"[RESUME] page={start_page}, blog_id={resume_blog_id or '(first blog on page)'}")

        if start_page > total_pages:
            print("[INFO] Saved position is beyond the current last page; nothing to process.")
            return

        for page in range(start_page, total_pages + 1):
            if page == 1:
                data = first_data
            else:
                html = fetch_official_page(page)
                data = parse_official_page(html)

            if not data:
                # 실패한 페이지의 status는 유지하여 다음 실행에서 다시 시도한다.
                print(f"[ERROR] Could not load official page {page}; stopping without advancing status.")
                break

            blog_ids = extract_official_blogs(data)

            start_index = 0
            if page == start_page and resume_blog_id:
                try:
                    # 중단된 blog_id부터 다시 시도한다.
                    start_index = blog_ids.index(resume_blog_id)
                except ValueError:
                    # 목록이 바뀌어 blog_id가 없다면 해당 페이지 첫 항목부터 검사한다.
                    print("[WARN] Saved blog_id is not on this page; scanning page from the beginning.")
                    start_index = 0

            for blog_id in blog_ids[start_index:]:
                # 매 공식 블로그 처리 직전에 진행 위치를 디스크에 기록한다.
                save_status(conn, page, blog_id)
                process_blog(conn, blog_id, 0, parent_idx=None)

            # 페이지가 끝난 뒤 다음 페이지를 체크포인트로 기록한다.
            save_status(conn, page + 1, "")
            resume_blog_id = ""

    finally:
        conn.close()


if __name__ == "__main__":
    main()
