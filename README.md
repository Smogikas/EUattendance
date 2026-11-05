# EUattendance – Europos turnyrų lankomumas

Puslapis: https://smogikas.github.io/EUattendance/

Namų rungtynių lankomumas: **EuroLeague** ir **EuroCup** (tik reguliarusis sezonas), **BCL** (reguliarusis sezonas + Play-ins + Top 16),
**FIBA Europe Cup** (reguliarusis sezonas + antrasis etapas). Atrankos ir atkrintamosios neįskaičiuojamos.
Klubų pavadinimai – kaip Google Sheets lapuose „Budgets“ (failas Basketball).

- **Einamasis sezonas (26/27)** – `collect.py` per GitHub Actions kas 6 val. (`.github/workflows/update.yml`) → `data/2026-27/`.
- **Pasibaigę sezonai (23/24–25/26)** – Google Sheets lape **EuroAttendance**: po vieną sezono lentelę kiekvienam turnyrui
  (Nation | Club | Average attendance | Available arena capacity | Filling rate), puslapis jas skaito iš ten.
- **Flashscore papildymai** – `data/2026-27/flashscore_attendance.csv`: lankomumas iš Flashscore rungtynėms, kurių oficialiai nepaskelbė. `collect.py` jį pritaiko tik kai oficialaus skaičiaus nėra (oficialus visada svarbesnis).
- **Einamojo sezono lentelės** – `data/2026-27/season_tables.csv` (tokiu pat formatu – sezonui pasibaigus įklijuojama į EuroAttendance).
- **Skaičiavimas (kaip ACBattendance)** – rungtynės be lankomumo neįskaičiuojamos; talpa iš lapo „Arenas“; svertinė talpa =
  efektyvių talpų vidurkis (efektyvi talpa = max(talpa, lankomumas)); užpildymas = lankomumo suma / efektyvių talpų suma.
- **Pavadinimų išimtys** – `data/aliases.csv` (`source` – turnyro pavadinimas, `sheet` – pavadinimas lape).
  Nesuvesti pavadinimai rodomi puslapyje geltona eilute ir `data/2026-27/unresolved.json`.
- **Talpa** – turnyro oficiali; jei jos nėra – lapas „Arenas“ (stulpeliai Arena, Capacity, Also known as).

Sezonui pasibaigus: `data/2026-27/season_tables.csv` lenteles įklijuoti į lapą „EuroAttendance“, `collect.py` ir
`index.html` pakeisti einamąjį sezoną (CURRENT / SEASON), papildyti BCL ir FIBA Europe Cup puslapių adresus.
