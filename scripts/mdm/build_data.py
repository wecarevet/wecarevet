#!/usr/bin/env python3
"""Builds data.json for md-meta.html from the MDM snapshot in scripts/mdm/data/.

Run from anywhere: python3 scripts/mdm/build_data.py
The tier list is fetched live from masterduelmeta.com when the network allows it
(MDM_REFRESH=0 or --no-fetch turns that off); every other input is the committed
snapshot under scripts/mdm/data/, refreshed by hand when a new banlist/pack lands.
"""
import json, re, os, sys, unicodedata, html, urllib.request
from collections import Counter, OrderedDict

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
sys.path.insert(0, BASE)
from banlist_raw import FORBIDDEN, LIMITED1, LIMITED2

try:
    from bs4 import BeautifulSoup
except ImportError:                                    # pip install beautifulsoup4
    sys.exit('build_data: beautifulsoup4 is required (pip install beautifulsoup4 lxml)')

try:
    import lxml  # noqa: F401
    PARSER = 'lxml'
except ImportError:
    PARSER = 'html.parser'

TIER_URL = 'https://www.masterduelmeta.com/tier-list'
REFRESH = '--no-fetch' not in sys.argv and os.environ.get('MDM_REFRESH', '1') != '0'

def load(name):
    with open(os.path.join(DATA, name), encoding='utf-8') as f:
        return json.load(f)

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; wecarevet-mdm/1.0; +https://wecarevet.github.io/wecarevet/md-meta.html)',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.8',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')

def norm(s):
    s = s.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s

# ---------- reference maps ----------
# rarities.json: normalised english card name -> rarity, from MDM's card list
# ko_names.json: normalised english card name -> korean name, from the YGOPRODeck ko card data
rarity_map = load('rarities.json')
ko_map = load('ko_names.json')

def ko_of(name):
    hit = ko_map.get(norm(name))
    return hit if hit and re.search(r'[가-힣]', hit) else ''

def rar_of(name):
    return rarity_map.get(norm(name), '')

# ---------- tier list (parsed from the tier-list page SSR html) ----------
def parse_tier(page):
    soup = BeautifulSoup(page, PARSER)
    out = []
    for a in soup.select('a[href^="/tier-list/"]'):
        label = a.select_one('.label')
        if not label:
            continue
        href = a.get('href')
        cont = a.find_parent('div', class_=re.compile('column'))
        ptxt = cont.get_text(' ', strip=True) if cont else ''
        m = re.search(r'Power:\s*([\d.]+)', ptxt)
        m2 = re.search(r'Popularity:\s*([\d.]+)%', ptxt)
        kind = 'engine' if href.startswith('/tier-list/engines/') else 'deck'
        name = label.get_text(strip=True)
        if kind == 'engine':
            name = re.sub(r'\s*Engine$', '', name)
        out.append({'en': name, 'kind': kind, 'power': float(m.group(1)) if m else None,
                    'pop': float(m2.group(1)) if m2 else None, 'slug': href})
    return out

def tier_page():
    snapshot = open(os.path.join(DATA, 'tier.html'), encoding='utf-8').read()
    if REFRESH:
        try:
            live = http_get(TIER_URL)
            scored = [e for e in parse_tier(live) if e['power'] is not None]
            if len(scored) >= 20:
                print('tier-list: live page, %d ranked entries' % len(scored))
                return live
            print('tier-list: live page had %d ranked entries, keeping the snapshot' % len(scored))
        except Exception as e:
            print('tier-list: fetch failed (%s), keeping the snapshot' % e)
    else:
        print('tier-list: refresh disabled, using the snapshot')
    return snapshot

entries = parse_tier(tier_page())

# merge power and popularity rows
tiers = OrderedDict()
for e in entries:
    k = (e['en'], e['kind'])
    if k not in tiers:
        tiers[k] = {'en': e['en'], 'kind': e['kind'], 'slug': e['slug'], 'power': None, 'pop': None}
    if e['power'] is not None:
        tiers[k]['power'] = e['power']
    if e['pop'] is not None:
        tiers[k]['pop'] = e['pop']

def band(p):
    if p is None:
        return None
    if p >= 12:
        return 'T1'
    if p >= 7:
        return 'T2'
    if p >= 3:
        return 'T3'
    if p >= 1:
        return 'RG'
    return 'RG'

