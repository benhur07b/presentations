# BNHR Presentations

A repository of presentations I've given over the years, published at https://bnhr.xyz/presentations/.

`index.html` lists the presentations by year, newest first: add a card there for each new folder. `assets/` holds the index page's link-preview image (`share.png`) and its logo, icon and fonts, which are the BNHR 2026 brand files also used by the workshops index.

## Checking a deck's links

`uv run scripts/check_links.py` checks every link the presentations make, as a participant would follow it: each link, image, stylesheet and script (a file here, or an address on the web that opens); each QR code (it decodes, its address opens, and the address typed in its caption is the one it opens); and each link to a quiz on bnhr.xyz/quizzes (a delivery on the quizzes site runs that quiz and round, so its page doesn't say the quiz isn't open). Name deck folders to check only those (`uv run scripts/check_links.py 2026-11-09-qgis-for-sflma-mapping`, before a deck is shown); `--pdfs` checks the links inside the PDF decks too, and `--json PATH` writes every link with its finding. It changes nothing, and exits 1 when a link does not hold. A site that turns scripts away (403, a closed connection, a timeout) is listed as a note, to open by hand. Its packages are in the script itself and `scripts/check_links.py.lock`, so uv needs nothing else; drawing the QR codes needs the Cairo library (`libcairo2` on Debian or Ubuntu).

## TODO
- add more presentations
- make searchable? filterable?
- improve grouping
