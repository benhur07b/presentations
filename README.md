# BNHR Presentations

A repository of presentations I've given over the years, published at https://bnhr.xyz/presentations/.

`index.html` lists the presentations by year, newest first: add a card there for each new folder (a training's deck gets its card from `new-deck`, below). `assets/` holds the index page's link-preview image (`share.png`) and its logo, icon and fonts, which are the BNHR 2026 brand files also used by the workshops index.

## In the learning factory

This repository is the factory's **decks**: one per training, beside the presentations given elsewhere. One of the repositories of BNHR's learning factory, beside the hub, [`learn-factory`](https://github.com/benhur07b/learn-factory) (private; its README's *The learning factory* has the model and every repository's role).

- **It holds:** each training's deck, in its own folder, and the index.
- **It reads:** to start a training's deck (`scripts/decks.py new-deck`), the hub's answer for the training (its `scripts/training.py ID --json`: title, days, client, courses and their workbooks, and the agenda from the trainer's delivery file) and the quizzes site's listing (`cohorts.json`: which quiz runs on which day). It reads no other repository's files.
- **It hands on:** each training's room kit copies its deck: the hub's `room_kit.py` finds it with `scripts/decks.py deck-of ID`, from the deck's card. Its addresses (`bnhr.xyz/presentations/<folder>/`) are in materials already given out, so a deck's folder keeps its name.

## Starting a training's deck

A training's deck starts from its record, so its days, agenda and every quiz link and QR code are the ones the quizzes and the trainer use; the presenter writes the rest with the `bnhr-write-slides-build` skill, as for any deck. From this folder, with the hub beside it (`../learn-factory`, where `nvm use 24` and `npm run generate` are done) and the training's quizzes published (or built: `uv run scripts/quizzes.py build --cohort ID` in the quizzes, then add `--listing ../quizzes/dist/cohorts.json`):

```
uv run --project scripts python scripts/decks.py new-deck acme-2027-02           # plans the deck; writes nothing
uv run --project scripts python scripts/decks.py new-deck acme-2027-02 --apply   # writes it, and its card in index.html
```

It writes `<first day>-<quiz set>/` (`--folder` names another): `index.md` with the title slide's fields, the contents, each course's workbook with its code, and each day's section, its agenda (a table per half day, from the trainer's schedule; none for a course with no trainer) and a slide per quiz round, the pre-test first and the post-test last, each with its timer and QR code, and the shared folder's code when the trainer gives one; `deck.css`; `img/qr/`; and a `.gitignore` keeping `index.md` out of git, as every deck here does (the built `index.html` holds the slides). A quiz's link is `bnhr.xyz/quizzes/<set>/<quiz>/<round>/`, without the round for a quiz with one, the quizzes' own rule: for PSA it gives back the twelve links PSA was given. A client the record keeps redacted is named by its type only, on the slides and the card: the deck is a public page. Its card goes at the top of its year in `index.html`, marked `<li data-training="ID">`: that mark is how `deck-of` and the room kit find the deck, so keep it when you edit the card.

Then write the rest of `index.md` with the skill, build `index.html` from it, check it (`uv run scripts/check_links.py <folder>`) and commit on a branch. The deck is yours from then on: a second `new-deck` says the deck is there and writes nothing, and a folder or card of another deck stops it. `uv run --project scripts python scripts/decks.py deck-of ID` prints a training's deck folder (`--json`: and the paths a copy needs, the folder and `assets/`).

Its tests: `uv run --project scripts pytest -q scripts/tests` (a fixture training, with the hub's answer stood in; they read every QR code back as the link check does).

## Checking a deck's links

`uv run scripts/check_links.py` checks every link the presentations make, as a participant would follow it: each link, image, stylesheet and script (a file here, an address on bnhr.xyz/presentations/ included, since this repository is what is published there, so a deck holds before it is published; or an address on the web that opens); each QR code (it decodes, its address opens, and the address typed in its caption is the one it opens); and each link to a quiz on bnhr.xyz/quizzes (a delivery on the quizzes site runs that quiz and round, so its page doesn't say the quiz isn't open). Name deck folders to check only those (`uv run scripts/check_links.py 2026-11-09-qgis-for-sflma-mapping`, before a deck is shown); `--pdfs` checks the links inside the PDF decks too, and `--json PATH` writes every link with its finding. It changes nothing, and exits 1 when a link does not hold. A site that turns scripts away (403, a closed connection, a timeout) is listed as a note, to open by hand. Its packages are in the script itself and `scripts/check_links.py.lock`, so uv needs nothing else; drawing the QR codes needs the Cairo library (`libcairo2` on Debian or Ubuntu).

## License

The presentations are © 2022-2026 Ben Hur S. Pintor and licensed under the [Creative Commons Attribution-ShareAlike 4.0 International License](https://creativecommons.org/licenses/by-sa/4.0/) (`LICENSE.txt`).

The BNHR name and logos are not covered by that license: all rights reserved. Fonts, third-party images and other works used in the decks stay under their own licenses and are credited on the slides where they appear.

`REUSE.toml` names the owner and license of every file that is not under CC BY-SA 4.0, and `LICENSES/` holds the license texts. `uvx reuse lint` checks that every file has one. A deck that adds a third-party image adds an entry for it there.

## TODO
- add more presentations
- make searchable? filterable?
- improve grouping
