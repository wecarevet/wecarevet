import urllib.request
import urllib.error
import urllib.parse
import json
import time
import os
import re
import sys
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
        "- summary_ko: 정확히 세 줄. 각 줄은 반드시 아래 라벨로 시작하고, 라벨당 1~2문장(전체 600자 이내).\n"
        "  [핵심 결론] 이 연구가 밝혀낸 결론\n"
        "  [방법·수치] 연구 설계, 대상(종/수/집단), 주요 수치(민감도·특이도·P값·위험비·용량 등)\n"
        "  [임상 적용·한계] 실제 진료에서 어떻게 쓸지와 한계(후향적·소규모·단일기관 등)\n"
        "- 초록에 있는 내용만 쓴다. 수치가 없으면 '수치 제시 없음'이라고 쓴다.\n"
        "- 마크다운(#, **, -, *) 기호를 쓰지 않는다.\n\n"
        f"제목: {title}\n\n초록: {abstract}"
    )


# ── 모델 응답에서 JSON·요약 꺼내기 ──
# 모델이 코드펜스(```json ... ```)로 감싸 보내거나, 앞뒤에 설명을 붙이거나,
# max_tokens에 걸려 JSON이 중간에서 잘려 오는 경우가 있다.
# 그때도 논문 카드에 원문 JSON이 그대로 노출되지 않도록 단계적으로 복구한다.
_CODE_FENCE_RE = re.compile(r'```[a-zA-Z0-9_+-]*\s*\n?(.*?)(?:```|\Z)', re.DOTALL)
_SUMMARY_KEY_RE = re.compile(r'"summary_ko"\s*:\s*"')
_SPECIALTY_KEY_RE = re.compile(r'"specialty"\s*:\s*\[([^\]]*)\]', re.DOTALL)


def _strip_fences(text):
    """응답 어디에 있든 코드펜스 표기(```json 등)를 걷어낸다."""
    return re.sub(r'```[a-zA-Z0-9_+-]*', '', text or '').strip()


def _relax_json(text):
    """사소한 문법 오류를 고쳐 한 번 더 파싱을 시도한다.
    - 문자열 안에 이스케이프 없이 들어온 줄바꿈·탭을 이스케이프
    - 객체·배열 끝의 마지막 쉼표 제거"""
    out = []
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            elif ch == "\\":
                out.append(ch)
                esc = True
            elif ch == '"':
                out.append(ch)
                in_str = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                continue
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
    return re.sub(r',\s*([}\]])', r'\1', "".join(out))


def _json_candidates(text):
    """응답에서 JSON 객체로 보이는 후보들을 넓은 것부터 만들어 둔다."""
    t = (text or "").strip()
    cands = []

    def add(value):
        value = (value or "").strip()
        if value and value not in cands:
            cands.append(value)

    # 1) 코드펜스 안쪽
    for m in _CODE_FENCE_RE.finditer(t):
        add(m.group(1))
    # 2) 펜스를 걷어낸 전체
    plain = _strip_fences(t)
    add(plain)
    # 3) 첫 { 부터 마지막 } 까지 / 4) 첫 { 부터 끝까지(잘린 응답)
    for src in list(cands):
        start, end = src.find("{"), src.rfind("}")
        if start != -1 and end > start:
            add(src[start:end + 1])
        if start != -1:
            add(src[start:])
    # 5) 중괄호 짝이 처음 맞는 블록
    for src in list(cands):
        start = src.find("{")
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(src)):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    add(src[start:i + 1])
                    break
    return cands


def extract_json(text):
    """코드펜스/설명/꼬리 텍스트가 섞인 응답에서 첫 JSON 객체를 꺼낸다."""
    for cand in _json_candidates(text):
        for attempt in (cand, _relax_json(cand)):
            try:
                obj = json.loads(attempt)
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def _unescape_json_string(raw):
    """따옴표 없이 꺼낸 JSON 문자열 본문의 이스케이프를 되돌린다."""
    try:
        return json.loads('"' + raw + '"')
    except ValueError:
        return (raw.replace('\\n', '\n').replace('\\"', '"')
                   .replace('\\\\', '\\').replace('\\t', '\t'))


def salvage_summary_fields(text):
    """JSON이 깨져 json.loads가 실패할 때(잘린 응답 등) 필드 값을 정규식으로 건져낸다."""
    out = {}
    m = _SPECIALTY_KEY_RE.search(text or "")
    if m:
        out["specialty"] = re.findall(r'"([^"]*)"', m.group(1))
    m = _SUMMARY_KEY_RE.search(text or "")
    if m:
        rest = (text or "")[m.end():]
        # 이스케이프되지 않은 다음 따옴표(없으면 응답 끝)까지가 값
        end = len(rest)
        i = 0
        while i < len(rest):
            if rest[i] == "\\":
                i += 2
                continue
            if rest[i] == '"':
                end = i
                break
            i += 1
        out["summary_ko"] = _unescape_json_string(rest[:end])
    return out


