#!/usr/bin/env python3
"""위케어동물의료센터 홈페이지 '박성수 원장의 블로그 노트' 자동 최신화.

네이버 블로그 RSS(https://rss.blog.naver.com/wecarevet.xml)에서 최근 글 4편을 읽어
index.html 의

    <!-- BLOG_NOTES_START -->
    ... 카드 4장 ...
    <!-- BLOG_NOTES_END -->

구역만 다시 그린다. 그 밖의 HTML/CSS 는 절대 건드리지 않는다.

원칙
  * RSS 가 일시적으로 막히거나 형식이 깨져도 사이트를 깨뜨리지 않는다(exit 0, 파일 그대로).
  * 마커 구역 밖은 손대지 않는다.
  * 이미 카드로 걸려 있는 글은 사람이 다듬어 둔 카테고리/요약을 그대로 살린다.
  * 내용이 바뀌지 않으면 파일을 쓰지 않는다 → 커밋도 생기지 않는다.

사용법
    python3 scripts/update_blog.py            # 동기화
    python3 scripts/update_blog.py --dry-run  # 결과만 출력
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

RSS_URL = "https://rss.blog.naver.com/wecarevet.xml"
USER_AGENT = (
    "Mozilla/5.0 (compatible; WeCareVetBlogSync/1.0; "
    "+https://wecarevet.github.io/wecarevet/)"
)
TIMEOUT = 20  # 초
POST_COUNT = 4
SUMMARY_LIMIT = 96  # 한 카드 요약 길이(약 2줄)
KST = timezone(timedelta(hours=9))

START_MARK = "<!-- BLOG_NOTES_START -->"
END_MARK = "<!-- BLOG_NOTES_END -->"

DEFAULT_HTML = Path(__file__).resolve().parent.parent / "index.html"

# RSS 의 category → 카드 배지 문구(사이트에서 쓰는 짧은 라벨 유지)
CATEGORY_LABELS = {
    "올바른 진료를 위한 칼럼": "칼럼",
    "병원소식": "연구 · 소식",
    "나의 아이들을 위한 서재": "원장의 서재",
    "병원소개": "병원 이야기",
    "의료진소개": "병원 이야기",
    "시설소개": "병원 이야기",
    "위케어동물의료센터": "병원 이야기",
}
FALLBACK_LABEL = "블로그"


# ---------------------------------------------------------------- RSS


def fetch_rss(url: str = RSS_URL) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def parse_date(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    # 예: Tue, 06 Oct 2026 19:59:54 +0900
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return dt.astimezone(KST) if dt.tzinfo else dt.replace(tzinfo=KST)
    return None


def normalize_link(link: str) -> str:
    link = (link or "").strip().split("?")[0].split("#")[0]
    link = link.replace("http://", "https://", 1)
    return link.rstrip("/") if link.endswith("/") and "blog.naver.com" not in link else link


def clean_text(value: str) -> str:
    """HTML 태그·URL·말줄임표를 걷어내고 공백을 정리한다."""
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]*>", " ", text)  # <img .../> 등
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"[\u00a0\u200b]", " ", text)
    text = re.sub(r"[.·]{3,}", "…", text)  # RSS 말줄임 '.......'
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_title(value: str) -> str:
    """제목의 중복 공백과 닫는 괄호 앞 공백만 정리한다(내용은 그대로)."""
    text = clean_text(value)
    text = re.sub(r"\s+([,\)\]])", r"\1", text)
    return text


def summarize(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """앞쪽 문장을 limit 자 안에서 2줄 분량으로 정리한다."""
    text = re.sub(r"…+", " ", text).strip()
    if not text:
        return ""
    # 문장 단위로 자른 뒤, limit 안에서 최대한 담는다.
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    # RSS 본문 맨 앞의 제목 비슷한 머리말("제목 | 병원소개" 형태)은 요약에서 뺀다.
    if len(parts) > 1 and " | " in parts[0] and len(parts[0]) < 70:
        parts = parts[1:]
    out = ""
    for part in parts:
        candidate = f"{out} {part}".strip()
        if len(candidate) > limit:
            break
        out = candidate
        if out.endswith((".", "!", "?")) and len(out) >= limit * 0.6:
            break
    if not out:
        # 첫 문장이 limit 보다 길면 단어 경계에서 자른다.
        cut = text[:limit]
        cut = cut[: cut.rfind(" ")] if " " in cut else cut
        out = cut.rstrip(" ,·-—") + "…"
    return out


def load_posts(url: str = RSS_URL, count: int = POST_COUNT) -> list[dict]:
    raw = fetch_rss(url)
    root = ET.fromstring(raw)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("channel 요소를 찾지 못했습니다.")

    posts: list[dict] = []
    seen: set[str] = set()
    for item in channel.findall("item"):
        title = clean_title(item.findtext("title") or "")
        link = normalize_link(item.findtext("link") or "")
        if not title or not link or link in seen:
            continue
        seen.add(link)
        category = clean_text(item.findtext("category") or "")
        summary = summarize(clean_text(item.findtext("description") or ""))
        posts.append(
            {
                "title": title,
                "title_html": html.escape(title, quote=False),
                "url": link,
                "date": parse_date(item.findtext("pubDate") or ""),
                "category": CATEGORY_LABELS.get(category, FALLBACK_LABEL),
                "summary_html": html.escape(summary, quote=False),
            }
        )
        if len(posts) >= count:
            break

    if not posts:
        raise ValueError("RSS 에 글이 없습니다.")
    return posts


# ---------------------------------------------------------------- HTML


def render_card(post: dict) -> str:
    """index.html 의 기존 카드와 같은 구조·클래스·들여쓰기."""
    date = post["date"].strftime("%Y. %m. %d") if post["date"] else ""
    return "\n".join(
        [
            '      <li class="note">',
            f'        <a href="{post["url"]}" target="_blank" rel="noopener">',
            f'          <span class="note-date">{date}</span>',
            '          <span class="note-body">',
            f'            <span class="note-cat">{html.escape(post["category"], quote=False)}</span>',
            f'            <span class="note-title">{post["title_html"]}</span>',
            f'            <span class="note-sum">{post["summary_html"]}</span>',
            "          </span>",
            '          <span class="note-go" aria-hidden="true">→</span>',
            "        </a>",
            "      </li>",
        ]
    )


def render_block(posts: list[dict]) -> str:
    cards = "\n".join(render_card(p) for p in posts)
    return f"    {START_MARK}\n{cards}\n    {END_MARK}"


BLOCK_RE = re.compile(
    r"[ \t]*" + re.escape(START_MARK) + r".*?" + re.escape(END_MARK) + r"[ \t]*",
    re.S,
)


def find_block(html_text: str) -> tuple[int, int] | None:
    """마커 구역의 (시작, 끝) 위치. 마커 줄 앞뒤 공백도 구역에 포함한다."""
    m = BLOCK_RE.search(html_text)
    return (m.start(), m.end()) if m else None


def existing_cards(html_text: str) -> dict[str, dict]:
    """이미 사이트에 걸린 카드의 배지·요약을 URL 기준으로 모아 둔다.

    사람이 다듬어 둔 문장을 RSS 앞부분으로 덮어쓰지 않기 위한 장치.
    """
    span = find_block(html_text)
    if not span:
        return {}
    block = html_text[span[0] : span[1]]
    cards: dict[str, dict] = {}
    for chunk in block.split('<li class="note">')[1:]:
        url = re.search(r'<a href="([^"]+)"', chunk)
        cat = re.search(r'<span class="note-cat">(.*?)</span>', chunk, re.S)
        summ = re.search(r'<span class="note-sum">(.*?)</span>', chunk, re.S)
        if not url:
            continue
        cards[normalize_link(url.group(1))] = {
            "category": (cat.group(1).strip() if cat else ""),
            "summary_html": (re.sub(r"\s+", " ", summ.group(1)).strip() if summ else ""),
        }
    return cards


def merge_curated(posts: list[dict], curated: dict[str, dict]) -> list[dict]:
    for post in posts:
        kept = curated.get(post["url"])
        if not kept:
            continue
        if kept["summary_html"]:
            post["summary_html"] = kept["summary_html"]
        if kept["category"]:
            post["category"] = kept["category"]
    return posts


def update_html(html_text: str, block: str) -> str:
    span = find_block(html_text)
    if not span:
        raise LookupError(
            f"{START_MARK} / {END_MARK} 마커를 index.html 에서 찾지 못했습니다."
        )
    if html_text.count(START_MARK) != 1 or html_text.count(END_MARK) != 1:
        raise LookupError("마커가 여러 개 있습니다. 한 쌍만 남겨 주세요.")
    return html_text[: span[0]] + block + html_text[span[1] :]


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버 블로그 RSS → index.html 블로그 노트")
    parser.add_argument("--file", default=str(DEFAULT_HTML), help="대상 HTML 경로")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 출력")
    parser.add_argument("--rss", default=RSS_URL, help="RSS 주소(테스트용)")
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"[blog] 대상 파일 없음: {path}", file=sys.stderr)
        return 1

    original = path.read_text(encoding="utf-8")
    try:
        posts = load_posts(args.rss)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # RSS 일시 장애: 사이트는 그대로 두고 정상 종료(워크플로 실패로 만들지 않음)
        print(f"[blog] RSS 연결 실패, 이번 회차는 건너뜁니다: {exc}")
        return 0
    except (ET.ParseError, ValueError) as exc:
        print(f"[blog] RSS 해석 실패, 이번 회차는 건너뜁니다: {exc}")
        return 0

    posts = merge_curated(posts, existing_cards(original))

    try:
        updated = update_html(original, render_block(posts))
    except LookupError as exc:
        print(f"[blog] {exc}", file=sys.stderr)
        return 1

    if updated == original:
        print("[blog] 변경 없음")
        return 0

    if args.dry_run:
        span = find_block(updated)
        print(updated[span[0] : span[1]] if span else updated)
        print("[blog] dry-run: 파일을 쓰지 않았습니다.")
        return 0

    path.write_text(updated, encoding="utf-8")
    print(f"[blog] 최신 {len(posts)}편으로 갱신: {path}")
    for post in posts:
        print(f"  - {post['date'].strftime('%Y-%m-%d') if post['date'] else '????-??-??'} "
              f"[{post['category']}] {post['title'][:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
