import urllib.request
import urllib.parse
import json
import time
from datetime import datetime

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

def get_papers(journal):
    query = urllib.parse.quote(f'({journal["query"]}) AND {SMALL_ANIMAL}')
    search = fetch(f"{BASE}esearch.fcgi?db=pubmed&term={query}&retmax=15&sort=pub+date&retmode=json")
    ids = search.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    time.sleep(0.4)
    summary = fetch(f"{BASE}esummary.fcgi?db=pubmed&id={','.join(ids)}&retmode=json")
    result = summary.get("result", {})
    papers = []
    for pid in ids:
        item = result.get(pid)
        if not item:
            continue
        papers.append({
            "id": pid,
            "title": item.get("title", "").replace("<b>", "").replace("</b>", ""),
            "authors": ", ".join(a.get("name", "") for a in item.get("authors", [])[:5]),
            "journal": journal["name"],
            "date": item.get("pubdate", ""),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
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

# 날짜순 정렬
all_papers.sort(key=lambda x: x.get("date", ""), reverse=True)

output = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    "total": len(all_papers),
    "papers": all_papers,
}

with open("papers.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n완료! 총 {len(all_papers)}편 저장됨 → papers.json")
