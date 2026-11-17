import urllib.request
import urllib.error
import urllib.parse
import json
import time
import os
import re
import hashlib
import html as html_lib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# 한글 요약은 논문 수가 많아 순차로 하면 30분 가까이 걸린다.
# 소수 병렬로 돌려 5~6분 안에 끝내고(자동 업데이트 실행 시간 단축), 429는 재시도한다.
SUMMARY_WORKERS = int(os.environ.get("SUMMARY_WORKERS", "6") or 6)
SUMMARY_ATTEMPTS = 4

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
    {"name": "JFMS",         "query": '"J Feline Med Surg"[jour]',                       "type": "vet"},
    {"name": "VRU",          "query": '"Vet Radiol Ultrasound"[jour]',                   "type": "vet"},
    {"name": "VAA",          "query": '"Vet Anaesth Analg"[jour]',                       "type": "vet"},
    {"name": "Vet Surg",     "query": '"Vet Surg"[jour]',                                "type": "vet"},
    {"name": "Vet Dermatol", "query": '"Vet Dermatol"[jour]',                            "type": "vet"},
    {"name": "VCO",          "query": '"Vet Comp Oncol"[jour]',                          "type": "vet"},
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

# ── 진료과목 태그 ──
SPECIALTY_TAGS = ["심장", "신장/비뇨", "내과/내분비", "응급/중환자", "마취/진통",
                  "외과/정형", "영상", "종양", "피부", "고양이", "기타"]

# 모델 응답이 없거나 JSON 파싱에 실패했을 때 쓰는 키워드 기반 추정
SPECIALTY_KEYWORDS = {
    "심장": ["cardiac", "heart", "mitral", "cardiomyopathy", "arrhythmia", "torsemide",
             "tolvaptan", "diuretic", "valve", "congestive", "atrial", "ventric"],
    "신장/비뇨": ["kidney", "renal", "azotemia", "urinary", "bladder", "urolith", "proteinuria",
                  "creatinine", "nephro", "ureter", "urethra", "sdma", "incontinence"],
    "내과/내분비": ["diabetes", "endocrine", "thyroid", "liver", "hepatic", "pancreatitis", "gastro",
                   "intestin", "adrenal", "cushing", "hyperadrenocorticism", "hypothyroid", "anemia"],
    "응급/중환자": ["emergency", "critical", "shock", "sepsis", "resuscitation", "triage",
                   "hypovolemia", "intensive care"],
    "마취/진통": ["anesthesia", "anaesthesia", "analgesia", "analgesic", "pain score", "sedation",
                  "opioid", "propofol", "isoflurane", "locoregional"],
    "외과/정형": ["surgery", "surgical", "fracture", "orthopedic", "laparoscopy", "wound", "repair",
                  "resection", "cruciate", "stifle", "osteotomy", "arthroscopy"],
    "영상": ["radiography", "radiograph", "ultrasound", "computed tomography", " ct ", "mri",
             "magnetic resonance", "echocardiograph", "radiolog", "fluoroscop"],
    "종양": ["tumor", "tumour", "cancer", "neoplasia", "lymphoma", "mast cell", "sarcoma", "oncology",
             "malignant", "carcinoma", "chemotherapy"],
    "피부": ["skin", "dermatitis", "atopy", "pruritus", "alopecia", "allergy", "dermatolog", "otitis"],
    "고양이": ["cat", "cats", "feline"],
}


def guess_specialties(text, limit=2):
    """제목/초록 키워드로 진료과목 태그를 추정한다(모델 응답 실패 시 대체)."""
    low = " " + (text or "").lower() + " "
    scored = []
    for tag, keywords in SPECIALTY_KEYWORDS.items():
        # 단어 경계로 매칭 ('renal'이 'adrenal'에 걸리는 것 방지)
        score = sum(1 for k in keywords
                    if re.search(r'\b' + re.escape(k.strip()) + r'\b', low))
        if score:
            scored.append((score, tag))
    if not scored:
        return ["기타"]
    scored.sort(key=lambda x: (-x[0], SPECIALTY_TAGS.index(x[1])))
    return [tag for _, tag in scored[:limit]]


