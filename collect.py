#!/usr/bin/env python3
"""
Europos turnyrų lankomumas (EuroLeague, EuroCup, BCL, FIBA Europe Cup).

Kas įskaičiuojama (kaip ACBattendance – tik „reguliarioji“ dalis):
  EuroLeague      – tik reguliarusis sezonas (phaseType RS)
  EuroCup         – tik reguliarusis sezonas (RS)
  BCL             – reguliarusis sezonas + Play-ins + Round of 16 / Top 16
                    (komanda, iškritusi po reguliariojo sezono, lieka su savo RS rungtynėmis)
  FIBA Europe Cup – reguliarusis sezonas + antrasis etapas (Second Round) – viskas iki atkrintamųjų
  Atrankos (Qualifiers / Qualifying Tournaments) ir atkrintamosios neįskaičiuojamos.

Šaltiniai:
  EuroLeague, EuroCup – api-live.euroleague.net (lankomumas „audience“, arenos talpa „venue.capacity“)
  BCL, FIBA Europe Cup – fiba.basketball / championsleague.basketball rungtynių sąrašai
                         (lankomumas „spectators“, talpa „venueCapacity“)

Klubų pavadinimai suvedami į pavadinimus iš Google Sheets lapų „Budgets 26/27“, „Budgets 25/26“,
„Historical Budgets“ (failas Basketball). Rankinės išimtys – data/aliases.csv. Nesuvesti – data/unresolved.json.
Talpa: turnyro oficiali; jei jos nėra – lapas „Arenas“ (pagal arenos pavadinimą ar „Also known as“).

Naudojimas:
  python collect.py --season 2026-27                 # einamasis sezonas -> data/2026-27/
  python collect.py --season 2025-26 --out seed      # senas sezonas (vieną kartą) -> seed/
"""
import argparse, csv, io, json, re, sys, time, unicodedata, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

SHEET_ID = "1Qt4ijFGDmvoLLHb-gCbcAF9KGts6ZC-RHwWzQw68cZI"
UA = {"User-Agent": "Mozilla/5.0 (EUattendance collector; +https://github.com/Smogikas/EUattendance)", "Accept": "*/*"}

FIBA_HIST1 = "https://www.fiba.basketball/en/history/112-fiba-mens-european-club-competitions-tier-1"
FIBA_HIST2 = "https://www.fiba.basketball/en/history/212-fiba-mens-european-club-competitions-tier-2"
COMPS = {
    "euroleague": {"name": "EuroLeague", "kind": "el", "code": "E", "rounds": {"RS"}},
    "eurocup": {"name": "EuroCup", "kind": "el", "code": "U", "rounds": {"RS"}},
    "bcl": {"name": "BCL", "kind": "fiba", "rounds": {"RS", "PLAY-INS", "PI", "R16", "T16", "TOP16"},
            "urls": {"2023-24": FIBA_HIST1 + "/208737/games", "2024-25": FIBA_HIST1 + "/208850/games",
                     "2025-26": FIBA_HIST1 + "/208962/games", "2026-27": "https://www.championsleague.basketball/en/games"}},
    "fec": {"name": "FIBA Europe Cup", "kind": "fiba", "rounds": {"RS", "SR"},
            "urls": {"2023-24": FIBA_HIST2 + "/208765/games",
                     "2024-25": "https://www.fiba.basketball/en/events/fiba-europe-cup-24-25/games",
                     "2025-26": "https://www.fiba.basketball/en/events/fiba-europe-cup-25-26/games",
                     "2026-27": "https://www.fiba.basketball/en/events/fiba-europe-cup-26-27/games"}},
}
FIELDS = ["comp", "season", "game_id", "date", "round", "home", "away", "attendance", "capacity", "cap_src",
          "venue", "home_src", "away_src", "url"]


def get(url, tries=4, as_json=False):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"; time.sleep(3 * (i + 1)); continue
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} {url}")
            return r.json() if as_json else r.text
        except (requests.RequestException, ValueError) as e:
            last = str(e); time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