KO_THEME = {
    'Elfnote': '엘프노트', 'Dracotail': '드라코테일', 'Kewl Tune': '쿨튠', 'Blitzclique': '블리츠클리크',
    'Artmage': '아트메이지', 'Yummy': '야미', 'Invoked': '인보크드', 'Rikka': '리카', 'Branded': '브랜디드',
    'Witchcrafter': '위치크래프트', 'Vanquish Soul K9': '뱅퀴시 소울 K9', 'Snake-Eye Yummy': '스네이크아이 야미',
    'Dark Magician': '블랙 매지션', 'DoomZ': '둠Z', 'Mitsurugi': '미츠루기', 'Mermail Atlantean': '머메일 아틀란티안',
    'Sky Striker': '스카이 스트라이커', 'Super Quant': '슈퍼퀀트', 'Magistus Fairy Tail': '마기스투스 페어리테일',
    'Ryzeal Mitsurugi': '라이질 미츠루기', 'Mitsurugi Orcust': '미츠루기 오르커스트', 'Maliss': '말리스',
    'Rokket': '로켓', 'Magnet Warrior': '마그넷 워리어', 'Darklord': '다크로드', 'Tellarknight': '텔라나이트',
    'Lunalight': '루나라이트', 'Phantom Knights': '팬텀 나이츠', 'Blue-Eyes': '블루아이즈', 'HEROs': '히어로즈',
    'Orcust': '오르커스트', 'Elfnote Kewl Tune': '엘프노트 쿨튠', 'Elfnote White Forest': '엘프노트 화이트 포레스트',
    'K9': 'K9', 'Elfnote 엔진': '엘프노트 엔진', 'Yummy 엔진': '야미 엔진', 'Snake-Eye Fiendsmith': '스네이크아이 핀드스미스',
    'White Forest Azamina': '화이트 포레스트 아자미나', 'Yubel Fiendsmith': '유벨 핀드스미스', 'Tenpai Dragon': '텐파이 드래곤',
    'Tearlaments': '티어라멘츠', 'K9': 'K9', 'Magistus Charmer': '마기스투스 채머', 'Earth Machine': '어스 머신',
    'Lightsworn': '라이트로드', 'Shark': '샤크', 'Six Samurai': '식스 사무라이', 'Insect': '인섹트', 'Clown Crew': '클라운 크루',
    'Dinos': '다이노스', 'Yubel': '유벨', 'Snake-Eye Fire King': '스네이크아이 파이어 킹', 'Rescue-ACE': '레스큐 ACE',
    'Infernoble Knight': '인페르노블 나이트', 'Ritual Beasts': '리추얼 비스트', 'Crystron': '크리스트론', 'Azamina': '아자미나',
    'Radiant Typhoon': '래디언트 타이푼', 'Fiendsmith Control': '핀드스미스 컨트롤', 'Exosister': '엑소시스터', 'Spright': '스프라이트',
}
def ko_theme(name):
    return KO_THEME.get(name, '')

# ---------- decklists ----------
deckstats = load('deckstats.json')
mw = load('mw256_decks.json')
decks = []
def rar_count(items):
    ur = sum(n for n, _ in items if rar_of(_) == 'UR')
    sr = sum(n for n, _ in items if rar_of(_) == 'SR')
    return ur, sr

for d in mw:
    main = [[it['amount'], it['card']['name']] for it in d['main']]
    extra = [[it['amount'], it['card']['name']] for it in d['extra']]
    side = [[it['amount'], it['card']['name']] for it in d.get('side') or []]
    author = d.get('author')
    player = author.get('username') if isinstance(author, dict) else (author or '')
    decks.append({
        'src': 'MW', 'event': 'Dkayed Meta Weekly #256', 'eventShort': 'MW #256',
        'eventDate': '2026-11-16', 'placement': d.get('tournamentPlacement') or '',
        'player': player, 'archetype': (d.get('deckType') or {}).get('name') or '',
        'engines': [e.get('name') for e in (d.get('engines') or [])],
        'ur': d.get('urPrice'), 'sr': d.get('srPrice'),
        'main': main, 'extra': extra, 'side': side,
        'url': 'https://www.masterduelmeta.com' + (d.get('url') or ''),
        'source': 'MDM top decks API (Meta Weekly #256)',
    })

