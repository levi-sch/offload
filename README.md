# Offload

Zet foto's en video's van een SD-kaart op de LaCie en daarna op de NAS. Elk bestand wordt gecontroleerd met een SHA-256-hash. Een dashboard in je browser toont in één oogopslag of een kaart veilig geformatteerd mag worden.

## Installeren (één keer)

1. Dubbelklik `installeer-autostart.cmd`. Offload start dan na elke login vanzelf op de achtergrond.
2. Pas zo nodig `config.json` aan: het NAS-pad, het volumelabel van de LaCie of de bestandstypes.

Handmatig starten of het dashboard openen kan altijd met `start.cmd`, of via http://127.0.0.1:8765.

## Gebruik

1. Steek de SD-kaart in. Het dashboard opent vanzelf.
2. Kies een klant (een bestaande map in `00_Bronbestanden`, of typ een nieuwe naam), een datum en een shootnaam.
3. Klik op **Kopieer**. De bestanden komen in `E:\00_Bronbestanden\<klant>\<datum>_<shoot>\`. De mappen van de kaart blijven daarin behouden.
4. Zodra `\\NAS-A-PRIMARY\Marketing` bereikbaar is, zet Offload alles vanzelf door naar dezelfde plek onder `nas_root`.
5. Groene melding **"Deze kaart mag geformatteerd worden"**? Dan staat elk foto- en videobestand van die kaart geverifieerd op de LaCie én op de NAS.

## Wat betekenen de kleuren?

| Badge | Betekenis |
|---|---|
| groen ✓ | alle bestanden zijn gekopieerd en de hash klopt |
| oranje | bezig, of wacht op de NAS |
| rood | er is iets misgegaan; klik op "probleem(en) bekijken" |

## Goed om te weten

- Offload wist en overschrijft nooit iets. Bestaat er al een ander bestand met dezelfde naam, dan wordt de kopie `naam_2.ext`.
- Steek je een kaart opnieuw in, dan herkent Offload de bestanden die al zijn overgezet (op naam en grootte). Alleen nieuwe bestanden worden gekopieerd.
- Per shootmap staat een `.offload.json` met de hash en de status van elk bestand.
- Alleen foto, video en audio wordt meegenomen (zie `extensions` in `config.json`). Sidecars zoals Sony `.XML` of `.THM` niet; voeg ze aan de lijst toe als je ze ook wilt.
- Fouten van de achtergrondprocessen staan in `offload.log`.
- Test: `python test_app.py`
