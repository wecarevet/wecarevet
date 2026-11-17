import urllib.request
import urllib.parse
import json
import time
import os
import re
import hashlib
import html as html_lib
from datetime import datetime, timedelta

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

JOURNALS = [
    {"name": "AJVR",         "query": '"Am J Vet Res"[jour]',                          "type": "vet"},
    {"name": "JVIM",         "query": '"J Vet Intern Med"[jour]',                       "type": "vet"},
    {"name": "JVCS",         "query": '"J Vet Cardiol"[jour]',                          "type": "vet"},
    {"name": "JSAP",         "query": '"J Small Anim Pract"[jour]',                     "type": "vet"},
    {"name": "JAVMA",        "query": '"J Am Vet Med Assoc"[jour]',                     "type": "vet"},
    {"name": "Vet J",        "query": '"Vet J"[jour]',                                  "type": "vet"},
    {"name": "BMC Vet Res",  "query": '"BMC Vet Res"[jour]',                            "type": "vet"},
    {"name": "Vet Clin Pathol", "query": '"Vet Clin Pathol"[jour]',                     "type": "vet"},
    {"name": "JVECC",        "query": '"J Vet Emerg Crit Care (San Antonio)"[jour]',    "type": "vet"},
    {"name": "Circulation",  "query": '"Circulation"[jour]',                            "type": "human"},
    {"name": "JACC",         "query": '"J Am Coll Cardiol"[jour]',                      "type": "human"},
    {"name": "Eur Heart J",  "query": '"Eur Heart J"[jour]',                            "type": "human"},
]

SMALL_ANIMAL = '("dogs"[tiab] OR "cats"[tiab] OR "feline"[tiab] OR "canine"[tiab] OR "small animal"[tiab])'
HUMAN_CARDIO = '("heart failure"[tiab] OR "atrial fibrillation"[tiab] OR "myocardial infarction"[tiab] OR "cardiac"[tiab] OR "cardiomyopathy"[tiab] OR "arrhythmia"[tiab] OR "coronary"[tiab] OR "valvular"[tiab])'
BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

# ── Clinician's Brief 설정 ──
CB_CATEGORY_PAGES = [
    ("https://www.cliniciansbrief.com/clinical-skills",    "Clinical Skills"),
    ("https://www.cliniciansbrief.com/drugs-therapeutics", "Drugs & Therapeutics"),
]
CB_MAX = 20
CB_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
# 실제 아티클이 아닌 사이트 안내 페이지
CB_EXCLUDE_SLUGS = {"clinicians-brief-editorial-policy"}

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def summarize_ko(title, abstract):
    if not ANTHROPIC_API_KEY or not abstract:
        return ""
    try:
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": f"다음 수의학 논문을 한국어로 2~3문장으로 핵심만 간결하게 요약해줘. 전문 수의사가 읽는다고 가정하고 임상적으로 중요한 내용 위주로.\n\n제목: {title}\n\n초록: {abstract}"
            }]
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            }
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"  요약 오류: {e}")
        return ""