cc = load('cc_deckcontainers.json')
cc_meta = [
    ('1st Place', 'Railgun_toki', 'Artmage'),
    ('2nd Place', 'Nei', 'Dracotail'),
    ('Top 4', 'hipster', 'Artmage'),
    ('Top 4', 'Teremiare', 'Rikka'),
    ('Top 8', 'Adnane', 'Artmage'),
    ('Top 8', 'Fictinium', 'Rikka'),
    ('Top 8', 'UfeelRage 命希', 'Rikka'),
]
for i, cont in enumerate(cc):
    place, player, arch = cc_meta[i]
    main = [[n, nm] for n, nm in cont['main']]
    extra = [[n, nm] for n, nm in cont['extra']]
    side = [[n, nm] for n, nm in cont.get('side') or []]
    ur_c, sr_c = rar_count([(a, b) for a, b in main + extra + side])
    decks.append({
        'src': 'CC', 'event': 'Master Duel Challenger Cup EU 2026-11-15', 'eventShort': 'Challenger Cup',
        'eventDate': '2026-11-15', 'placement': place, 'player': player, 'archetype': arch,
        'engines': [], 'ur': ur_c * 30, 'sr': sr_c * 15, 'urCount': ur_c, 'srCount': sr_c,
        'main': main, 'extra': extra, 'side': side,
        'url': 'https://www.masterduelmeta.com/tournaments/challenger-cup/november-2026/15/report/',
        'source': 'MDM Challenger Cup report deck component',
    })

# normalise urCount for MW decks (urPrice is dust = copies*30)
for d in decks:
    if 'urCount' not in d:
        d['urCount'] = int(round((d['ur'] or 0) / 30))
        d['srCount'] = int(round((d['sr'] or 0) / 15))
    d['mainCount'] = sum(n for n, _ in d['main'])
    d['extraCount'] = sum(n for n, _ in d['extra'])

PLACE_ORDER = {'1st Place': 0, '2nd Place': 1, 'Top 4': 2, 'Top 8': 3, 'Top 16': 4}
deck_order = {'MW': 0, 'CC': 1}
decks.sort(key=lambda d: (deck_order[d['src']], PLACE_ORDER.get(d['placement'], 9), d['archetype']))

# ---------- archetype aggregation ----------
arch = {}
GENERIC = set(['Maxx "C"', 'Ash Blossom & Joyous Spring', 'Mulcharmy Fuwalos', 'Mulcharmy Purulia',
    'Droll & Lock Bird', 'Effect Veiler', 'Infinite Impermanence', 'Ghost Ogre & Snow Rabbit',
    'Ghost Belle & Haunted Mansion', 'Ghost Mourner & Moonlit Chill', 'Dimension Shifter', 'Called by the Grave',
    'Crossout Designator', 'Nibiru, the Primal Being', 'Triple Tactics Talent', 'Forbidden Droplet',
    'Lightning Storm', 'Raigeki', "Harpie's Feather Duster", 'Pot of Prosperity', 'Pot of Extravagance',
    'Pot of Desires', 'Super Polymerization', 'PSY-Frame Driver', 'PSY-Framegear Gamma',
    'S:P Little Knight', 'Baronne de Fleur', 'Lightning Crash'])
for d in decks:
    a = arch.setdefault(d['archetype'], {'en': d['archetype'], 'decks': [], 'mainSizes': [], 'ur': [], 'sr': []})
    a['decks'].append(d)
    a['mainSizes'].append(d['mainCount'])
    a['ur'].append(d['ur'] or 0)
    a['sr'].append(d['sr'] or 0)

for k, a in arch.items():
    # card inclusion: how many of this archetype's decks run the card
    cnt = Counter()
    for d in a['decks']:
        for n, nm in d['main'] + d['extra']:
            cnt[nm] += n
    core = [c for c in cnt.most_common(14) if c[0] not in GENERIC]
    a['topCards'] = [c for c, _ in core[:6]]
    a['best'] = a['decks'][0]['placement']
    a['sample'] = a['decks'][0]
    a['avgMain'] = round(sum(a['mainSizes']) / len(a['mainSizes']))