# ---------------------------------------------------------------- EuroLeague / EuroCup
def el_slug(s):
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def fetch_el(comp, season):
    c = COMPS[comp]; y = season[:4]; sc = f"{c['code']}{y}"
    data = get(f"https://api-live.euroleague.net/v2/competitions/{c['code']}/seasons/{sc}/games", as_json=True)
    games = data.get("data", data) if isinstance(data, dict) else data
    site = "euroleague" if c["code"] == "E" else "eurocup"
    out = []
    for g in games:
        ph = ((g.get("phaseType") or {}).get("code") or "").upper()
        if ph not in c["rounds"] or not g.get("played"):
            continue
        h, a = g["local"]["club"], g["road"]["club"]
        v = g.get("venue") or {}
        aud = g.get("audience") or 0
        out.append({
            "game_id": f"{sc}_{g.get('gameCode')}", "date": (g.get("localDate") or g.get("date") or "")[:10],
            "round": f"{ph} {g.get('round') or ''}".strip(), "home_src": h.get("name", ""), "away_src": a.get("name", ""),
            "home_alt": [h.get("abbreviatedName") or "", h.get("editorialName") or ""],
            "away_alt": [a.get("abbreviatedName") or "", a.get("editorialName") or ""],
            "country": "", "attendance": int(aud) if aud and int(aud) >= MIN_ATT else "",
            "capacity": int(v["capacity"]) if v.get("capacity") else "", "venue": (v.get("name") or "").title(),
            "url": f"https://www.euroleaguebasketball.net/{site}/game-center/{season[:5]}{season[5:]}/"
                   f"{el_slug(h.get('name', ''))}-{el_slug(a.get('name', ''))}/{sc}/{g.get('gameCode')}/",
        })
    return out


# ---------------------------------------------------------------- BCL / FIBA Europe Cup
PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', re.S)


def fiba_games(html):
    """Ištraukia visus rungtynių objektus iš Next.js puslapio duomenų."""
    text = ""
    for m in PUSH.finditer(html):
        try:
            text += json.loads('"' + m.group(1) + '"')
        except Exception:
            pass
    if not text:
        text = html.replace('\\"', '"')
    dec = json.JSONDecoder(); seen = {}
    for m in re.finditer(r'\{"gameId":', text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except Exception:
            continue
        gid = obj.get("gameId")
        if gid and ("teamA" in obj) and gid not in seen:
            seen[gid] = obj
    return list(seen.values())


def fetch_fiba(comp, season):
    c = COMPS[comp]; url = c["urls"][season]
    games = fiba_games(get(url))
    if not games:
        raise RuntimeError(f"{url}: rungtynių sąrašas tuščias (pasikeitė puslapis?)")
    out = []
    base = url.rstrip("/")
    for g in games:
        rnd = g.get("round") or {}
        rc = (rnd.get("roundCode") or "").upper()
        if rc not in c["rounds"]:
            continue
        sa, sb = g.get("teamAScore"), g.get("teamBScore")
        played = (sa or 0) + (sb or 0) > 0 and not g.get("isLive")
        if not played or g.get("isPostponed"):
            continue
        A, B = g.get("teamA") or {}, g.get("teamB") or {}
        sp = g.get("spectators") or 0
        cap = g.get("venueCapacity") or 0
        if g.get("isPlayedBehindClosedDoors"):
            sp = 0
        out.append({
            "game_id": str(g.get("gameId")), "date": (g.get("gameDateTime") or "")[:10],
            "round": (rnd.get("roundName") or rc) + (f" {rnd.get('roundNumber')}" if rc == "RS" and rnd.get("roundNumber") else ""),
            "home_src": A.get("officialName") or A.get("shortName") or "", "away_src": B.get("officialName") or B.get("shortName") or "",
            "home_alt": [A.get("shortName") or ""], "away_alt": [B.get("shortName") or ""],
            "country": g.get("hostCountry") or "", "attendance": int(sp) if sp and int(sp) >= MIN_ATT else "",
            "capacity": int(cap) if cap and int(cap) > 0 else "", "venue": g.get("venueName") or "",
            "url": f"{base}/{g.get('gameId')}-{A.get('code', '')}-{B.get('code', '')}",
        })
    return out


# ---------------------------------------------------------------- Google Sheets
def sheet_csv(name, headers=0):
    url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&headers={headers}"
           f"&sheet={urllib.parse.quote(name)}")
    return list(csv.reader(io.StringIO(get(url))))


