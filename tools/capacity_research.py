"""Vienkartinis įrankis: kiekvienai arenai su oficialia talpa suranda krepšinio talpą Vikipedijoje
ir palygina su lapo „Arenas“ talpa. Rezultatas – tools/capacity_research.csv."""
import csv, io, json, re, sys, time, urllib.parse
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collect  # noqa: E402

S = requests.Session()
S.headers["User-Agent"] = "EUattendance capacity research (github.com/Smogikas/EUattendance)"


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


def wiki(lang, params):
    params = dict(params, format="json", origin="*")
    for i in range(3):
        try:
            r = S.get(f"https://{lang}.wikipedia.org/w/api.php", params=params, timeout=30)
            if r.ok:
                return r.json()
        except Exception:
            pass
        time.sleep(2)
    return {}


def clean(v):
    v = re.sub(r"<ref[^>]*/>", "", v)
    v = re.sub(r"<ref.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"<br\s*/?>", "; ", v)
    v = re.sub(r"\{\{(?:nowrap|nobr|small)\|([^{}]*)\}\}", r"\1", v, flags=re.I)
    v = re.sub(r"\{\{(?:plainlist|unbulleted list|ubl)\s*\|", "", v, flags=re.I)
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


def lookup(venue, club):
    """Grąžina (title, lang, cap, kind, raw)."""
    tried = []
    for lang in ("en",):
        for q in (venue, f"{venue} {club} arena"):
            j = wiki(lang, {"action": "query", "list": "search", "srsearch": q, "srlimit": 3})
            for hit in (j.get("query", {}).get("search") or []):
                t = hit["title"]
                if t in tried:
                    continue
                tried.append(t)
                p = wiki(lang, {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                                "titles": t, "redirects": 1})
                pages = p.get("query", {}).get("pages", {})
                txt = ""
                for pg in pages.values():
                    try:
                        txt = pg["revisions"][0]["slots"]["main"]["*"]
                    except Exception:
                        pass
                head = txt[:20000]
                if not re.search(r"\{\{\s*Infobox\s*(venue|stadium|building|arena|sports venue)", head, re.I):
                    continue
                vals = [clean(m.group(2)) for m in FIELD.finditer(head)]
                vals = [v for v in vals if re.search(r"\d", v)]
                if not vals:
                    continue
                raw = " | ".join(vals)[:300]
                cap, kind = parse_cap(" ; ".join(vals))
                return t, lang, cap, kind, raw
            time.sleep(0.3)
    return "", "", 0, "", ""


def main():
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
        t, lang, cap, kind, raw = lookup(v["venue"], club)
        out.append({"venue": v["venue"], "club": club, "other_clubs": "; ".join(c for c in v["clubs"] if c != club),
                    "comps": ",".join(sorted(v["comps"])), "games": v["n"], "official": off,
                    "official_all": "; ".join(f"{k}×{n}" for k, n in sorted(v["caps"].items())),
                    "arenas_cap": a[0] if a else "", "arenas_name": a[1] if a else "", "arenas_match": how,
                    "wiki_title": t, "wiki_cap": cap or "", "wiki_kind": kind, "wiki_raw": raw})
        print(i, v["venue"], off, a, t, cap, kind, flush=True)
    with open("tools/capacity_research.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)


if __name__ == "__main__":
    main()
