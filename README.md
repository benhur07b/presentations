# BNHR Presentations

A repository of presentations I've given over the years, published at https://bnhr.xyz/presentations/.

`index.html` lists the presentations by year, newest first: add a card there for each new folder. `assets/` holds the index page's link-preview image (`share.png`) and its logo, icon and fonts, which are the BNHR 2026 brand files also used by the workshops index.

## In the learning factory

This repository is the factory's **decks**: one per training, beside the presentations given elsewhere. One of the repositories of BNHR's learning factory, beside the hub, [`learn-factory`](https://github.com/benhur07b/learn-factory) (private; its README's *The learning factory* has the model and every repository's role).

- **It holds:** each training's deck, in its own folder, and the index.
- **It reads:** nothing automatically yet: a deck's links to the Learn site and the quizzes are typed, and its QR codes come from the trainer. A command that starts a training's deck from its record in the hub is planned (the factory's work order WO-06).
- **It hands on:** each training's room kit copies its deck. Its addresses (`bnhr.xyz/presentations/<folder>/`) are in materials already given out, so a deck's folder keeps its name.

## Checking a deck's links

`uv run scripts/check_links.py` checks every link the presentations make, as a participant would follow it: each link, image, stylesheet and script (a file here, or an address on the web that opens); each QR code (it decodes, its address opens, and the address typed in its caption is the one it opens); and each link to a quiz on bnhr.xyz/quizzes (a delivery on the quizzes site runs that quiz and round, so its page doesn't say the quiz isn't open). Name deck folders to check only those (`uv run scripts/check_links.py 2026-11-09-qgis-for-sflma-mapping`, before a deck is shown); `--pdfs` checks the links inside the PDF decks too, and `--json PATH` writes every link with its finding. It changes nothing, and exits 1 when a link does not hold. A site that turns scripts away (403, a closed connection, a timeout) is listed as a note, to open by hand. Its packages are in the script itself and `scripts/check_links.py.lock`, so uv needs nothing else; drawing the QR codes needs the Cairo library (`libcairo2` on Debian or Ubuntu).

## License

The presentations are © 2022-2026 Ben Hur S. Pintor and licensed under the [Creative Commons Attribution-ShareAlike 4.0 International License](https://creativecommons.org/licenses/by-sa/4.0/) (`LICENSE.txt`).

The BNHR name and logos are not covered by that license: all rights reserved. Fonts, third-party images and other works used in the decks stay under their own licenses and are credited on the slides where they appear.

`REUSE.toml` names the owner and license of every file that is not under CC BY-SA 4.0, and `LICENSES/` holds the license texts. `uvx reuse lint` checks that every file has one. A deck that adds a third-party image adds an entry for it there.

## TODO
- add more presentations
- make searchable? filterable?
- improve grouping