def budget_clubs():
    """[(season 'yy/yy', club, nation)] iš Budgets 26/27, 25/26 ir Historical Budgets."""
    out = []
    for sheet, default in (("Budgets 26/27", "26/27"), ("Budgets 25/26", "25/26"), ("Historical Budgets", None)):
        try:
            rows = sheet_csv(sheet)
        except Exception as e:
            print(f"! nepavyko nuskaityti {sheet}: {e}", file=sys.stderr); continue
        ci = ni = -1; title = ""; season = default
        for i, r in enumerate(rows):
            h = [x.strip() for x in r]
            if "Club" in h and any(x.endswith("Nation") for x in h):
                ci = h.index("Club"); ni = next(k for k, x in enumerate(h) if x.endswith("Nation"))
                # bloko pavadinimas – artimiausia ankstesnė netuščia eilutė
                for j in range(i - 1, max(-1, i - 4), -1):
                    t = " ".join(x for x in rows[j] if x.strip())
                    if t: title = t; break
                m = re.search(r"(\d\d)\s*/\s*(\d\d)\s*$", title or "")
                season = f"{m.group(1)}/{m.group(2)}" if m else default
                continue
            if ci < 0:
                continue
            club = (r[ci] if ci < len(r) else "").strip()
            if not club:
                if not any(x.strip() for x in r): ci = -1
                continue
            if re.match(r"^(Vidurkis|Average|Club)$", club, re.I):
                continue
            out.append((season, club, (r[ni] if ni < len(r) else "").strip()))
    return out


VGEN = set("""arena areena hall halle hala sala salle sports sport spor salonu ve etkinlik event events palais palau palacio
palazzetto palasport des de del della dello di da do dos la le el les los the and of center centre centar centrum sportski
sportova sportovni dvorana pabellon pavello pavilhao municipal municipale city indoor olympic olimpic olimpico olimpiskais
olympique complex dome stadium athletic athlitiko gymnasium hallen spelu basketball basket development club sh nova new
deportes esports desportos d omnisport omnisports spordihall sporto sporthal sportcsarnok sporturilor polivalenta
multifunctional multipurpose viceucelova main grand big small mala velika palace areena""".split())


def vtoks(s):
    s = unicodedata.normalize("NFD", str(s or "").translate(TR)).encode("ascii", "ignore").decode().lower()
    return {t for t in re.split(r"[^a-z0-9]+", s) if t and len(t) > 1 and t not in VGEN}


def _teq(x, y):
    n = min(len(x), len(y))
    return x == y or (n >= 5 and x[:max(5, n - 2)] == y[:max(5, n - 2)])


def _cover(a, b):
    return bool(a) and all(any(_teq(x, y) for y in b) for x in a)


