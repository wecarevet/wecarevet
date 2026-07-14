import urllib.request
import urllib.parse
import json
import time
import os
from datetime import datetime, timedelta

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

JOURNALS = [
    {"name": "AJVR",         "query": '"Am J Vet Res"[jour]'},
    {"name": "JVIM",         "query": '"J Vet Intern Med"[jour]'},
    {"name": "JVCS",         "query": '"J Vet Cardiol"[jour]'},
    {"name": "JSAP",         "query": '"J Small Anim Pract"[jour]'},
    {"name": "JAVMA",        "query": '"J Am Vet Med Assoc"[jour]'},
    {"name": "Vet J",        "query": '"Vet J"[jour]'},
    {"name": "BMC Vet Res",  "query": '"BMC Vet Res"[jour]'},
    {"name": "Vet Clin Pathol", "query": '"Vet Clin Pathol"[jour]'},
]

SMALL_ANIMAL = '("dogs"[tiab] OR "cats"[tiab] OR "feline"[tiab] OR "canine"[tiab] OR "small animal"[tiab])'
BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

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
    query = urllib.parse.quote(
        f'({journal["query"]}) AND {SMALL_ANIMAL} AND ("{date_from}"[PDAT] : "{date_to}"[PDAT])'
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
    import re
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
            "date": item.get("pubdate", ""),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "abstract": abstract[:500] if abstract else "",
            "summary_ko": summary_ko,
        })
    return papers

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

output = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    "total": len(all_papers),
    "papers": all_papers,
}

with open("papers.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n완료! 총 {len(all_papers)}편 저장됨 → papers.json")