# ---------- tier list assembly ----------
TIERS_OUT = []
for (name, kind), t in tiers.items():
    if t['power'] is None:
        continue
    a = arch.get(name)
    item = {
        'en': name, 'ko': ((ko_theme(name) + ' 엔진') if kind == 'engine' and ko_theme(name) else ko_theme(name)), 'kind': kind, 'power': t['power'], 'pop': t['pop'],
        'band': band(t['power']), 'slug': 'https://www.masterduelmeta.com' + t['slug'],
        'decks': len(a['decks']) if a else 0,
        'topCards': a['topCards'] if a else [],
        'ur': a['ur'][0] if a else None, 'sr': a['sr'][0] if a else None,
        'avgMain': a['avgMain'] if a else (int(deckstats.get(name, {}).get('avgSize')) if deckstats.get(name, {}).get('avgSize') else None),
    }
    ds = deckstats.get(name) or {}
    if ds.get('avgUr'):
        item['avgUr'], item['avgSr'], item['avgSize'] = int(float(ds['avgUr'])), int(float(ds['avgSr'])), int(ds['avgSize'])
    TIERS_OUT.append(item)

order = {'T1': 0, 'T2': 1, 'T3': 2, 'RG': 3}
TIERS_OUT.sort(key=lambda x: (order[x['band']], -x['power']))