class ArenaMatcher:
    """Arenos talpa tik iš lapo „Arenas“: tikslus pavadinimo ar „Also known as“ atitikmuo arba,
    jei jo nėra, panašus pavadinimas (tos pačios arenos klubas arba ≥2 sutampantys žodžiai)."""

    def __init__(self, sheet_rows):
        self.A = []
        if sheet_rows:
            h = [x.strip().lower() for x in sheet_rows[0]]
            def col(r, n):
                return r[h.index(n)].strip() if n in h and h.index(n) < len(r) else ""
            for r in sheet_rows[1:]:
                self._add(col(r, "arena"), col(r, "also known as"), col(r, "capacity"),
                          ";".join([col(r, "home clubs"), col(r, "main arena for"), col(r, "club")]))
        self.cache = {}

    def _add(self, arena, aka, cap, clubs):
        try:
            cap = int(float(re.sub(r"[^0-9.]", "", str(cap).replace(",", ""))))
        except Exception:
            return
        if not arena or cap <= 0:
            return
        names = [arena] + [x for x in re.split(r"[;/]", aka or "") if x.strip()]
        self.A.append({"arena": arena, "cap": cap, "keys": {nkey(n) for n in names if nkey(n)},
                       "toks": [vtoks(n) for n in names], "clubs": {nkey(c) for c in re.split(r"[;,]", clubs or "") if c.strip()}})

    def match(self, venue, club=""):
        """Grąžina (talpa, arenos pavadinimas lape, 'exact'|'similar') arba None."""
        key = (venue, club)
        if key in self.cache:
            return self.cache[key]
        vk, vt, ck = nkey(venue), vtoks(venue), nkey(club)
        res = None
        exact = [a for a in self.A if vk and vk in a["keys"]]
        if exact:                       # tas pats pavadinimas keliose eilutėse – pirmenybė arenai su šiuo klubu
            a = next((a for a in exact if ck and ck in a["clubs"]), exact[0])
            res = (a["cap"], a["arena"], "exact")
        if res is None:
            best = None
            for a in self.A:
                ov = 0
                for t in a["toks"]:
                    if t and vt and (_cover(vt, t) or _cover(t, vt)):
                        ov = max(ov, sum(1 for z in vt if any(_teq(z, y) for y in t)))
                if not ov:
                    continue
                same_club = bool(ck and ck in a["clubs"])
                if not same_club and ov < 2:
                    continue
                sc = ov + (3 if same_club else 0)
                if not best or sc > best[0]:
                    best = (sc, a)
            if best:
                res = (best[1]["cap"], best[1]["arena"], "similar")
        self.cache[key] = res
        return res


def arena_matcher():
    try:
        rows = sheet_csv("Arenas", headers=1)
    except Exception as e:
        print(f"! Arenas: {e}", file=sys.stderr); rows = []
    return ArenaMatcher(rows)


# ---------------------------------------------------------------- pavadinimų suvedimas
STOP = set("bc kk bk b c fc sc cb sk ks kb club basket basketball basketbol basquet baloncesto pallacanestro "
           "koszykowka koszykarski basketbal the de of and as sad sport sports team tc ok okk pbc bv bcm "
           "ab ac cf ss sl s a".split())