def get_papers(journal):
    date_from = (datetime.now() - timedelta(days=60)).strftime("%Y/%m/%d")
    date_to = datetime.now().strftime("%Y/%m/%d")
    filter_query = SMALL_ANIMAL if journal["type"] == "vet" else HUMAN_CARDIO
    query = urllib.parse.quote(
        f'({journal["query"]}) AND {filter_query} AND ("{date_from}"[PDAT] : "{date_to}"[PDAT])'
    )
    search = fetch(f"{BASE}esearch.fcgi?db=pubmed&term={query}&retmax=30&sort=date&retmode=json")
    ids = search.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    time.sleep(0.4)

    # abstract 포함해서 가져오기
    fetch_url = f"{BASE}efetch.fcgi?db=pubmed&id={','.join(ids)}&retmode=xml&rettype=abstract"
    req = urllib.request.Request(fetch_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        xml = r.read().decode()

    summary = fetch(f"{BASE}esummary.fcgi?db=pubmed&id={','.join(ids)}&retmode=json")
    result = summary.get("result", {})

    # XML에서 abstract 파싱
    abstracts = {}
    art_blocks = re.findall(r'<PubmedArticle>(.*?)</PubmedArticle>', xml, re.DOTALL)
    for block in art_blocks:
        pmid_m = re.search(r'<PMID[^>]*>(\d+)</PMID>', block)
        abs_m = re.findall(r'<AbstractText[^>]*>(.*?)</AbstractText>', block, re.DOTALL)
        if pmid_m and abs_m:
            abstracts[pmid_m.group(1)] = ' '.join(re.sub(r'<[^>]+>', '', a) for a in abs_m)

    papers = []
    for pid in ids:
        item = result.get(pid)
        if not item:
            continue
        abstract = abstracts.get(pid, "")
        title = item.get("title", "").replace("<b>", "").replace("</b>", "")

        print(f"    요약 중: {title[:40]}...")
        summary_ko = summarize_ko(title, abstract)
        time.sleep(0.3)

        papers.append({
            "id": pid,
            "title": title,
            "authors": ", ".join(a.get("name", "") for a in item.get("authors", [])[:5]),
            "journal": journal["name"],
            "type": journal["type"],
            "date": item.get("pubdate", ""),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "abstract": abstract[:500] if abstract else "",
            "summary_ko": summary_ko,
        })
    return papers

# ── Clinician's Brief ──

def cb_article_id(url):
    """URL 기반 결정적 ID. 실행할 때마다 값이 바뀌지 않아 읽음/북마크 상태가 유지된다."""
    return "cb_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]

def normalize_date(value):
    """기존 papers.json의 날짜 표기를 YYYY-MM-DD로 통일."""
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%Y %b %d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""

def load_previous_papers():
    """이전 papers.json의 PubMed 논문 목록(수집 실패 시 대체용)."""
    try:
        with open("papers.json", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("papers", [])
    except (OSError, ValueError):
        return []

def load_previous_cb():
    """이전 papers.json의 CB 아티클을 URL → 항목으로 불러온다."""
    try:
        with open("papers.json", encoding="utf-8") as f:
            data = json.load(f)
        return {a["url"]: a for a in data.get("clinicians_brief", []) if a.get("url")}
    except (OSError, ValueError):
        return {}

CB_TITLE_RE = re.compile(
    r'href="(/article/[^"#?]+)"[^>]*>\s*(?:<span[^>]*>)?([^<]{5,300}?)\s*(?:</span>)?\s*</a>'
)
CB_CATEGORY_RE = re.compile(r'href="/clinical-skills/([^"]+)"[^>]*>\s*([^<]{2,80}?)\s*</a>')

def parse_cb_page(page_html, default_category):
    """목록 페이지에서 실제 아티클 카드(제목 + 카테고리)만 뽑는다.
    푸터의 정책 안내 링크 등 카드가 아닌 링크는 제외한다."""
    body = page_html.split("<footer", 1)[0]
    cards = []
    for m in CB_TITLE_RE.finditer(body):
        path = m.group(1)
        slug = path.rsplit("/", 1)[-1]
        if slug in CB_EXCLUDE_SLUGS:
            continue
        title = html_lib.unescape(m.group(2)).strip()
        if len(title) < 10:
            continue
        # 카드 위쪽에서 가장 가까운 카테고리 링크를 카테고리로 사용
        before = body[max(0, m.start() - 4000):m.start()]
        cats = CB_CATEGORY_RE.findall(before)
        category = html_lib.unescape(cats[-1][1]).strip() if cats else default_category
        cards.append((title, "https://www.cliniciansbrief.com" + path, category))
    return cards

def clean_text(text):
    return html_lib.unescape(re.sub(r'\s+', ' ', text)).strip()

def cb_article_excerpt(url):
    """아티클 페이지의 meta description을 요약용 본문으로 사용한다."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": CB_UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            page = r.read().decode("utf-8", errors="ignore")
        m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', page)
        if not m:
            m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', page)
        return clean_text(m.group(1))[:500] if m else ""
    except Exception as e:
        print(f"    CB 본문 오류: {e}")
        return ""


def previous_cb_items():
    """이전 CB 목록을 결정적 ID로 정리해서 돌려준다(수집 실패 시 대체용)."""
    items = []
    for url, article in load_previous_cb().items():
        article = dict(article)
        article["id"] = cb_article_id(url)
        article["date"] = normalize_date(article.get("date")) or datetime.now().strftime("%Y-%m-%d")
        article.setdefault("category", "Clinician's Brief")
        items.append(article)
    return items[:CB_MAX]

def fetch_clinicians_brief():
    previous = load_previous_cb()
    today = datetime.now().strftime("%Y-%m-%d")
    articles = []
    seen = set()
    for page_url, default_category in CB_CATEGORY_PAGES:
        if len(articles) >= CB_MAX:
            break
        try:
            req = urllib.request.Request(page_url, headers={"User-Agent": CB_UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                page_html = r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"  → CB 목록 오류 ({page_url}): {e}")
            continue

        cards = parse_cb_page(page_html, default_category)
        print(f"  {page_url} → 아티클 {len(cards)}개 발견")
        for title, url, category in cards:
            if len(articles) >= CB_MAX or url in seen:
                continue
            seen.add(url)

            prev = previous.get(url, {})
            # 이미 본 아티클은 처음 확인한 날짜를 유지 (매일 NEW로 보이지 않도록)
            date = normalize_date(prev.get("date")) or today
            summary_ko = prev.get("summary_ko") or ""
            abstract = prev.get("abstract") or ""

            if not abstract:
                abstract = cb_article_excerpt(url)
                time.sleep(0.3)

            if not summary_ko:
                print(f"    CB 요약 중: {title[:40]}...")
                summary_ko = summarize_ko(title, abstract)
                time.sleep(0.3)

            articles.append({
                "id": cb_article_id(url),
                "title": title,
                "authors": "Clinician's Brief",
                "journal": "Clinician's Brief",
                "category": category,
                "type": "cb",
                "date": date,
                "url": url,
                "abstract": abstract,
                "summary_ko": summary_ko,
            })
    print(f"  → Clinician's Brief {len(articles)}편")
    return articles

def main():
    all_papers = []
    for j in JOURNALS:
        print(f"Fetching {j['name']}...")
        try:
            papers = get_papers(j)
            all_papers.extend(papers)
            print(f"  → {len(papers)}편")
        except Exception as e:
            print(f"  → 오류: {e}")
        time.sleep(0.5)

    all_papers.sort(key=lambda x: x.get("date", ""), reverse=True)

    # PubMed이 전부 실패하면 기존 논문 데이터를 지우지 않고 유지한다
    if not all_papers:
        previous_papers = load_previous_papers()
        if previous_papers:
            print("  → PubMed 수집 실패: 기존 논문 목록을 유지합니다.")
            all_papers = previous_papers

    print("Fetching Clinician's Brief...")
    cb_articles = fetch_clinicians_brief()
    if not cb_articles:
        cb_articles = previous_cb_items()
        if cb_articles:
            print("  → CB 수집 실패: 기존 CB 목록을 유지합니다.")

    output = {
        "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "total": len(all_papers),
        "papers": all_papers,
        "clinicians_brief": cb_articles,
    }

    with open("papers.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n완료! 논문 {len(all_papers)}편 + CB {len(cb_articles)}편 저장됨 → papers.json")

if __name__ == "__main__":
    main()