def clean_summary(text):
    """모델이 붙인 맨 앞머리 제목(# ...)과 굵게 표기(**)를 제거해
    카드에 그대로 보이도록 정리한다."""
    text = re.sub(r'^\s*#{1,6}[^\n]*\n*', '', text, count=1)
    text = text.replace("**", "").replace("__", "")
    return re.sub(r'\n{2,}', '\n', text).strip()

def build_prompt(title, abstract):
    tags = "[" + ", ".join('"%s"' % t for t in SPECIALTY_TAGS) + "]"
    return (
        "다음 수의학 논문을 전문 수의사가 임상 공부에 바로 활용할 수 있도록 한국어 스터디 노트로 정리해줘.\n"
        "설명이나 인사말 없이, 아래 형식의 JSON 객체 하나만 출력해.\n\n"
        '{"specialty": ["태그"], "summary_ko": "[핵심 결론] ...\\n[방법·수치] ...\\n[임상 적용·한계] ..."}\n\n'
        "규칙:\n"
        f"- specialty: {tags} 중에서 이 논문 주제에 맞는 태그 1~2개만 배열로. 해당 주제가 고양이 연구면 \"고양이\"도 함께 넣어.\n"
        "- summary_ko: 정확히 세 줄. 각 줄은 반드시 아래 라벨로 시작하고, 라벨당 1~3문장.\n"
        "  [핵심 결론] 이 연구가 밝혀낸 결론\n"
        "  [방법·수치] 연구 설계, 대상(종/수/집단), 주요 수치(민감도·특이도·P값·위험비·용량 등)\n"
        "  [임상 적용·한계] 실제 진료에서 어떻게 쓸지와 한계(후향적·소규모·단일기관 등)\n"
        "- 초록에 있는 내용만 쓴다. 수치가 없으면 '수치 제시 없음'이라고 쓴다.\n"
        "- 마크다운(#, **, -, *) 기호를 쓰지 않는다.\n\n"
        f"제목: {title}\n\n초록: {abstract}"
    )