TR = str.maketrans({"ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "đ": "d", "Đ": "d", "ß": "ss", "ı": "i", "æ": "ae", "œ": "oe"})


CN = {"turkiye": "turkey", "czechia": "czechrepublic", "bosnia": "bosniaandherzegovina", "bih": "bosniaandherzegovina",
      "northmacedonia": "macedonia", "unitedkingdom": "greatbritain", "england": "greatbritain", "scotland": "greatbritain",
      "russianfederation": "russia", "holland": "netherlands"}


# šių šalių klubai „namų“ rungtynes dažnai žaidžia kitose šalyse
EXILE = {"israel", "ukraine", "russia", "belarus"}


def ckey(s):
    k = nkey(s)
    return CN.get(k, k)


def nkey(s):
    s = unicodedata.normalize("NFD", str(s or "").translate(TR)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def toks(s):
    s = unicodedata.normalize("NFD", str(s or "").translate(TR)).encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in STOP and len(t) > 1]


class Matcher:
    def __init__(self, clubs, aliases):
        self.clubs = clubs                      # [(season, club, nation)]
        self.names = sorted({c for _, c, _ in clubs})
        self.by_season = {}
        self.nation = {}
        for s, c, n in clubs:
            self.by_season.setdefault(s, set()).add(c)
            if n: self.nation.setdefault(c, n)
        self.alias = {nkey(k): v for k, v in aliases.items()}
        self.tok = {c: set(toks(c)) for c in self.names}
        df = {}
        for c, ts in self.tok.items():
            for t in ts: df[t] = df.get(t, 0) + 1
        import math
        self.idf = {t: math.log(1 + len(self.names) / d) for t, d in df.items()}
        self.cache = {}

    def w(self, ts):
        return sum(self.idf.get(t, 4.0) for t in ts)

    def match(self, names, season, country=""):
        """names – šaltinio pavadinimai (pirmas – pagrindinis). Grąžina lapo pavadinimą arba None."""
        key = (tuple(names), season, country)
        if key in self.cache: return self.cache[key]
        res = None
        for n in names:
            if n and nkey(n) in self.alias:
                res = self.alias[nkey(n)]; break
        if res is None:
            exact = {nkey(c): c for c in self.names}
            for n in names:
                if n and nkey(n) in exact:
                    res = exact[nkey(n)]; break
        if res is None:
            ss = f"{season[2:4]}/{season[5:7]}"
            best = []
            src = [set(toks(n)) for n in names if n and toks(n)]
            for c, ct in self.tok.items():
                if not ct: continue
                sc = 0.0
                for st in src:
                    inter = st & ct
                    if not inter: continue
                    cov_c = self.w(inter) / self.w(ct)          # kiek lapo pavadinimo „padengta“
                    cov_s = self.w(inter) / self.w(st)          # kiek šaltinio pavadinimo padengta
                    if ct <= st or st <= ct:
                        s1 = 2.0 + cov_c + cov_s
                    elif cov_c >= 0.6 and cov_s >= 0.34:
                        s1 = cov_c + cov_s
                    else:
                        continue
                    sc = max(sc, s1)
                if sc <= 0: continue
                if c in self.by_season.get(ss, ()): sc += 0.3
                if country and self.nation.get(c):
                    if ckey(self.nation[c]) == ckey(country):
                        sc += 0.5
                    elif ckey(self.nation[c]) not in EXILE:
                        continue                                # kitos šalies klubas – netinka
                best.append((sc, c))
            best.sort(reverse=True)
            if best and (len(best) == 1 or best[0][0] - best[1][0] >= 0.25):
                res = best[0][1]
        self.cache[key] = res
        return res


MIN_ATT = 15        # mažiau nei 15 žiūrovų – laikoma, kad lankomumas nepateiktas


TITLES = {"euroleague": "Euroleague", "eurocup": "Eurocup", "bcl": "Basketball Champions League", "fec": "FIBA Europe Cup"}
CN_EN = {"Türkiye": "Turkey", "Czechia": "Czech Republic", "England": "United Kingdom", "Great Britain": "United Kingdom"}


def season_tables(rows, season, out_dir, M, src_cn):
    """Sezono lentelės kaip lape „EuroAttendance“: Nation | Club | Average attendance | Available arena capacity |
    Filling rate. Rungtynės be lankomumo neįskaičiuojamos; talpa – lapas „Arenas“, svertinė kaip ACBattendance
    (efektyvi talpa = max(talpa, lankomumas))."""
    label = f"{season[2:4]}/{season[5:7]}"
    lines, js = [], {}
    for comp in COMPS:
        by = {}
        for r in rows:
            if r["comp"] != comp:
                continue
            c = by.setdefault(r["home"], {"src": r["home_src"], "att": [], "eff": [], "attc": [], "games": 0})
            c["games"] += 1
            a = int(r["attendance"]) if str(r["attendance"]).isdigit() else 0
            cap = int(r["capacity"]) if str(r["capacity"]).isdigit() else 0
            if a > 0:
                c["att"].append(a)
                if cap > 0:
                    c["eff"].append(max(cap, a)); c["attc"].append(a)
        tab = []
        for club, c in by.items():
            nation = M.nation.get(club) or src_cn.get(c["src"], "")
            nation = CN_EN.get(nation, nation)
            avg = round(sum(c["att"]) / len(c["att"])) if c["att"] else None
            wc = round(sum(c["eff"]) / len(c["eff"])) if c["eff"] else None
            fr = round(sum(c["attc"]) / sum(c["eff"]), 4) if c["eff"] else None
            tab.append({"nation": nation, "club": club, "average_attendance": avg, "weighted_capacity": wc,
                        "filling_rate": fr, "games_with_attendance": len(c["att"]), "home_games": c["games"],
                        "highest": max(c["att"]) if c["att"] else None, "lowest": min(c["att"]) if c["att"] else None})
        tab.sort(key=lambda t: -(t["average_attendance"] or -1))
        js[comp] = tab
        lines += [["", f"{TITLES[comp]} {label}"], ["", "Nation", "Club", "Average attendance", "Available arena capacity",
                                                     "Filling rate", "Games", "Highest attendance", "Lowest attendance"]]
        for t in tab:
            lines.append(["", t["nation"], t["club"], t["average_attendance"] or "", t["weighted_capacity"] or "",
                          f"{round(t['filling_rate'] * 100)}%" if t["filling_rate"] is not None else "",
                          t["games_with_attendance"], t["highest"] or "", t["lowest"] or ""])
        lines += [["", "", "END"], [], []]
    with (out_dir / "season_tables.csv").open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(lines)
    (out_dir / "season_tables.json").write_text(json.dumps({"season": season, "competitions": js}, ensure_ascii=False, indent=1),
                                                encoding="utf-8")


def venue_capacities(AM, cur_rows, out_root):
    """Visų sezonų arenų talpos iš lapo „Arenas“ (puslapis jas pritaiko ir pasibaigusiems sezonams)
    + sąrašas arenų, kurių lape nėra (naudojama turnyro talpa) – peržiūrai."""
    allrows = [dict(r) for r in cur_rows]      # pasibaigę sezonai – jau sezonų lentelės lape „EuroAttendance“
    V = {}
    for g in allrows:
        v = (g.get("venue") or "").strip()
        if not v:
            continue
        x = V.setdefault(v, {"venue": v, "clubs": {}, "comps": set(), "seasons": set(), "games": 0, "official": {}})
        x["clubs"][g.get("home", "")] = x["clubs"].get(g.get("home", ""), 0) + 1
        x["comps"].add(g.get("comp", "")); x["seasons"].add(g.get("season", "")); x["games"] += 1
        c = re.sub(r"[^0-9]", "", str(g.get("capacity") or ""))
        if c and g.get("cap_src") != "arenas":
            x["official"][c] = x["official"].get(c, 0) + 1
    caps, review, similar = {}, [], []
    for v, x in sorted(V.items()):
        club = max(x["clubs"], key=x["clubs"].get)
        m = AM.match(v, club)
        if m:
            caps[v] = {"capacity": m[0], "src": "arenas", "arena": m[1], "match": m[2]}
            if m[2] == "similar":
                similar.append({"venue": v, "arena": m[1], "capacity": m[0], "club": club, "games": x["games"]})
        else:
            review.append({"venue": v, "club": club, "other_clubs": sorted(c for c in x["clubs"] if c != club),
                           "comps": sorted(x["comps"]), "seasons": sorted(x["seasons"]), "games": x["games"],
                           "official": {k: n for k, n in sorted(x["official"].items(), key=lambda kv: -kv[1])}})
    review.sort(key=lambda r: -r["games"])
    (out_root / "venue_capacity.json").write_text(json.dumps(caps, ensure_ascii=False, indent=0), encoding="utf-8")
    similar.sort(key=lambda r: -r["games"])
    (out_root / "capacity_review.json").write_text(json.dumps({"missing": review, "similar_names": similar},
                                                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Arenų talpos: rasta {len(caps)} (panašus pavadinimas {len(similar)}), nėra lape {len(review)}")


# ---------------------------------------------------------------- pagrindinė dalis
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True, help="pvz. 2026-27")
    ap.add_argument("--out", default="data")
    ap.add_argument("--comps", default=",".join(COMPS))
    args = ap.parse_args()
    season = args.season
    out_dir = Path(args.out) / season
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    aliases = {}
    ap_path = Path("data/aliases.csv")
    if ap_path.exists():
        for r in csv.DictReader(ap_path.open(encoding="utf-8")):
            if r.get("source") and r.get("sheet"): aliases[r["source"].strip()] = r["sheet"].strip()
    clubs = budget_clubs()
    print(f"Klubų iš lapų: {len(clubs)}")
    M = Matcher(clubs, aliases)
    AM = arena_matcher()
    print(f"Arenų lape: {len(AM.A)}")
    if args.out != "data":                      # pagalbinis sąrašas tikrinimui
        (Path(args.out) / "sheet_clubs.json").write_text(json.dumps(sorted(set(clubs)), ensure_ascii=False, indent=0), encoding="utf-8")

    status_path = out_dir / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    games_path = out_dir / "games.csv"
    old_rows = []
    if games_path.exists():
        old_rows = list(csv.DictReader(games_path.open(encoding="utf-8")))
    rows, unresolved, nocap = [], {}, {}
    src_cn = {}                                  # turnyro pavadinimas -> šalis (FIBA namų rungtynės)
    for comp in args.comps.split(","):
        c = COMPS[comp]
        st = status.get(comp, {})
        try:
            raw = fetch_el(comp, season) if c["kind"] == "el" else fetch_fiba(comp, season)
            ok, err = True, ""
        except Exception as e:
            raw, ok, err = None, False, str(e)[:300]
            print(f"! {comp}: {err}", file=sys.stderr)
        if raw is None:                        # nepavyko – paliekami ankstesni duomenys
            rows += [r for r in old_rows if r["comp"] == comp]
        else:
            cnt = {}                           # komandos šalis – dažniausia jos namų rungtynių šalis
            for g in raw:
                if g["country"]:
                    d = cnt.setdefault(g["home_src"], {}); d[g["country"]] = d.get(g["country"], 0) + 1
            home_cn = {k: max(d, key=d.get) for k, d in cnt.items()}
            src_cn.update(home_cn)
            for g in raw:
                hcn, acn = home_cn.get(g["home_src"], ""), home_cn.get(g["away_src"], "")
                h = M.match([g["home_src"]] + g["home_alt"], season, hcn)
                a = M.match([g["away_src"]] + g["away_alt"], season, acn)
                for nm, ok_, cc in ((g["home_src"], h, hcn), (g["away_src"], a, acn)):
                    if not ok_:
                        unresolved.setdefault((comp, nm), {"comp": comp, "season": season, "source": nm, "country": cc})
                m = AM.match(g["venue"], h or g["home_src"]) if g["venue"] else None
                cap, csrc = (m[0], "arenas") if m else ("", "")   # talpa – tik iš lapo „Arenas“
                if not cap:
                    nocap.setdefault((comp, g["venue"]), {"comp": comp, "venue": g["venue"], "club": h or g["home_src"], "games": 0})
                    nocap[(comp, g["venue"])]["games"] += 1
                rows.append({"comp": comp, "season": season, "game_id": g["game_id"], "date": g["date"], "round": g["round"],
                             "home": h or g["home_src"], "away": a or g["away_src"], "attendance": g["attendance"],
                             "capacity": cap, "cap_src": csrc, "venue": g["venue"], "home_src": g["home_src"],
                             "away_src": g["away_src"], "url": g["url"]})
        n_att = sum(1 for r in rows if r["comp"] == comp and r["attendance"])
        prev_att = st.get("games_with_attendance", 0)
        st.update({"comp": comp, "name": c["name"], "ok": ok, "error": err, "run_at": now,
                   "games": sum(1 for r in rows if r["comp"] == comp), "games_with_attendance": n_att})
        if ok: st["last_ok"] = now
        if n_att > prev_att: st["last_new_attendance"] = now
        status[comp] = st
        time.sleep(1)

    rows.sort(key=lambda r: (r["comp"], r["date"], r["game_id"]))
    season_tables(rows, season, out_dir, M, src_cn)
    with games_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "unresolved.json").write_text(json.dumps(sorted(unresolved.values(), key=lambda x: (x["comp"], x["source"])),
                                                        ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "missing_capacity.json").write_text(json.dumps(sorted(nocap.values(), key=lambda x: (x["comp"], -x["games"])),
                                                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Rungtynių: {len(rows)}; nesuvesta pavadinimų: {len(unresolved)}; be talpos arenų: {len(nocap)}")
    if args.out == "data":
        venue_capacities(AM, rows, Path(args.out))
    return 0 if all(s.get("ok") for s in status.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
