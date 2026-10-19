# Design van het dashboard

Regels voor de look en het gedrag van het dashboard (`index.html`). Volg ze bij elke wijziging aan de interface, zodat alles één geheel blijft.

## Uitgangspunten

- **Eén vraag beantwoorden:** mag deze kaart geformatteerd worden? Elk scherm helpt daarbij. Wat daar niet bij helpt, laat je weg.
- **Status gaat voor alles.** Groen, oranje en rood betekenen overal hetzelfde (zie [Statuskleuren](#statuskleuren)). Een kleur zonder betekenis gebruik je niet.
- **Rustig en zakelijk.** Geen illustraties, geen animaties behalve de voortgangsbalk, geen schaduwen behalve bij de vaste kopieerbalk.
- **Nederlands (Vlaams), in gewone taal.** Schrijf "Kopieer selectie", niet "Submit". Zeg wat er gebeurt en wat de gebruiker moet doen.
- **Eén bestand, geen build.** Alles staat in `index.html`: CSS in `<style>`, JS in `<script>`. Geen frameworks, geen externe fonts of CDN's. Het dashboard moet ook zonder internet werken.

## Kleuren

Alle kleuren zijn CSS-variabelen op `:root`. Gebruik in componenten nooit een vaste hex-waarde, alleen deze tokens. Donkere modus volgt het systeem via `prefers-color-scheme` en definieert dezelfde tokens opnieuw.

| Token | Licht | Donker | Gebruik |
|---|---|---|---|
| `--bg` | `#f5f6f8` | `#0e1013` | paginaachtergrond, invulvelden, tegels |
| `--panel` | `#fff` | `#171a1f` | panelen, chips, actieve tab |
| `--text` | `#16191d` | `#e7e9ed` | gewone tekst |
| `--muted` | `#667085` | `#98a1b0` | bijschriften, labels, sectiekoppen |
| `--line` | `#e3e6eb` | `#282d35` | randen en scheidingslijnen |
| `--track` | `#e9ecf1` | `#252a32` | lege voortgangsbalk, placeholder-miniaturen |
| `--accent` / `--accent-bg` | `#2b6cf0` / `#e8effe` | `#5b8cff` / `#182544` | knoppen, selectie, focus, info-banner |
| `--ok` / `--ok-bg` | `#0f9d58` / `#e7f6ee` | `#3ddc84` / `#0f2a1c` | geslaagd, geverifieerd |
| `--wait` / `--wait-bg` | `#b26a00` / `#fff4e0` | `#f5b54a` / `#2e2210` | bezig, wachten, nog te controleren |
| `--bad` / `--bad-bg` | `#d92d20` / `#fdecea` | `#ff6b5e` / `#331512` | fout, niet bereikbaar |

Een statuskleur komt altijd als paar: tekst in `--ok`, achtergrond in `--ok-bg` (idem voor `wait` en `bad`).

### Statuskleuren

| Status | Klasse | Betekenis |
|---|---|---|
| groen | `.ok` | gekopieerd en hash klopt; kaart mag geformatteerd worden |
| oranje | `.wait` | bezig, wacht op de NAS, of staat al op de LaCie maar is nog niet gecontroleerd |
| rood | `.bad` | er is iets misgegaan of een schijf is niet bereikbaar |
| blauw | `.info` | uitleg of een volgende stap, geen status |

Groen toon je alleen als het echt veilig is. Bij twijfel kies je oranje.

## Typografie

- Lettertype: `system-ui, "Segoe UI", sans-serif`, basis `15px` met regelhoogte `1.45`.
- `h1`: 22px, alleen voor "Offload" in de kop.
- `h2`: sectiekop, 13px, hoofdletters, `letter-spacing: .06em`, kleur `--muted`.
- `h3.day`: dagkop boven de sessies, 15px.
- `.cardtitle`: naam van de SD-kaart, 18px, gewicht 650.
- Kleine tekst: 13px voor chips, tabellen en details; 12px voor labels en badges; 11px voor de miniatuurlabels.
- Gewichten: 400 voor gewone tekst, 600 voor knoppen, badges en paden, 650 voor titels.

## Ruimte en vorm

- Pagina: maximaal `1100px` breed, gecentreerd, `16px` zijmarge.
- Afrondingen: panelen `12px`, banners en suggesties `10px`, tegels `9px`, knoppen en invulvelden `8px`, badges `6px`, chips en balken volledig rond.
- Randen zijn altijd `1px solid var(--line)`. Een selectie krijgt een rand van `2px` in `--accent`.
- Tussenruimte in veelvouden van ongeveer 4px (4, 6, 8, 10, 12, 16, 20).

## Componenten

| Component | Klasse | Waarvoor |
|---|---|---|
| Paneel | `.panel` | elke blok-inhoud: kaart, taak, importlijst, logboek |
| Chip | `.chip` + `.dot` | verbindingsstatus in de kop (LaCie, NAS) |
| Banner | `.banner.ok/.wait/.bad/.info` | de belangrijkste melding van een kaart of taak; bevat eventueel één knop |
| Badge | `.badge.ok/.wait/.bad` | status per import, bv. `LaCie ✓ 12/12` |
| Knop | `button` | primaire actie, gevuld in `--accent` |
| Linkknop | `button.link` | secundaire actie zonder vulling, bv. "Bestanden tonen" |
| Tegel | `.tile` | één bestand met miniatuur, statuslabel (`.st`) en vinkje (`.ck`) |
| Strook | `.strip` | zes voorbeeldbeelden per sessie |
| Suggestie | `.suggest` + `.mini` | voorstel om ontbrekende bestanden aan een bestaande map toe te voegen |
| Kopieerbalk | `.assign` | vaste balk onderaan de kaart zodra er iets geselecteerd is |
| Voortgangsbalk | `.bar` | voortgang van de lopende taak |

Regels:

- **Eén primaire knop per blok.** Andere acties zijn linkknoppen.
- Een knop die nu niet kan, staat op `disabled` (halve dekking). Verberg hem niet.
- Een tegel die niet nieuw is, kun je niet selecteren: de miniatuur staat op 45% dekking en het statuslabel zegt waarom (`al op LaCie`, `LaCie ✓`, `LaCie + NAS ✓`).
- De kopieerbalk toont altijd vooraf de doelmap (`→ E:\00_Bronbestanden\…`), zodat je ziet waar alles terechtkomt.
- Lege toestanden krijgen een korte zin in `.empty` of `.muted` die zegt wat je moet doen ("Steek een kaart in…").

## Interactie

- Het dashboard ververst elke seconde via `/api/status`. Bouw een kaart maar één keer op en werk daarna alleen de status bij, zodat selectie en invulvelden blijven staan.
- Selecteren: klik op een tegel, shift+klik voor een reeks, of vink een hele sessie aan.
- Destructieve of massale acties vragen eerst bevestiging met `confirm()`.
- Reageert de app niet, dan verschijnt onderaan de rode banner `#offline`.

## Toegankelijkheid

- Elke knop en elk invulveld heeft een zichtbare focusrand: `outline: 2px solid var(--accent)`.
- Status nooit alleen met kleur: zet er ook een woord of `✓` bij.
- De actieve tab heeft `aria-current="page"`.
- Tekst op `--bg` en `--panel` moet in licht en donker goed leesbaar blijven. Test beide modi na een kleurwijziging.
- Het dashboard werkt vanaf 760px breed in kolommen; smaller valt de kopieerbalk terug op één kolom.
