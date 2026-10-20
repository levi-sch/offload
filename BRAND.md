# Offload – huisstijl

Wie Offload is, hoe het eruitziet en hoe het praat. De regels voor de interface van het dashboard staan in [DESIGN.md](DESIGN.md). Dit bestand gaat over het merk zelf.

## Kern

**Offload zet je opnames veilig over, en zegt pas dat het klaar is als het ook echt klaar is.**

Een fotograaf of videograaf komt terug van een shoot met een volle SD-kaart. Offload zet alles op de LaCie en daarna op de NAS, controleert elk bestand met een hash, en geeft één duidelijk antwoord: *mag deze kaart geformatteerd worden?*

Karakter: **betrouwbaar en rustig.** Offload is een kluis, geen gadget. Het werkt op de achtergrond, maakt geen ophef en is altijd eerlijk over wat er nog niet veilig staat.

| Offload is | Offload is niet |
|---|---|
| zeker | stoer |
| rustig | saai of afstandelijk |
| eerlijk, ook als iets misloopt | geruststellend als het niet klopt |
| kort en duidelijk | technisch om indruk te maken |

## Logo

Bestanden in [brand/](brand/):

| Bestand | Gebruik |
|---|---|
| `offload-logo.svg` | standaardlogo (beeldmerk + woordmerk) op een lichte achtergrond |
| `offload-logo-dark.svg` | hetzelfde op een donkere achtergrond |
| `offload-mark.svg` | alleen het beeldmerk: app-icoon, favicon, kleine plaatsen |
| `offload-wordmark.svg` | alleen het woordmerk, als het beeldmerk al ergens anders staat |
| `offload.ico` | Windows-icoon (16, 24, 32, 48 en 256 px), voor snelkoppelingen |

### Beeldmerk

Een SD-kaart met een vinkje. Het is het moment waar Offload om draait: de kaart is veilig en mag geformatteerd worden. Het schuine hoekje rechtsboven maakt het een kaart in plaats van een document; laat dat hoekje dus altijd staan.

### Woordmerk

`offload` in kleine letters, getekend met cirkels en rechte lijnen in één lijndikte. De twee f's delen één dwarsstreep. Het woordmerk is getekend, geen lettertype: typ het nooit na in een ander font.

In lopende tekst schrijf je de naam altijd als **Offload**, met een hoofdletter.

### Regels

- **Vrije ruimte:** houd rondom het logo minstens de breedte van de `o` vrij.
- **Minimale grootte:** het volledige logo minstens 96 px breed; daaronder gebruik je alleen het beeldmerk. Het beeldmerk werkt tot 16 px.
- **Kleur:** het beeldmerk is altijd Offload-blauw met een wit vinkje. Het woordmerk is Inkt op licht en Mist op donker.
- **Niet doen:** het logo uitrekken of draaien, het vinkje van kleur veranderen, het beeldmerk een andere statuskleur geven (groen, oranje of rood), schaduwen of verlopen toevoegen, of het logo op een drukke foto zetten.

## Kleur

Het merk heeft één kleur: Offload-blauw. Alle andere kleuren zijn neutraal of geven een status aan.

| Naam | Licht | Donker | Rol |
|---|---|---|---|
| **Offload-blauw** | `#2b6cf0` | `#5b8cff` | beeldmerk, knoppen, selectie, focus |
| Blauw zacht | `#e8effe` | `#182544` | achtergrond bij blauw, info |
| **Inkt** | `#16191d` | – | tekst en woordmerk op licht |
| **Mist** | – | `#e7e9ed` | tekst en woordmerk op donker |
| Grijs | `#667085` | `#98a1b0` | bijschriften |
| Papier | `#f5f6f8` | `#0e1013` | achtergrond |
| Vlak | `#fff` | `#171a1f` | panelen |

Groen, oranje en rood zijn **statuskleuren**, geen merkkleuren. Ze betekenen altijd *veilig*, *bezig of wacht* en *fout* (zie [DESIGN.md](DESIGN.md#statuskleuren)). Gebruik ze nooit voor decoratie of in het logo.

## Typografie

- **Interface en tekst:** het systeemlettertype (`system-ui`, op Windows *Segoe UI*). Offload werkt offline en laadt dus geen webfonts.
- **Logo:** altijd het getekende woordmerk uit `brand/`, nooit getypte tekst.
- **Cijfers:** tabulair (`font-variant-numeric: tabular-nums`), zodat aantallen en tijden mooi onder elkaar staan.
- Hoofdletters alleen aan het begin van een zin of in een naam. Kopjes in kleine hoofdletters (`SD-KAART`) zijn alleen voor sectietitels in het dashboard.

## Tone of voice

Offload praat zoals een collega die je bestanden voor je bewaart: kort, zeker en eerlijk. Altijd in het Nederlands (Vlaams) en met *je*.

### Principes

1. **Zeg wat er is, daarna wat je moet doen.** "8 bestanden staan al op de LaCie. Controleer ze eerst op inhoud."
2. **Veilig betekent ook echt veilig.** Zeg pas "mag geformatteerd worden" als alles op de LaCie én de NAS staat en de hash klopt. Twijfel je? Dan zeg je "nog niet".
3. **Geen paniek, geen jubel.** Geen uitroeptekens, geen emoji, geen "Oeps!" of "Top!". Een vinkje ✓ is genoeg.
4. **Gewone woorden.** "kopiëren", "controleren", "staat al op de LaCie". Technische termen alleen waar ze helpen ("hash", "NAS"), en dan zonder uitleg-jargon.
5. **Werkwoorden op knoppen.** Een knop zegt wat er gebeurt: "Kopieer selectie", "Controleer 8 bestaande bestanden". Nooit "OK", "Verzenden" of "Doorgaan".
6. **Fouten zonder schuld.** Zeg wat er misliep en wat de gebruiker kan doen. "Logboek kon niet bijgewerkt worden. Staat het open in Excel?"

### Woordenlijst

| Gebruik | Niet |
|---|---|
| kaart, SD-kaart | geheugenkaart, medium, volume |
| LaCie | externe schijf, back-up-disk |
| NAS | server, cloud |
| kopiëren | uploaden, synchroniseren, back-uppen |
| controleren | valideren, checken |
| overgezet | verwerkt, gesynct |
| formatteren | wissen, leegmaken |
| shoot | project, job |
| klant | account |

### Voorbeelden

| Situatie | Zo | Niet zo |
|---|---|---|
| alles veilig | ✓ Alles staat geverifieerd op de LaCie én de NAS. Deze kaart mag geformatteerd worden. | Gelukt! Je bestanden zijn gebackupt 🎉 |
| wacht op NAS | Alles staat op de LaCie. Wacht op de NAS (14/75). Nog niet formatteren. | Bijna klaar! |
| fout | Taak gestopt: hash klopt niet na kopiëren. Details in het logboek. | Er ging iets mis. Probeer het later opnieuw. |
| app weg | Offload-app reageert niet. Start start.cmd opnieuw. | Verbinding verloren :( |
| lege staat | Geen SD-kaart gevonden. Steek een kaart in; dit scherm opent dan vanzelf. | Nog niets te zien hier! |