def extract_json(text):
    """코드펜스/설명이 섞인 응답에서 첫 JSON 객체를 꺼낸다."""
    t = (text or "").strip()
    t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
    t = re.sub(r'\s*```\s*$', '', t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def normalize_specialty(value):
    """모델이 준 태그를 허용 목록 안으로 정리한다."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    tags = []
    for v in value:
        v = str(v).strip()
        if v in SPECIALTY_TAGS and v not in tags:
            tags.append(v)
    return tags[:2]


RETRYABLE_HTTP = (408, 409, 429, 500, 502, 503, 504, 529)


def call_claude(payload, attempts=SUMMARY_ATTEMPTS):
    """한글 요약 API 호출. 429·5xx와 일시적 네트워크 오류는 지수 백오프로 재시도."""
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01"
        }
    )
    delay = 2.0
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in RETRYABLE_HTTP or attempt == attempts - 1:
                raise
            wait = delay
            retry_after = (e.headers or {}).get("retry-after", "") if e.headers else ""
            try:
                wait = max(wait, min(float(retry_after), 20.0))
            except (TypeError, ValueError):
                pass
            print(f"  요약 재시도({e.code}) {wait:.0f}s 후...")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt == attempts - 1:
                raise
            wait = delay
            print(f"  요약 재시도(네트워크) {wait:.0f}s 후...")
        time.sleep(wait)
        delay = min(delay * 2, 20.0)
    raise last if last else RuntimeError("요약 호출 실패")


def summarize_ko(title, abstract):
    """(한국어 스터디 노트, 진료과목 태그 목록)을 돌려준다."""
    fallback_tags = guess_specialties(f"{title} {abstract}")
    if not ANTHROPIC_API_KEY or not abstract:
        return "", fallback_tags
    try:
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 700,
            "messages": [{"role": "user", "content": build_prompt(title, abstract)}]
        }).encode()
        data = call_claude(payload)
        text = "".join(
            block.get("text", "") for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not text:
            return "", fallback_tags

        parsed = extract_json(text)
        if parsed:
            summary = clean_summary(str(parsed.get("summary_ko") or ""))
            tags = normalize_specialty(parsed.get("specialty"))
            if summary:
                return summary, (tags or fallback_tags)

        # JSON이 아니거나 비어 있으면 본문을 그대로 정리해 쓴다
        summary = clean_summary(text)
        if summary and not summary.lstrip().startswith("{"):
            return summary, fallback_tags
        return "", fallback_tags
    except Exception as e:
        print(f"  요약 오류: {e}")
        return "", fallback_tags

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
        abstract = (abstracts.get(pid, "") or "").strip()
        # 초록이 없는 편집자 노트·서평 등은 스터디 피드에서 제외
        if not abstract:
            continue
        title = item.get("title", "").replace("<b>", "").replace("</b>", "")

        papers.append({
            "id": pid,
            "title": title,
            "authors": ", ".join(a.get("name", "") for a in item.get("authors", [])[:5]),
            "journal": journal["name"],
            "type": journal["type"],
            "date": item.get("pubdate", ""),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "abstract": abstract,
            "summary_ko": "",
            "specialty": [],
        })
    return papers


def summarize_papers(papers, label=""):
    """아직 한글 요약이 없는 논문들을 병렬로 요약해 채운다(목록 순서는 그대로 유지)."""
    todo = [p for p in papers if not p.get("summary_ko")]
    if not todo:
        return papers
    if not ANTHROPIC_API_KEY:
        for p in todo:
            p["specialty"] = p.get("specialty") or guess_specialties(f"{p['title']} {p['abstract']}")
        return papers

    print(f"  {label}요약 {len(todo)}편 (동시 {SUMMARY_WORKERS})")
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, SUMMARY_WORKERS)) as ex:
        futures = {ex.submit(summarize_ko, p["title"], p["abstract"]): p for p in todo}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                summary_ko, specialty = fut.result()
            except Exception as e:
                print(f"  요약 실패: {p['title'][:40]} ({e})")
                summary_ko, specialty = "", guess_specialties(f"{p['title']} {p['abstract']}")
            p["summary_ko"] = summary_ko
            p["specialty"] = specialty or guess_specialties(f"{p['title']} {p['abstract']}")
            done += 1
            if done % 20 == 0 or done == len(todo):
                print(f"    ...{done}/{len(todo)}")
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
    cards_out = []
    seen = set()
    for page_url, default_category in CB_CATEGORY_PAGES:
        if len(cards_out) >= CB_MAX:
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
            if len(cards_out) >= CB_MAX or url in seen:
                continue
            seen.add(url)

            prev = previous.get(url, {})
            # 이미 본 아티클은 처음 확인한 날짜를 유지 (매일 NEW로 보이지 않도록)
            date = normalize_date(prev.get("date")) or today
            summary_ko = prev.get("summary_ko") or ""
            abstract = prev.get("abstract") or ""
            specialty = normalize_specialty(prev.get("specialty"))

            if not abstract:
                abstract = cb_article_excerpt(url)
                time.sleep(0.2)

            cards_out.append({
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
                "specialty": specialty,
            })

    # 새로 추가된 아티클의 요약은 병렬로 채운다
    summarize_papers(cards_out, "CB ")
    for a in cards_out:
        a["specialty"] = normalize_specialty(a.get("specialty")) or \
            guess_specialties(f"{a['title']} {a['abstract']}")

    print(f"  → Clinician's Brief {len(cards_out)}편")
    return cards_out

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
        time.sleep(0.3)

    if all_papers:
        summarize_papers(all_papers, "PubMed ")
        for p in all_papers:
            p["abstract"] = (p.get("abstract") or "")[:500]

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