def looks_like_raw_json(text):
    """카드에 그대로 두면 안 되는 원문 JSON·코드펜스 문자열인지 판별한다."""
    s = (text or "").strip()
    if not s:
        return False
    if s.startswith("```") or s.startswith("{"):
        return True
    return '"summary_ko"' in s or '"specialty"' in s


def parse_summary_response(text):
    """모델 응답에서 (한글 요약, 진료과목 태그)를 꺼낸다. 못 꺼내면 ("", []).

    정상 JSON → 문법을 살짝 고쳐 재시도 → 잘린 JSON에서 필드만 건져내기 → 평문 응답 순서로
    시도하고, 그래도 원문 JSON 모양이면 버린다(카드 노출 방지)."""
    summary, tags = "", []
    parsed = extract_json(text)
    if parsed:
        summary = clean_summary(str(parsed.get("summary_ko") or ""))
        tags = normalize_specialty(parsed.get("specialty"))
    if not summary:
        salvaged = salvage_summary_fields(text)
        summary = clean_summary(salvaged.get("summary_ko") or "")
        tags = tags or normalize_specialty(salvaged.get("specialty"))
    if not summary and not looks_like_raw_json(text):
        # JSON이 아닌 평문 응답은 그대로 정리해 쓴다
        summary = clean_summary(text)
    if summary and looks_like_raw_json(summary):
        summary = ""
    return summary, tags


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
            # 700이면 긴 논문에서 응답이 중간에 잘려 JSON이 깨졌다(2026-11-23 확인).
            "max_tokens": 1200,
            "messages": [{"role": "user", "content": build_prompt(title, abstract)}]
        }).encode()
        data = call_claude(payload)
        text = "".join(
            block.get("text", "") for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not text:
            return "", fallback_tags
        if data.get("stop_reason") == "max_tokens":
            print("  요약 응답이 max_tokens에서 잘렸습니다. 남은 부분까지 복구해 사용합니다.")

        summary, tags = parse_summary_response(text)
        if summary:
            return summary, (tags or fallback_tags)
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


def repair_paper_summaries(items, verbose=True):
    """이미 저장된 항목의 깨진 summary_ko(LLM 원문 JSON 문자열)를 제자리에서 복구한다.

    merge_papers·merge_cb_articles는 기존 summary_ko를 그대로 살리므로, 한 번 깨져
    저장된 항목은 코드를 고쳐도 그대로 남는다. 매 실행 전에 이 함수를 돌려 누적
    papers.json 안의 깨진 값을 정상 텍스트로 바꿔 둔다.
    """
    fixed = 0
    for p in items:
        raw = p.get("summary_ko") or ""
        if not looks_like_raw_json(raw):
            continue
        summary, tags = parse_summary_response(raw)
        p["summary_ko"] = summary
        if tags:
            p["specialty"] = tags
        elif not normalize_specialty(p.get("specialty")):
            p["specialty"] = guess_specialties(f"{p.get('title', '')} {p.get('abstract', '')}")
        fixed += 1
        if verbose:
            print(f"  요약 복구: {paper_key(p)} ({len(raw)}자 → {len(summary)}자)")
    return fixed


def summarize_papers(papers, label=""):
    """아직 한글 요약이 없는 논문들을 병렬로 요약해 채운다(목록 순서는 그대로 유지).
    이미 summary_ko가 있는(기존에 요약해 둔) 논문은 건너뛰므로 누적 병합 후에도 다시 요약하지 않는다."""
    todo = [p for p in papers if not p.get("summary_ko")]
    if not todo:
        return papers
    if not ANTHROPIC_API_KEY:
        for p in todo:
            p["specialty"] = p.get("specialty") or guess_specialties(f"{p.get('title', '')} {p.get('abstract', '')}")
        return papers

    print(f"  {label}요약 {len(todo)}편 (동시 {SUMMARY_WORKERS})")
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, SUMMARY_WORKERS)) as ex:
        futures = {ex.submit(summarize_ko, p.get("title", ""), p.get("abstract", "")): p for p in todo}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                summary_ko, specialty = fut.result()
            except Exception as e:
                print(f"  요약 실패: {p.get('title', '')[:40]} ({e})")
                summary_ko, specialty = "", guess_specialties(f"{p.get('title', '')} {p.get('abstract', '')}")
            p["summary_ko"] = summary_ko
            p["specialty"] = specialty or guess_specialties(f"{p.get('title', '')} {p.get('abstract', '')}")
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

MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