# ---------- tier list assembly ----------
NOTES = {
    'Elfnote': {
        'note': 'MW #256 우승 덱은 Elfnote Lucina·Regina 3장씩에 Prohibited Power Patron Portal - Terminus 3장, Fydraulis Harmonia 3장을 얹고 Accel Synchron 엔진을 더해 엑스트라 15장을 싱크로로 채운다.',
        'choke': '몬스터를 늘어놓아 필드를 만드는 축이라 「증식의 G」가 가장 무거운 견제. 초동 몬스터를 끊는 「하루 우라라」·「이펙트 뷀러」, 패에서 이어지는 「멀챠미 푸와로스」가 톱16 공통 카드다.',
    },
    'Dracotail': {
        'note': 'MW #256 톱8 덱은 42장. 드라코테일 본체에 Branded · Dogmatika · Fallen of the White Dragon · The Fallen & The Virtuous 엔진을 섞은 융합축이다.',
        'choke': '융합 소재와 묘지 자원을 굴리는 축 — 묘지를 닫는 「디멘션 시프터」, 융합 서치를 끊는 「하루 우라라」가 핵심. 표본 덱 자신도 우라라 3·푸와로스 3·드롤 2를 넣었다.',
    },
    'Elfnote Kewl Tune': {
        'note': 'MW #256 톱4 덱은 40장. 엘프노트에 쿨튠(Kewl Tune Reco·Mix·Rotary)과 Earthbound · Fydraulis를 섞은 혼합축이며, 11/5 금제로 쿨튠 Reco·Mix가 제한1이 됐다.',
        'choke': '엘프노트 축과 같은 이유로 「증식의 G」·「하루 우라라」가 기본값. 제한1이 된 쿨튠 카드를 1장씩만 쓰는 구성이라 서치 의존도가 높다.',
    },
    'Blitzclique': {
        'note': 'MW #256 톱8 덱은 40장. Whisker·Surge·Grain·Crackle Blitzclique를 3장씩 쓰는 본체에 Fydraulis Harmonia 3장, Hideout in the Sky, Coulomb 3장, Blitzclique - Breakaway 3장을 얹는다. 래더 인기 1위(12.87%).',
        'choke': '본체 몬스터를 3장씩 깔고 전개하는 구성 — 「증식의 G」와 「하루 우라라」가 기본. 표본 덱도 우라라 3, 푸와로스·푸룰리아를 채용했다.',
    },
    'Artmage': {
        'note': 'MW #256 준우승 덱은 40장. Artmage Power Patron·Finmel·Varnish 본체에 Power Patron 사이클(Medius·Junoldo·Vidolium·Nervedo)과 Forbidden Crown을 얹는다. 챌린저 컵 톱8에 3명이 들어갔다.',
        'choke': '융합(Super Polymerization·Garura 등)과 펜듈럼 자원을 함께 쓰는 구성. 「디멘션 시프터」·「하루 우라라」, 그리고 상대 융합을 막는 「봄의 징조」 계열이 유효하다는 평가가 많은 구간이다.',
    },
    'Rikka': {
        'note': 'MW #256 톱8 덱은 40장. Rikka Petal·Black Princess 3장, Rikka Konkon 3장, Cactus Bouncer 1장, Dominus Impulse 3장 구성. 챌린저 컵 톱8에 3명.',
        'choke': '식물족 전개에 Cactus Bouncer 같은 특수소환 제한 카드를 섞는 축 — 상대 턴에 쓰는 우라라·뷀러와 범용 제거기가 중요하다.',
    },
    'Invoked': {
        'note': 'MW #256 톱16에 2덱. Aleister the Invoker·Invocation·Magical Meltdown에 Aleister the Reminiscent·Aiwass·Invocation - "Sword"를 더한 새 융합축이다.',
        'choke': '「마법진 융합」처럼 서치 마법에 의존하는 구간이 있어 「하루 우라라」가 아프고, 묘지 융합이라 「디멘션 시프터」가 유효하다.',
    },
    'Yummy': {
        'note': 'MW #256 톱16 덱은 40장. Cooky·Lollipo 3장, Marshmao 2장, Dark Magical Curtain 3장, Dominus Spark 2장에 Magicians\' Souls·Illusion of Chaos를 섞는다.',
        'choke': '마법 카드로 전개를 잇는 축이라 마법 발동에 반응하는 견제가 유효. 표본 덱은 드롤 2·우라라 3·푸와로스 3에 크로스아웃까지 넣었다.',
    },
    'Darklord': {
        'note': 'MW #256 톱4 덱은 50장. Darklord Djehuty 3장·Banishment of the Darklords 3장에 Solfachord 엔진과 Forbidden Crown 3장을 얹은 50장 구성.',
        'choke': '50장이라 서치·드로우 의존도가 높아 「드롤 & 로크 버드」가 특히 아프다. 묘지·제외를 쓰므로 「디멘션 시프터」도 유효하다.',
    },
    'Branded': {
        'note': 'Branded Fusion을 축으로 하는 융합 테마. 11/5 금제에서 Branded Fusion이 제한1, The Fallen & The Virtuous가 제한2로 묶여 있다.',
        'choke': '「브랜디드 퓨전」 서치와 묘지 융합을 끊는 「하루 우라라」·「디멘션 시프터」가 기본 대응이다.',
    },
    'Sky Striker': {
        'note': 'MW #256 톱16 덱은 40장. Sky Striker Mobilize - Engage! 3장, Widow Anchor 3장, Linkage! 3장에 Pot of Sloth·Super Polymerization을 더했다. 11/5 금제로 Hornet Drones가 제한1.',
        'choke': '마법 카드 중심이라 「하루 우라라」·마법 발동 견제가 유효. 표본 덱은 드롤 대신 맥스 C·푸와로스로 상대 전개를 견제한다.',
    },
    'Dark Magician': {
        'note': 'MW #256 톱16에 2덱. Dragoon·Dark Magician of Destruction·DMG Shining Sarc·Dark Magical Curtain 엔진을 조합한다. 표본 중 하나는 46장.',
        'choke': '서치 마법과 묘지 자원을 함께 쓰는 구성 — 「하루 우라라」와 「디멘션 시프터」가 기본 대응이다.',
    },
    'Vanquish Soul K9': {
        'note': '랜더에서 K9 축과 Vanquish Soul을 섞은 구성. 11/5 금제로 Vanquish Soul Razen이 제한2가 됐다.',
        'choke': 'K9 몬스터 전개를 끊는 「하루 우라라」·「증식의 G」가 기본. Vanquish Soul 카드가 제한2라 서치 의존도가 높아졌다.',
    },
    'Snake-Eye Yummy': {
        'note': '야미에 스네이크아이 엔진을 섞은 축. 11/5 금제로 Snake-Eye Ash가 제한1이 됐다.',
        'choke': '「스네이크아이 애쉬」가 제한1이라 서치 루트가 좁아졌다 — 그 지점을 끊는 우라라가 유효하다.',
    },
    'Mitsurugi': {
        'note': '미츠루기 본체에 Mitsurugi Prayers 등 서치 카드를 쓰는 축. 11/5 금제로 Mitsurugi Prayers·Ame no Habakiri no Mitsurugi가 제한1·제한2.',
        'choke': '제한 카드가 많아 서치 루트가 얇다 — 「하루 우라라」로 서치를 끊으면 전개가 느려진다.',
    },
    'DoomZ': {
        'note': '플래닛 런 제출 덱과 특별전 M-Ace Duo Cup #1(커스텀 룰) 톱4에 등장. DoomZ Change·DoomZ Command "A.D.R.A.S.T.E.I.A."·DoomZ Break - Diactorus를 쓰는 축.',
        'choke': '전개형 축으로 「증식의 G」·「하루 우라라」가 기본 대응이다.',
    },
    'Witchcrafter': {
        'note': 'MDM 덱 통계 평균 41장의 마법사 축. 래더 점유 5.45%로 티어 3에 올라 있다.',
        'choke': '마법 카드를 묘지에서 되쓰는 축이라 「디멘션 시프터」·「하루 우라라」가 유효하다.',
    },
}

