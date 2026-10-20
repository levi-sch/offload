# Offload

Zet foto's en video's van een SD-kaart op de LaCie en daarna op de NAS. Elk bestand wordt gecontroleerd met een SHA-256-hash. Een dashboard in je browser toont in één oogopslag of een kaart veilig geformatteerd mag worden.

## Installeren (één keer)

1. Dubbelklik `installeer-autostart.cmd`. Offload start dan na elke login vanzelf op de achtergrond.
2. Pas zo nodig `config.json` aan: het NAS-pad, het volumelabel van de LaCie, de bestandstypes, de pauze tussen sessies (`session_gap_minutes`) of de plek van het logboek.

Handmatig starten of het dashboard openen kan altijd met `start.cmd`, of via http://127.0.0.1:8765.

## Gebruik

1. Steek de SD-kaart in. Het dashboard opent vanzelf.
2. Offload doorzoekt de hele LaCie op bestanden die er al staan, ook in mappen die je met de hand hebt gekopieerd.
3. **Bestanden die al op de LaCie staan** worden niet opnieuw gekopieerd. Klik op **Controleer bestaande bestanden**: Offload vergelijkt dan de hash van de kaart met die op de LaCie. Is de inhoud gelijk, dan wordt het bestand opgenomen en gaat het ook naar de NAS. Is de inhoud anders, dan wordt het een gewoon nieuw bestand.
4. **Ontbrekende bestanden:** is een nieuw bestand opgenomen tussen bestanden die al samen in één map staan (en staat het grootste deel van die sessie daar), dan stelt Offload voor om het aan die map toe te voegen. Je ziet de miniaturen; klik er een aan om het over te slaan, en klik op **Voeg toe aan deze map**.
5. **Nieuwe bestanden** staan per opnamedag in sessies. Een nieuwe sessie begint na meer dan 30 minuten zonder opnames. Vink een sessie aan, of klik op losse bestanden; met shift+klik selecteer je een hele reeks. Kies een klant, een datum en een shootnaam en klik op **Kopieer selectie**. Herhaal dit voor de volgende klant.
6. De bestanden komen plat in `E:\00_Bronbestanden\<klant>\JJ-MM-DD_<shoot>\`, bv. `01_VMRE\26-09-11_teambuilding\`, zonder de camera-mappen zoals `DCIM\100MSDCF`. Een klant mag een tussenniveau hebben (`02_Cleanpoint\01_Eke`), en met **Submap** kun je bv. `Drone` of `Camera` kiezen. Het dashboard toont vooraf de doelmap. Liever zelf een map aanwijzen? Klik op **Kies map…**: dan opent het gewone Windows-venster, zoals bij Opslaan als, waarin je ook een **Nieuwe map** kunt maken. Alleen mappen binnen `00_Bronbestanden` op de LaCie worden aanvaard.
7. Zodra `\\NAS-A-PRIMARY\Marketing` bereikbaar is, zet Offload alles vanzelf door naar dezelfde plek onder `nas_root`.
8. Groene melding **"Deze kaart mag geformatteerd worden"**? Dan staat elk foto- en videobestand van die kaart geverifieerd op de LaCie én op de NAS.

## Veilig verwijderen

- **Van de SD-kaart:** alleen bestanden die geverifieerd op de LaCie én de NAS staan (groen). Offload kijkt vlak voor het wissen nog na dat beide kopieën bestaan met de juiste grootte. Een SD-kaart heeft geen Prullenbak, dus wissen is daar definitief; de kopieën op LaCie en NAS zijn je reservekopie. Sony-camera's vragen na het wissen van clips soms om hun database te herstellen.
- **Dubbels op de LaCie:** klik op **Zoek dubbels**. Offload hasht bestanden met dezelfde naam en grootte in verschillende mappen en toont welke mappen identieke bestanden delen. Kies per paar mappen **Verwijder uit …**: die kopieën gaan naar de Windows-Prullenbak, hun NAS-kopie (als Offload die zette) naar `#recycle` op de NAS. De identieke kopie in de andere map blijft en gaat, indien nodig, opnieuw naar de NAS.
- Je krijgt altijd eerst een lijst te zien van wat er weg gaat, en elke verwijdering staat in het logboek.

## Logboek

Elke actie (kaart ingestoken, gekopieerd, al aanwezig, andere inhoud, NAS gekopieerd, fout) komt als een regel in `E:\Overzetting controle\Offload-logboek.csv`. Dat bestand opent in Excel. In het dashboard kun je het logboek doorzoeken via het tabblad **Logboek**.

Staat het logboek open in Excel, dan bewaart Offload de nieuwe regels en schrijft ze weg zodra het bestand weer vrij is.

## Wat betekenen de kleuren?

| Badge | Betekenis |
|---|---|
| groen ✓ | alle bestanden zijn gekopieerd en de hash klopt |
| oranje | bezig, wacht op de NAS, of staat al op de LaCie maar is nog niet gecontroleerd |
| rood | er is iets misgegaan; klik op "probleem(en) bekijken" of kijk in het logboek |

Kleuren, typografie, componenten en de andere ontwerpregels van het dashboard staan in [DESIGN.md](DESIGN.md). Lees dat bestand voor je iets aan `index.html` verandert.

## Goed om te weten

- Offload wist en overschrijft nooit iets. Bestaat er al een ander bestand met dezelfde naam, dan wordt de kopie `naam_2.ext`.
- Per shootmap staat een `.offload.json` met de hash en de status van elk bestand.
- Alleen foto, video en audio worden meegenomen (zie `extensions` in `config.json`). Sidecars zoals Sony `.XML` worden niet gekopieerd. De Sony-miniaturen (`THMBNL`) worden alleen gebruikt als voorbeeldbeeld in het dashboard.
- Technische fouten van de achtergrondprocessen staan in `offload.log`.
- Test: `python test_app.py`