def parse_pub_date(value):
    """PubMed·ISO 날짜 표기를 정렬용 (연, 월, 일) 튜플로 바꾼다.
    '2026-11-05', '2026 Nov 5', '2026 Nov', '2026 Nov-Dec', '2026' 등을 처리하고,
    해석할 수 없는 값은 (0, 0, 0)으로 두어 맨 뒤로 보낸다."""
    s = str(value or "").strip()
    if not s:
        return (0, 0, 0)
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r'^(\d{4})\s+([A-Za-z]{3})(?:\s*[-\u2013]\s*[A-Za-z]{3})?(?:\s+(\d{1,2}))?$', s)
    if m:
        return (int(m.group(1)), MONTH_NUM.get(m.group(2).title(), 0), int(m.group(3) or 0))
    m = re.match(r'^(\d{4})$', s)
    if m:
        return (int(m.group(1)), 0, 0)
    return (0, 0, 0)

def load_previous_papers():
    """이전 papers.json의 PubMed 논문 목록(누적 병합의 기준)."""
    try:
        with open("papers.json", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("papers", [])
    except (OSError, ValueError):
        return []

def paper_key(item):
    """논문 고유 키. PubMed는 pmid(id)를, 그 밖에는 url을 쓴다."""
    for k in ("pmid", "id", "url"):
        v = item.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""

def merge_papers(fresh, previous):
    """새로 받아온 논문을 기존 papers.json 목록에 누적 병합한다.

    - 고유 키(pmid/id/url)가 같은 논문은 이미 만들어 둔 summary_ko·specialty를 그대로 살린다.
      (summarize_papers가 summary_ko 있는 논문을 건너뛰므로 API 비용도 다시 들지 않는다)
    - 이번 수집 범위(retmax=30, 최근 60일) 밖으로 밀려난 과거 논문도 하나도 버리지 않고 유지한다.
    - 반환값: (병합된 전체 목록, 이번에 새로 추가된 편수). 정렬은 호출 쪽에서 한다.
    """
    prev_by_key = {}
    for p in previous:
        k = paper_key(p)
        if k and k not in prev_by_key:
            prev_by_key[k] = p

    merged = []
    seen = set()
    added = 0
    for p in fresh:
        k = paper_key(p)
        if not k or k in seen:
            continue
        seen.add(k)
        old = prev_by_key.get(k)
        if old is None:
            merged.append(p)
            added += 1
            continue
        # 이미 있던 논문: 수집값(제목·날짜·초록 등)은 새 값으로 갱신하되 요약·태그는 보존
        item = dict(old)
        for field, value in p.items():
            if field in ("summary_ko", "specialty"):
                continue
            if value not in (None, "", []):
                item[field] = value
        if not item.get("summary_ko") and p.get("summary_ko"):
            item["summary_ko"] = p["summary_ko"]
        if not item.get("specialty") and p.get("specialty"):
            item["specialty"] = p["specialty"]
        merged.append(item)

    # 이번에 다시 받아오지 않은 과거 논문도 순서 그대로 뒤에 붙인다
    for p in previous:
        k = paper_key(p)
        if not k or k in seen:
            continue
        seen.add(k)
        merged.append(p)
    return merged, added

def _load_papers_json():
    with open("papers.json", encoding="utf-8") as f:
        return json.load(f)


def repair_existing():
    """papers.json만 제자리에서 복구한다(PubMed 수집·API 호출 없음).
    실행: python fetch_papers.py --repair"""
    try:
        data = _load_papers_json()
    except (OSError, ValueError) as e:
        print(f"papers.json을 읽지 못했습니다: {e}")
        return 1
    fixed = repair_paper_summaries(data.get("papers", []))
    fixed += repair_paper_summaries(data.get("clinicians_brief", []))
    if fixed:
        with open("papers.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"복구 {fixed}건")
    return check_existing() if fixed else 0


def check_existing():
    """papers.json에 카드용이 아닌 원문 JSON 문자열이 남았는지 검사한다.
    실행: python fetch_papers.py --check (깨진 값이 있으면 종료코드 1)"""
    try:
        data = _load_papers_json()
    except (OSError, ValueError) as e:
        print(f"papers.json을 읽지 못했습니다: {e}")
        return 1
    broken = []
    for group in ("papers", "clinicians_brief"):
        for item in data.get(group, []):
            if looks_like_raw_json(item.get("summary_ko")):
                broken.append((group, paper_key(item) or item.get("url", "")))
            if not isinstance(item.get("specialty"), list):
                print(f"  specialty 형식 이상(목록 아님): {paper_key(item) or item.get('url', '')}")
    print(f"검사 대상: 논문 {len(data.get('papers', []))}편 + CB {len(data.get('clinicians_brief', []))}편")
    if broken:
        print(f"원문 JSON이 남은 항목 {len(broken)}건:")
        for group, key in broken:
            print(f"  - [{group}] {key}")
        return 1
    print("원문 JSON이 남은 항목 0건")
    return 0


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
    """이전 CB 목록을 결정적 ID로 정리해서 돌려준다(수집 실패 시 대체용).
    상한 없이 저장된 CB 아티클을 전부 돌려준다(CB_MAX는 한 번에 긁는 양에만 쓴다)."""
    items = []
    for url, article in load_previous_cb().items():
        article = dict(article)
        article["id"] = cb_article_id(url)
        article["date"] = normalize_date(article.get("date")) or str(article.get("date") or "")
        article.setdefault("category", "Clinician's Brief")
        items.append(article)
    items.sort(key=lambda a: parse_pub_date(a.get("date")), reverse=True)
    return items

def merge_cb_articles(fresh, previous):
    """Clinician's Brief 아티클을 기존 목록에 누적 병합한다.

    CB_MAX는 '한 번에 긁어오는 양'에만 적용하고, 저장 목록은 기존 글을 모두 유지한 뒤
    새 URL만 위에 보태 날짜순으로 정렬한다.
    """
    prev_by_url = {}
    for a in previous:
        url = a.get("url")
        if url and url not in prev_by_url:
            prev_by_url[url] = a

    merged = []
    seen = set()
    added = 0
    for a in fresh:
        url = a.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        old = prev_by_url.get(url)
        if old is None:
            merged.append(a)
            added += 1
            continue
        item = dict(old)
        for field, value in a.items():
            # 처음 확인한 날짜와 이미 만든 요약·태그·ID는 유지한다
            if field in ("date", "summary_ko", "specialty", "id"):
                continue
            if value not in (None, "", []):
                item[field] = value
        if not item.get("summary_ko") and a.get("summary_ko"):
            item["summary_ko"] = a["summary_ko"]
        if not normalize_specialty(item.get("specialty")) and a.get("specialty"):
            item["specialty"] = a["specialty"]
        merged.append(item)

    for a in previous:
        url = a.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(a)

    for a in merged:
        url = a.get("url") or ""
        a["id"] = a.get("id") or (cb_article_id(url) if url else "")
        a["date"] = normalize_date(a.get("date")) or str(a.get("date") or "")
        a.setdefault("category", "Clinician's Brief")
    return merged, added

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

    if not cards_out:
        print("  → CB 목록 수집 실패: 기존 CB 목록을 유지합니다.")

    # 기존에 저장돼 있던 CB 글을 모두 유지하고 새 글만 위에 병합한다
    merged, added = merge_cb_articles(cards_out, list(previous.values()))
    merged.sort(key=lambda a: parse_pub_date(a.get("date")), reverse=True)
    print(f"  → Clinician's Brief {len(merged)}편 (기존 {len(merged) - added}편 + 신규 {added}편)")
    return merged

def main():
    fresh_papers = []
    for j in JOURNALS:
        print(f"Fetching {j['name']}...")
        try:
            papers = get_papers(j)
            fresh_papers.extend(papers)
            print(f"  → {len(papers)}편")
        except Exception as e:
            print(f"  → 오류: {e}")
        time.sleep(0.3)

    if not fresh_papers:
        print("  → PubMed 수집 실패: 기존 논문 목록을 유지합니다.")

    # 새로 받아온 논문을 기존 papers.json과 누적 병합한다.
    # (이미 요약한 논문은 summary_ko·specialty를 그대로 살리고,
    #  이번 수집 범위 밖으로 밀려난 과거 논문도 하나도 버리지 않는다)
    previous_papers = load_previous_papers()
    all_papers, added = merge_papers(fresh_papers, previous_papers)
    if previous_papers:
        print(f"  → 기존 {len(previous_papers)}편 보존 + 신규 {added}편 = {len(all_papers)}편")

    # 예전에 깨져 저장된 요약(원문 JSON 문자열)은 여기서 복구하고 나서 빈 요약만 다시 만든다
    repaired = repair_paper_summaries(all_papers)
    if repaired:
        print(f"  → 깨진 요약 {repaired}건 복구")

    summarize_papers(all_papers, "PubMed ")
    for p in all_papers:
        p["abstract"] = (p.get("abstract") or "")[:500]

    all_papers.sort(key=lambda x: parse_pub_date(x.get("date")), reverse=True)

    print("Fetching Clinician's Brief...")
    cb_articles = fetch_clinicians_brief()
    if not cb_articles:
        cb_articles = previous_cb_items()
        if cb_articles:
            print(f"  → CB 수집 실패: 기존 CB {len(cb_articles)}편을 유지합니다.")
    repair_paper_summaries(cb_articles)

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
    if "--repair" in sys.argv:
        sys.exit(repair_existing())
    if "--check" in sys.argv:
        sys.exit(check_existing())
    main()