for t in TIERS_OUT:
    n = NOTES.get(t['en']) or {}
    if t['kind'] == 'engine':
        t['note'] = 'MDM은 엔진 단위로도 Power를 합산해 보여줍니다. 이 엔진을 쓰는 덱 타입의 점수를 묶은 값이라, 덱 타입 카드(아래 목록)와 따로 봐야 합니다.'
        t['choke'] = ''
    else:
        t['note'] = n.get('note', '')
        t['choke'] = n.get('choke', '')


def parse_block(block):
    out = []
    for line in block.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^(.*?)\s*\(([^)]*)\)$', line)
        name, rar = (m.group(1), m.group(2)) if m else (line, '')
        if rar == 'N/A':
            rar = rar_of(name) or ''
        out.append({'en': name, 'ko': ko_of(name), 'rarity': rar})
    return out

BAN = {'forbidden': parse_block(FORBIDDEN), 'limited1': parse_block(LIMITED1), 'limited2': parse_block(LIMITED2)}

# ---------- card index ----------
cards = {}
def add_card(name, extra=None):
    if not name:
        return
    if name not in cards:
        cards[name] = {'en': name, 'ko': ko_of(name), 'rarity': rar_of(name), 'in': []}
    if extra and extra not in cards[name]['in']:
        cards[name]['in'].append(extra)

for d in decks:
    tag = d['eventShort'] + ' ' + d['placement']
    for n, nm in d['main'] + d['extra'] + d['side']:
        add_card(nm, tag)
for grp in BAN.values():
    for c in grp:
        add_card(c['en'], '금제')

# staples worth searching even when no deck in the sample runs them (from MDM's official usage report)
STAPLES = ['Maxx "C"', 'Ash Blossom & Joyous Spring', 'Mulcharmy Fuwalos', 'Droll & Lock Bird',
           'Effect Veiler', 'Infinite Impermanence', 'Ghost Ogre & Snow Rabbit', 'Ghost Belle & Haunted Mansion',
           'Dimension Shifter', 'Called by the Grave', 'Crossout Designator', 'Nibiru, the Primal Being',
           'Triple Tactics Talent', 'Forbidden Droplet', 'S:P Little Knight', 'Baronne de Fleur',
           'Fydraulis Harmonia', 'Golden Cloud Beast - Malong', 'Dominus Purge', 'Dominus Spark',
           'Forbidden Crown', 'Pot of Sloth', 'Lightning Storm', 'Harpie\'s Feather Duster', 'Raigeki',
           'Super Polymerization', 'Terraforming', 'Foolish Burial', 'Monster Reborn', 'Upstart Goblin']
for s in STAPLES:
    add_card(s, '스테이플')

CARD_LIST = sorted(cards.values(), key=lambda c: c['en'].lower())

# ---------- handtrap usage across MW #256 top 16 ----------
HT = ['Maxx "C"', 'Ash Blossom & Joyous Spring', 'Mulcharmy Fuwalos', 'Droll & Lock Bird',
      'Effect Veiler', 'Infinite Impermanence', 'Ghost Ogre & Snow Rabbit', 'Ghost Belle & Haunted Mansion',
      'Dimension Shifter', 'Called by the Grave', 'Crossout Designator', 'Nibiru, the Primal Being',
      'Triple Tactics Talent', 'Forbidden Droplet', 'Super Polymerization']
HT_OUT = []
for h in HT:
    ds = [d for d in decks if d['src'] == 'MW' and any(nm == h for _, nm in d['main'] + d['extra'])]
    copies = sum(n for d in decks if d['src'] == 'MW' for n, nm in d['main'] if nm == h)
    if ds:
        HT_OUT.append({'en': h, 'ko': ko_of(h), 'decks': len(ds), 'of': 16, 'copies': copies, 'rarity': rar_of(h)})
