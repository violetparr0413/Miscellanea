#!/usr/bin/env python3

import requests
import sqlite3
import json
import math
import re
import time

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blog_emails (
            id       INTEGER PRIMARY KEY,
            blog_id  TEXT NOT NULL UNIQUE,
            email    TEXT
        )
    """)

    conn.commit()


def is_blog_exists(conn, blog_id):
    row = conn.execute(
        "SELECT 1 FROM blog_emails WHERE blog_id = ? LIMIT 1",
        (blog_id,)
    ).fetchone()

    return row is not None


def save_blog(conn, blog_id, email):
    sql = """
        INSERT OR IGNORE INTO blog_emails
            (blog_id, email)
        VALUES
            (?, ?)
    """

    conn.execute(
        sql,
        (
            blog_id,
            email
        )
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
            verify=True
        )

        response.raise_for_status()

        time.sleep(REQUEST_DELAY)

        return response.text

    except requests.RequestException as e:
        print(f"[ERROR] GET {url}: {e}")
        return None


# ------------------------------------------------------------
# Step 1
# 공식 블로그 목록
# ------------------------------------------------------------

def fetch_official_page(page):
    url = (
        f"{SECTION_URL}"
        f"?pageNo={page}"
    )

    referer = (
        f"{SECTION_URL}"
        f"?pageNo={max(page - 1, 1)}"
    )

    return fetch(url, referer)


def parse_official_page(html):
    if not html:
        return None

    # Naver 응답의 앞부분
    prefix = ")]}',"

    if html.startswith(prefix):
        html = html[len(prefix):]

    try:
        return json.loads(html)

    except json.JSONDecodeError as e:
        print(f"[ERROR] Official JSON parse error: {e}")
        return None


def extract_official_blogs(data):
    try:
        blog_list = data["result"]["blogList"]

    except (KeyError, TypeError):
        return []

    result = []

    for item in blog_list:
        blog_id = item.get("blogId")

        if blog_id:
            result.append(blog_id)

    return result


def get_official_total_pages(data):
    try:
        return int(data["result"]["totalPageNo"])

    except (KeyError, TypeError, ValueError):
        return 0


# ------------------------------------------------------------
# Step 2
# 블로그 페이지에서 이메일 및 authCode 추출
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

    if not match:
        return None

    return match.group(0)

def extract_auth_code(html):
    if not html:
        return None

    pattern = (
        r'src="/connect/WidgetView\.naver'
        r'\?blogId=[^&"]+'
        r'&widgetSeq=1'
        r'&authCode=([^"&]+)"'
    )

    match = re.search(pattern, html)

    if not match:
        return None

    return match.group(1)


# ------------------------------------------------------------
# Step 3
# 팔로워 JSON 파싱
# ------------------------------------------------------------

def fetch_followers_page(blog_id, auth_code, page):
    url = FOLLOWER_URL.format(
        blog_id=blog_id,
        page=page,
        auth_code=auth_code
    )

    referer = (
        f"https://blog.naver.com/PostList.naver"
        f"?blogId={blog_id}"
    )

    return fetch(url, referer)


def parse_followers_page(html):
    if not html:
        return None

    try:
        return json.loads(html)

    except json.JSONDecodeError as e:
        print(f"[ERROR] Follower JSON parse error: {e}")
        return None


def extract_followers(data):
    try:
        buddies = data["result"]["buddies"]

        count_per_page = int(
            buddies["countPerPage"]
        )

        total_count = int(
            data["result"]["buddyCount"]
        )

        follower_list = buddies["list"]

    except (KeyError, TypeError, ValueError):
        return 0, 0, []

    total_pages = math.ceil(
        total_count / count_per_page
    ) if count_per_page else 0

    blog_ids = []

    for item in follower_list:
        blog_id = item.get("blogId")

        if blog_id:
            blog_ids.append(blog_id)

    return total_count, total_pages, blog_ids


# ------------------------------------------------------------
# Recursive processing
# ------------------------------------------------------------

def process_blog(
    conn,
    blog_id,
    depth,
):
    # DB에 이미 존재하면 즉시 중단
    if is_blog_exists(conn, blog_id):
        print(
            f"[SKIP] {blog_id} "
            f"(already exists)"
        )
        return

    print(
        f"[BLOG] {blog_id} "
        f"(depth={depth})"
    )

    # --------------------------------------------------------
    # Step 2
    # --------------------------------------------------------

    html = fetch_blog_page(blog_id)

    if not html:
        return
    
    email = extract_email(html)
    
    print(f"email: {email}")
    
    save_blog(
        conn,
        blog_id,
        email
    )
    
    if depth > MAX_DEPTH:
        print(
            f"[DEPTH] {blog_id} "
            f"(depth={depth})"
        )
        return

    auth_code = extract_auth_code(html)

    if not auth_code:
        print(
            f"[WARN] authCode not found: "
            f"{blog_id}"
        )
        return

    # --------------------------------------------------------
    # Step 3 - 첫 페이지
    # --------------------------------------------------------

    html = fetch_followers_page(
        blog_id,
        auth_code,
        1
    )

    data = parse_followers_page(html)

    if not data:
        return

    total_count, total_pages, follower_ids = (
        extract_followers(data)
    )

    print(
        f"[FOLLOWER] {blog_id}: "
        f"{total_count} users, "
        f"{total_pages} pages"
    )

    # 첫 페이지 처리
    for follower_id in follower_ids:
        process_blog(
            conn,
            follower_id,
            depth + 1,
        )

    # --------------------------------------------------------
    # 나머지 페이지
    # --------------------------------------------------------

    for page in range(2, total_pages + 1):

        html = fetch_followers_page(
            blog_id,
            auth_code,
            page
        )

        data = parse_followers_page(html)

        if not data:
            continue

        _, _, follower_ids = extract_followers(
            data
        )

        for follower_id in follower_ids:
            process_blog(
                conn,
                follower_id,
                depth + 1,
            )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    conn = sqlite3.connect(DB_FILE)

    try:
        init_db(conn)

        # ----------------------------------------------------
        # Step 1
        # ----------------------------------------------------

        first_html = fetch_official_page(1)

        first_data = parse_official_page(
            first_html
        )

        if not first_data:
            return

        total_pages = get_official_total_pages(
            first_data
        )

        print(
            f"[OFFICIAL] total pages: "
            f"{total_pages}"
        )

        # 첫 페이지
        official_blog_ids = extract_official_blogs(
            first_data
        )

        for blog_id in official_blog_ids:
            process_blog(
                conn,
                blog_id,
                0
            )

        # 나머지 페이지
        for page in range(
            2,
            total_pages + 1
        ):

            html = fetch_official_page(
                page
            )

            data = parse_official_page(
                html
            )

            if not data:
                continue

            blog_ids = extract_official_blogs(
                data
            )

            for blog_id in blog_ids:
                process_blog(
                    conn,
                    blog_id,
                    0
                )

    finally:
        conn.close()


if __name__ == "__main__":
    main()