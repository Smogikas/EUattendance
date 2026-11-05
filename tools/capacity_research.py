"""Vienkartinis įrankis: kiekvienai arenai su oficialia talpa suranda krepšinio talpą Vikipedijoje
ir palygina su lapo „Arenas“ talpa. Rezultatas – tools/capacity_research.csv."""
import csv, io, json, re, sys, time, urllib.parse
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collect  # noqa: E402

S = requests.Session()
S.headers["User-Agent"] = "EUattendanceBot/1.0 (https://github.com/Smogikas/EUattendance; one-off arena capacity lookup) python-requests"


def games():
    rows = list(csv.DictReader(open("data/2026-27/games.csv", encoding="utf-8")))
    old = collect.sheet_csv("EuroAttendance", headers=1)
    h = [x.strip() for x in old[0]]
    rows += [dict(zip(h, r)) for r in old[1:]]
    return rows


def arenas_rows():
    rows = collect.sheet_csv("Arenas", headers=1)
    h = [x.strip().lower() for x in rows[0]]
    return [dict(zip(h, r)) for r in rows[1:]]


def num(x):
    x = re.sub(r"[^0-9]", "", str(x or ""))
    return int(x) if x else 0


def clean(v):
    v = re.sub(r"<ref[^>]*/>", "", v)
    v = re.sub(r"<ref.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"<br\s*/?>", "; ", v)
    v = re.sub(r"\{\{(?:nowrap|nobr|small)\|([^{}]*)\}\}", r"\1", v, flags=re.I)
    v = re.sub(r"\{\{(?:plainlist|unbulleted list|ubl|collapsible list|flatlist|hlist)\s*\|?", "", v, flags=re.I)
    v = re.sub(r"\|\s*title\s*=", "", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"'''?", "", v)
    v = re.sub(r"<[^>]+>", "", v)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = v.replace("}}", "").replace("\n*", ";").replace("\n", " ")
    return re.sub(r"\s+", " ", v).strip(" ;|")


FIELD = re.compile(r"\|\s*(capacity|seating_capacity|kapazität|capienza|aforo|capacité|capacidade|pojemność|kapacita|kapasite|"
                   r"kapacitet|χωρητικότητα|vietos|places)\s*=\s*(.*?)(?=\n\s*\|\s*[\w ]+\s*=|\n\}\})", re.S | re.I)
BASK = re.compile(r"(basketball|basket|baloncesto|pallacanestro|koszyk|kosárlabda|košarka|кошарка|баскетбол|basquete|krepšin|μπάσκετ)"
                  r"[^0-9;]{0,25}?(\d[\d.,\s ]{2,8}\d)", re.I)
BASK2 = re.compile(r"(\d[\d.,\s ]{2,8}\d)\s*[(\-–:]?\s*(?:for\s+)?(basketball|basket)", re.I)
SPORT = re.compile(r"(sport|sports|indoor|handball|volleyball|futsal|seated|seating|seats)[^0-9;]{0,25}?(\d[\d.,\s ]{2,8}\d)", re.I)


def parse_cap(txt):
    m = BASK2.search(txt)
    if m:
        return num(m.group(1)), "basketball"
    m = BASK.search(txt)
    if m:
        return num(m.group(2)), "basketball"
    m = SPORT.search(txt)
    if m:
        return num(m.group(2)), "sport"
    nums = [num(x) for x in re.findall(r"\d[\d.,]{2,8}\d|\d{3,6}", txt)]
    nums = [n for n in nums if 300 <= n <= 60000]
    if nums and not re.search(r"concert", txt, re.I):
        return nums[0], "capacity"
    if nums:
        return min(nums), "capacity(min, has concert)"
    return 0, ""



STATS = {"ok": 0, "err": 0}


def wiki(lang, params):
    params = dict(params, format="json", maxlag=5)
    for i in range(6):
        try:
            r = S.get(f"https://{lang}.wikipedia.org/w/api.php", params=params, timeout=30)
            if r.ok and "error" not in r.text[:200]:
                STATS["ok"] += 1
                return r.json()
            print(f"  ! {lang} {r.status_code} {r.text[:120]!r}", flush=True)
        except Exception as e:
            print(f"  ! {lang} {e}", flush=True)
        STATS["err"] += 1
        time.sleep(3 * (i + 1))
    return {}


def page_text(lang, title):
    p = wiki(lang, {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                    "titles": title, "redirects": 1})
    for pg in p.get("query", {}).get("pages", {}).values():
        try:
            return pg.get("title", title), pg["revisions"][0]["slots"]["main"]["*"]
        except Exception:
            pass
    return title, ""


def infobox(txt):
    """Grąžina (tipas, {param: reikšmė}) pirmam Infobox šablonui."""
    m = re.search(r"\{\{\s*(Infobox|Info/|Infobox_|Infocaseta|Сп|Карточка)[^|}]*", txt, re.I)
    if not m:
        return "", {}
    i, depth, buf, parts = m.start(), 0, "", []
    while i < len(txt):
        two = txt[i:i + 2]
        if two in ("{{", "[["):
            depth += 1; buf += two; i += 2; continue
        if two in ("}}", "]]"):
            depth -= 1
            if depth == 0:
                parts.append(buf); break
            buf += two; i += 2; continue
        if txt[i] == "|" and depth == 1:
            parts.append(buf); buf = ""; i += 1; continue
        buf += txt[i]; i += 1
    kind = parts[0].strip("{ \n") if parts else ""
    d = {}
    for x in parts[1:]:
        if "=" in x:
            k, v = x.split("=", 1)
            d[k.strip().lower()] = v.strip()
    return kind, d


CAPKEYS = ("capacity", "seating_capacity", "kapazität", "capienza", "aforo", "capacité", "capacidade", "pojemność",
           "kapacita", "kapasite", "kapacitet", "kapacitás", "χωρητικότητα", "talpa", "capacitate", "вместимость")
NAMEKEYS = ("name", "nickname", "former_names", "former names", "fullname", "full_name", "other_names", "names")
GENERIC = set("arena hall halle sports sport spor salonu salle palais des de del della dello di la le el sala hala dvorana "
              "pabellon pavello pavilhao palacio palau palasport palazzetto center centre centrum indoor municipal city "
              "the and areena spordihall sporto sportovni sportova sporthal event events complex dome stadium olympic "
              "athletic gymnasium hallen spelu basketball basket development club sh nova new".split())


def dtoks(s):
    return set(collect.toks(s)) - GENERIC


def overlap(a, b):
    for x in a:
        for y in b:
            n = min(len(x), len(y))
            if x == y or (n >= 4 and x[:max(4, n - 2)] == y[:max(4, n - 2)]):
                return True
    return False


def lookup(venue, club, langs):
    """Grąžina dict: wiki_title, wiki_lang, wiki_cap, wiki_kind, wiki_raw."""
    vt = dtoks(venue)
    for lang in langs:
        for q in (venue, f"{venue} {club}"):
            j = wiki(lang, {"action": "query", "list": "search", "srsearch": q, "srlimit": 4})
            for hit in (j.get("query", {}).get("search") or []):
                t, txt = page_text(lang, hit["title"])
                kind, d = infobox(txt)
                if not d or not re.search(r"venue|stadium|building|arena|sport|hall|dvorana|spielstätte|impianto", kind, re.I):
                    continue
                names = " ".join([t] + [clean(d.get(k, "")) for k in NAMEKEYS])
                if vt and not overlap(vt, dtoks(names)):
                    continue
                vals = [clean(d[k]) for k in d if k in CAPKEYS or k.startswith("capacity")]
                vals = [v for v in vals if re.search(r"\d", v)]
                if not vals:
                    continue
                cap, ck = parse_cap(" ; ".join(vals))
                return {"wiki_title": t, "wiki_lang": lang, "wiki_cap": cap or "", "wiki_kind": ck, "wiki_raw": " | ".join(vals)[:300]}
            time.sleep(0.2)
    return {"wiki_title": "", "wiki_lang": "", "wiki_cap": "", "wiki_kind": "", "wiki_raw": ""}


CLUBCACHE = {}


def club_info(club, lang="en"):
    """Klubo infobox: arena ir talpa (dažniausiai krepšinio)."""
    if club in CLUBCACHE:
        return CLUBCACHE[club]
    res = {"club_page": "", "club_arena": "", "club_cap": ""}
    j = wiki(lang, {"action": "query", "list": "search", "srsearch": f"{club} basketball club", "srlimit": 3})
    for hit in (j.get("query", {}).get("search") or []):
        t, txt = page_text(lang, hit["title"])
        kind, d = infobox(txt)
        if "basketball" not in kind.lower():
            continue
        res = {"club_page": t, "club_arena": clean(d.get("arena", ""))[:120], "club_cap": clean(d.get("capacity", ""))[:120]}
        break
    CLUBCACHE[club] = res
    return res


LANG = {"spain": "es", "italy": "it", "germany": "de", "france": "fr", "greece": "el", "turkey": "tr", "turkiye": "tr",
        "poland": "pl", "serbia": "sr", "hungary": "hu", "czechrepublic": "cs", "czechia": "cs", "lithuania": "lt",
        "latvia": "lv", "estonia": "et", "romania": "ro", "bulgaria": "bg", "israel": "he", "portugal": "pt",
        "belgium": "nl", "netherlands": "nl", "finland": "fi", "sweden": "sv", "denmark": "da", "slovakia": "sk",
        "slovenia": "sl", "croatia": "hr", "montenegro": "sr", "bosniaandherzegovina": "bs", "northmacedonia": "mk",
        "georgia": "ka", "azerbaijan": "az", "cyprus": "el", "kosovo": "sq", "switzerland": "de", "austria": "de",
        "monaco": "fr", "unitedarabemirates": "ar", "greatbritain": "en", "england": "en", "scotland": "en"}


NATION = {}


def main():
    for _s, c, n in collect.budget_clubs():
        if n:
            NATION.setdefault(c, n)
    G = games()
    ar = arenas_rows()
    byV, byC = {}, {}
    for a in ar:
        cap = num(a.get("capacity"))
        if not cap:
            continue
        for n in [a.get("arena", "")] + str(a.get("also known as", "")).split(";"):
            k = collect.nkey(n)
            if k and k not in byV:
                byV[k] = (cap, a.get("arena", ""))
        ck = collect.nkey(a.get("club", ""))
        if ck:
            byC.setdefault(ck, []).append((cap, a.get("arena", "")))
    V = {}
    for g in G:
        if g.get("cap_src") != "official":
            continue
        v = V.setdefault(g["venue"], {"venue": g["venue"], "clubs": {}, "comps": set(), "caps": {}, "n": 0})
        v["clubs"][g["home"]] = v["clubs"].get(g["home"], 0) + 1
        v["comps"].add(g["comp"])
        c = num(g["capacity"])
        v["caps"][c] = v["caps"].get(c, 0) + 1
        v["n"] += 1
    out = []
    for i, v in enumerate(sorted(V.values(), key=lambda x: -x["n"])):
        club = max(v["clubs"], key=v["clubs"].get)
        off = max(v["caps"], key=v["caps"].get)
        a = byV.get(collect.nkey(v["venue"]))
        how = "venue" if a else ""
        if not a:
            cs = byC.get(collect.nkey(club)) or []
            if len(cs) == 1:
                a, how = cs[0], "club"
        nat = collect.nkey(NATION.get(club, ""))
        langs = ["en"] + ([LANG[nat]] if LANG.get(nat, "en") != "en" else [])
        L = lookup(v["venue"], club, langs)
        C = club_info(club)
        out.append({"venue": v["venue"], "club": club, "other_clubs": "; ".join(c for c in v["clubs"] if c != club),
                    "comps": ",".join(sorted(v["comps"])), "games": v["n"], "official": off,
                    "official_all": "; ".join(f"{k}×{n}" for k, n in sorted(v["caps"].items())),
                    "arenas_cap": a[0] if a else "", "arenas_name": a[1] if a else "", "arenas_match": how,
                    **L, **C})
        print(i, v["venue"], off, a, L["wiki_title"], L["wiki_cap"], L["wiki_kind"], C["club_cap"], flush=True)
    print("requests", STATS, flush=True)
    with open("tools/capacity_research.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)


if __name__ == "__main__":
    main()