HT_OUT.sort(key=lambda x: (-x['decks'], -x['copies']))

# ---------- Planet Run event distribution ----------
pr = load('planetrun.json')          # planet-run submissions kept from the recent-decks snapshot
pr_counter = Counter((d.get('deckType') or {}).get('name') for d in pr)
PR = [{'en': k, 'ko': ko_theme(k) or '', 'n': v} for k, v in pr_counter.most_common(12) if k]
PR_TOTAL = len(pr)

# ---------- articles (Korean summaries written from the fetched MDM posts) ----------
ARTICLES = [
    {
        'date': '2026-11-17', 'kind': '대회', 'event': 'Challenger Cup EU (2026-11-15)',
        'title': '챌린저 컵 EU — 아트메이지 3명 톱8, 리카 3명',
        'summary': [
            '코나미 후원 유럽 오픈, 256명 캡 · 대회 당일 마스터듀얼 표준 금제 사용 (MDM 리포트).',
            '우승 Railgun_toki(아트메이지), 준우승 Nei(드라코테일).',
            '톱4: hipster(아트메이지) · Teremiare(리카). 톱8: Adnane(아트메이지) · Fictinium·UfeelRage 命希(리카) · Jonas(드라코테일).',
            '톱8 중 아트메이지 3 / 리카 3 / 드라코테일 2 — 상위권이 이 세 테마로 갈렸다.',
        ],
        'url': 'https://www.masterduelmeta.com/tournaments/challenger-cup/november-2026/15/report/',
    },
    {
        'date': '2026-11-16', 'kind': '대회', 'event': 'Dkayed Meta Weekly #256',
        'title': '메타 위클리 #256 — 엘프노트 우승, 아트메이지 준우승',
        'summary': [
            '104명 참가 · 단일 토너먼트(1덱 BO3) · 1위 상금 $50 (MDM 리포트).',
            '우승 moussa(엘프노트) · 준우승 Milito-22(아트메이지).',
            '톱4: TheDarkLord(다크로드) · Ne0 Hawkeye(엘프노트 쿨튠).',
            '톱8: Anderson Strife(블리츠클리크) · Yuno(리카) · Katharsis(블루아이즈) · Wys(드라코테일).',
            '톱16에 스카이 스트라이커·인보크드·야미·슈퍼퀀트·로켓·블랙 매지션 2덱이 이름을 올렸다.',
        ],
        'url': 'https://www.masterduelmeta.com/articles/tournaments/dmc-md-meta-weekly-tournament/256/report/',
    },
    {
        'date': '2026-11-16', 'kind': '이벤트', 'event': 'Planet Run',
        'title': '플래닛 런 상위 덱 모음 공개',
        'summary': [
            'MDM이 2026년 11월 플래닛 런 이벤트 제출 덱을 모아 공개했다.',
            '이 페이지에는 최근 제출 덱 %d개를 아키타입별로 세어 상위 12개만 요약했다.' % PR_TOTAL,
            '이벤트 덱은 래더·토너먼트 통계에 반영되지 않는다(MDM 표기 statsWeight 0) — 티어표 수치와 별개로 봐야 한다.',
        ],
        'url': 'https://www.masterduelmeta.com/events/november-2026/planet-run/',
    },
    {
        'date': '2026-11-06', 'kind': '금제', 'event': '금제 변경 (11/5 시행)',
        'title': '11월 5일 금제 — 금지 4장 · 제한1 5장',
        'summary': [
            '새로 금지(3→0): Spell Canceller · Dracotail Phryxul · Go! - D/D/D Divine Zero King Rage · Protector of the Sanctuary.',
            '제한1 강화: Kewl Tune Reco(2→1) · Kewl Tune Mix(2→1) · Elfnote Tinia(3→1) · Elfnote Power Patron(3→1).',
            '새로 제한1(0→1): Premature Burial.',
            'MDM 공지(10/26) 기준, 2026-11-05 시행. 현재 전체 리스트는 금제 탭 참고.',
        ],
        'url': 'https://www.masterduelmeta.com/news/october-26-2026/master-duel-forbidden-list-update/',
    },
    {
        'date': '2026-11-05', 'kind': '세트', 'event': 'Majestic Vortex',
        'title': '최신 팩 Majestic Vortex 발매 (11/5)',
        'summary': [
            'MDM 티어표 페이지 표기: 최신 릴리스는 2026-11-05 "Majestic Vortex".',
            '같은 날 셀렉션 팩/시크릿 팩 업데이트와 레거시 팩 갱신도 함께 공지됐다.',
        ],
        'url': 'https://www.masterduelmeta.com/sets/majestic-vortex/',
    },
    {
        'date': '2026-11-06', 'kind': '공식', 'event': '인게임 사용률 리포트',
        'title': '공식 카드 사용률/승률 리포트 갱신 — 맥스 "C"·하루 우라라 상승',
        'summary': [
            'MDM이 11/5자 공식 인게임 사용률 리포트 갱신을 정리했다.',
            '상승 표시: Maxx "C" · Ash Blossom & Joyous Spring · Mulcharmy Fuwalos · Effect Veiler · Infinite Impermanence · Baronne de Fleur · Fydraulis Harmonia.',
            '하락 표시: Droll & Lock Bird. 신규 표시: Elfnote Lucina/Regina/Fortuna 등 엘프노트 카드 다수.',
            'MDM은 이 리포트에서 승률을 숫자로 공개하지 않는다 — 이 페이지도 승률 수치를 만들지 않았다.',
        ],
        'url': 'https://www.masterduelmeta.com/news/november-05-2026/card-usage-update/',
    },
    {
        'date': '2026-11-17', 'kind': 'OCG', 'event': 'RV02',
        'title': 'OCG 소식 — RV02 오버프레임 아트 "Marincess Aqua Argonaut"',
        'summary': [
            'OCG 신규 수록 RV02에서 마린세스 아쿠아 아르고넛 오버프레임 아트가 공개됐다 (MDM 11/17).',
            '11/16에는 같은 RV02의 Crimson Nova the Dark Cubic Lord 오버프레임 아트가 공개됐다.',
            'OCG 소식은 마스터듀얼 적용 시점이 따로라 국내 마듀 환경과는 시차가 있다.',
        ],
        'url': 'https://www.masterduelmeta.com/news/nov-17-2026/RV02/',
    },
    {
        'date': '2026-11-11', 'kind': '가이드', 'event': 'Rikka Guide',
        'title': 'MDM 리카 가이드 공개 (11/11)',
        'summary': ['리카 테마 입문·강점/약점·전개 파트를 나눈 가이드. 챌린저 컵 톱8에 리카 3명이 들어간 시점과 맞물린다.'],
        'url': 'https://www.masterduelmeta.com/guides/rikka-yusodus/',
    },
    {
        'date': '2026-11-05', 'kind': '가이드', 'event': 'Blitzclique Guide',
        'title': 'MDM 블리츠클리크 가이드 공개 (11/5)',
        'summary': ['퓨어/브랜디드/라이질 세 가지 축의 덱리스트를 함께 제시한 가이드.'],
        'url': 'https://www.masterduelmeta.com/guides/blitzclique-younglank/',
    },
]

DATA = {
    'source': 'masterduelmeta.com',
    'banlistDate': '2026-11-05',
    'latestSet': {'name': 'Majestic Vortex', 'date': '2026-11-05'},
    'tierRule': {'T1': 'Power 12 이상', 'T2': 'Power 7~12', 'T3': 'Power 3~7', 'RG': 'Power 1~3'},
    'tiers': TIERS_OUT,
    'decks': decks,
    'ban': BAN,
    'cards': CARD_LIST,
    'handtraps': HT_OUT,
    'planetrun': {'total': PR_TOTAL, 'list': PR},
    'articles': ARTICLES,
}

with open(os.path.join(BASE, 'data.json'), 'w', encoding='utf-8') as f:
    json.dump(DATA, f, ensure_ascii=False)

print('tiers', len(TIERS_OUT), 'decks', len(decks), 'cards', len(CARD_LIST),
      'ban', {k: len(v) for k, v in BAN.items()}, 'handtraps', len(HT_OUT), 'pr', PR_TOTAL)
print('ko coverage decks:', sum(1 for c in CARD_LIST if c['ko']), '/', len(CARD_LIST))
