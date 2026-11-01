"""A training's deck, started from its record; and which deck is a training's.

    uv run --project scripts python scripts/decks.py new-deck ID            # plans the deck; writes nothing
    uv run --project scripts python scripts/decks.py new-deck ID --apply    # writes its folder and its card in index.html
    uv run --project scripts python scripts/decks.py deck-of ID [--json]    # the folder of a training's deck

new-deck starts the deck of a training, ID being its id in the learn-factory hub (the same in the quizzes and its
trainer). It reads three answers, never another repository's files:

- the hub's `scripts/training.py ID --json`, run in the hub beside this repository: the training's title, days, client
  (named only when the record names it: a redacted client's name reaches no page), its courses with their workbooks'
  addresses, and its agenda from its trainer's delivery file, when its course has a trainer;
- the quizzes site's listing, `cohorts.json` at the hub's quizzes address (the one the link check reads), or --listing,
  a file or an address: a delivery built but not yet published is read from `quizzes/dist/cohorts.json` after the
  quizzes' `build --cohort ID`. It says which quiz runs on which day, its kind, title and rounds.

It writes `<first day>-<quiz set>/` (or --folder): `index.md` with the title slide's fields, the contents, a slide with
each course's workbook and its code, then each day: its section, its agenda (a table per half day, from the trainer's
schedule), and a slide per quiz round, the pre-test first and the post-test last, each with its timer and QR code, and
the shared folder's code when the trainer's file gives one; `deck.css`; `img/qr/*.svg`; and a `.gitignore` that keeps
`index.md` out of git, as every deck here does (the built `index.html` holds the slides). Every link is made by the
quizzes' own rule, `<quizzes>/<set>/<quiz>/<round>/` (no round for a quiz with one), from the listing's ids: the same
address the trainer's notebooks and QR codes give. It adds the deck's card to `index.html`, at the top of its year,
marked with the training's id (`<li data-training="ID">`): that mark is how `deck-of` finds a training's deck, and how
the hub's room kit finds it.

The deck is the presenter's from then on: write the rest with the `bnhr-write-slides-build` skill and build `index.html`
with it, then check it with `uv run scripts/check_links.py <folder>`. Nothing here writes a deck again: once its card
is in `index.html` and its folder exists, new-deck says so and writes nothing; a folder of another deck, or a card that
names another folder, stops it.

deck-of answers which folder a training's deck is in, from its card, and the paths a copy of it needs (offline_deck.py's,
which the room kit holds): the folder, and `assets/`, which every deck's pages link to.

Assumptions: the hub sits beside this repository (`../learn-factory`, as in the factory's workspace) or is given with
--hub; its own command needs Node (`nvm use 24`) and `npm run generate` done there.

Exit codes: 0 done (or planned, or there already); 2 usage; 5 the folder or the card is another deck's; 65 the hub, the
listing or the agenda disagree on the training's days, or a value can't be shown; 66 no such training, or no delivery of
it in the listing, or no card for it; 78 the hub is not where expected, or answers otherwise than its --json says.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import segno

ROOT = Path(__file__).resolve().parents[1]  # this repository, presentations/
SITE = "https://bnhr.xyz/presentations/"
DONE, USAGE, CONFLICT, DATA, NO_INPUT, CONFIG = 0, 2, 5, 65, 66, 78
TRAINING = ["uv", "run", "--project", "scripts", "python", "scripts/training.py"]  # the hub's answer, run from its folder
FOLDER = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*")
NAVY = "#0c2340"  # the brand's navy, as the trainers' QR codes are drawn: dark enough on white for every phone camera
ROWS_PER_SLIDE = 6  # a table's body rows on one slide, before it crowds the footer (the slides skill)
# A round's timer on its slide (minutes, and the extra minutes T gives), as the decks given so far run them
TIMERS = {"pre": (10, 3), "post": (8, 3), "check-in": (3, 1)}
HAND_IN = {"assistant": "hand the file it downloads to the training assistant", "drive": "put the file it downloads in the shared folder",
           "send": "send the file it downloads with the page's buttons"}
NUMBERS = "one two three four five six seven eight nine ten".split()
SHARED = ("assets",)  # what every deck's pages link to beside its own folder: a copy of a deck takes it too
CARD = re.compile(r'<li data-training="(?P<id>[^"]+)">.*?<a href="(?P<href>[^"]+)"', re.S)

Run = Callable[[list[str], Path], subprocess.CompletedProcess]


class Stop(Exception):
    """A refusal, with the exit code it ends the command with."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Another repository's command, from its folder, in its own environment: this command's (VIRTUAL_ENV) is left out."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)


# ── What the deck is made from ─────────────────────────────────────────────────────────────────────────────────────


def read_training(training: str, hub: Path, run_command: Run | None = None) -> dict:
    """The hub's answer for the training (its scripts/training.py --json)."""
    run_command = run_command or run
    if not (hub / "scripts" / "training.py").is_file():
        raise Stop(CONFIG, f"the hub is not at {hub} (no scripts/training.py): give it with --hub")
    done = run_command([*TRAINING, training, "--json"], hub)
    if done.returncode != 0:
        code = done.returncode if done.returncode in (DATA, NO_INPUT, CONFIG) else CONFIG
        raise Stop(code, f"the hub's training.py refused it (exit {done.returncode}):\n{(done.stderr or done.stdout).strip()}")
    try:
        answer = json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise Stop(CONFIG, f"the hub's training.py answered something else than its --json: {done.stdout.strip()[:300]}") from error
    if not {"id", "title", "days", "courses", "quizzes", "client", "agenda"} <= set(answer):
        raise Stop(CONFIG, "the hub's training.py answered without the keys new-deck reads (id, title, days, courses, quizzes, client, agenda)")
    return answer


def read_listing(where: str) -> dict:
    """The quizzes site's listing, from a file or an address."""
    try:
        if re.match(r"https?://", where):
            request = urllib.request.Request(where, headers={"User-Agent": "Mozilla/5.0 (presentations new-deck)"})
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.load(response)
        return json.loads(Path(where).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Stop(NO_INPUT, f"the quizzes listing at {where} could not be read ({error}): give a built one with --listing "
                             "../quizzes/dist/cohorts.json, after the quizzes' `build --cohort ID`") from error


def delivery_of(listing: dict, training: str, where: str) -> dict:
    for cohort in listing.get("cohorts", []):
        if cohort.get("id") == training:
            return cohort
    raise Stop(NO_INPUT, f"the quizzes listing at {where} has no dated delivery {training}: publish its delivery, or build it "
                         f"(`uv run scripts/quizzes.py build --cohort {training}` in the quizzes) and give --listing "
                         "../quizzes/dist/cohorts.json")


# ── Words ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def dates_text(days: list[dt.date]) -> str:
    """28–30 October 2026; 14, 15, 21 and 22 November 2026: three days or more in a row as a range, the rest one by one,
    as the trainer's setup guide writes them."""
    months: dict[tuple[int, int], list[int]] = {}
    for day in days:
        months.setdefault((day.year, day.month), []).append(day.day)
    parts = []
    for (year, month), numbers in months.items():
        runs: list[list[int]] = []
        for n in numbers:
            if runs and n == runs[-1][-1] + 1:
                runs[-1].append(n)
            else:
                runs.append([n])
        items = [item for r in runs for item in ([f"{r[0]}–{r[-1]}"] if len(r) > 2 else map(str, r))]
        joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
        parts.append(f"{joined} {dt.date(year, month, 1):%B} {year}")
    return "; ".join(parts)


def counted_days(n: int) -> str:
    return "the day" if n == 1 else f"the {NUMBERS[n - 1] if n <= len(NUMBERS) else n} days"


def who(training: dict) -> str:
    """Who the training is for, as a page may show it: the client's name only when the record names it, else its type."""
    client = training.get("client")
    if client:
        return client["name"] or client["label"]
    return training.get("venue") or "Public training"


def yaml_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def cell(value: str) -> str:
    return value.replace("|", "\\|")


def caption(url: str) -> str:
    """The address as a QR caption shows it, without its scheme, each part kept whole and wrapping only after a slash:
    the link check reads it back and compares it with the code."""
    parts = re.sub(r"^https?://", "", url).split("/")
    shown = [p + "/" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    return "<wbr>".join(f'<span class="nw">{html.escape(p)}</span>' for p in shown)


def qr_svg(url: str) -> bytes:
    """The QR code of an address, as the trainers draw theirs (segno, error level M, navy on white)."""
    out = io.BytesIO()
    segno.make(url, error="m", micro=False).save(out, kind="svg", scale=10, border=4, dark=NAVY)
    return out.getvalue()


# ── The plan ───────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QuizSlide:
    day: int
    order: int  # its place among the day's quiz slides, from 1
    round: str  # pre, post, check-in, survey…
    label: str  # how the delivery names the round (Pre-test, Check-in…)
    title: str  # the quiz's title on the quizzes site
    url: str
    light: bool  # it ends with the traffic light

    @property
    def qr(self) -> str:
        return f"img/qr/day{self.day}-{self.order}-{re.sub(r'[^a-z0-9]+', '-', self.label.lower()).strip('-')}.svg"


@dataclass
class Deck:
    training: dict
    folder: str
    present: bool  # its folder and its card are there already: nothing to write
    files: dict[str, bytes] = field(default_factory=dict)
    card: str = ""
    quizzes: list[QuizSlide] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def quiz_url(base: str, quiz_set: str, quiz: dict, round_: str) -> str:
    """Where a quiz round's page is, by the quizzes' rule: <set>/<quiz>/<round>/, or <set>/<quiz>/ for a quiz with one
    round (quizzes.py's quiz_path, the trainers' quiz_url)."""
    return f"{base}{quiz_set}/{quiz['id']}/" + ("" if len(quiz["rounds"]) == 1 else f"{round_}/")


def day_quizzes(number: int, day: dict, cohort: dict, base: str) -> list[QuizSlide]:
    """A day's quiz slides, in the order the room takes them: each test's first round (the pre-test) first, the
    quizzes with one round (check-ins, surveys) in the listing's order, each test's last round (the post-test) last."""
    labels = cohort.get("roundLabels", {})
    first, middle, last = [], [], []
    for quiz in day.get("quizzes", []):
        rounds = quiz["rounds"]
        made = [(r, quiz) for r in rounds]
        if len(rounds) == 1:
            middle += made
        else:
            first.append(made[0])
            last.append(made[-1])
            middle += made[1:-1]
    return [QuizSlide(number, k, r, labels.get(r, r.replace("-", " ").capitalize()), quiz.get("title", quiz["id"]),
                      quiz_url(base, cohort["courseId"], quiz, r), bool(quiz.get("light")))
            for k, (r, quiz) in enumerate([*first, *middle, *last], start=1)]


def halves(rows: list[list[str]]) -> list[tuple[str, list[list[str]]]]:
    """A day's schedule as slides, each with its heading's part of the day: its morning (rows starting before noon) and
    its afternoon, each split into as few slides of at most ROWS_PER_SLIDE rows as it takes, of near-equal length."""
    parts = {"morning": [r for r in rows if r[0][:5] < "12:00"], "afternoon": [r for r in rows if r[0][:5] >= "12:00"]}
    slides = []
    for name, part in parts.items():
        if not part:
            continue
        n = math.ceil(len(part) / ROWS_PER_SLIDE)
        size = math.ceil(len(part) / n)
        slides += [(f"*{name}*" + (", continued" if i else ""), part[i * size:(i + 1) * size]) for i in range(n)]
    return slides


DECK_CSS = """/* {title}: the deck's own meanings and layouts, on top of the 2026 style. Started by new-deck; the presenter's from here. */

/* The check-in's traffic light, in the colours the quiz page shows (quizzes/site/css/site.css) */
:root {{
  --light-green: #1f8a4c;
  --light-yellow: #e0b400;
  --light-red: #c0392b;
}}
.dot.light-green {{ --dot: var(--light-green); }}
.dot.light-yellow {{ --dot: var(--light-yellow); }}
.dot.light-red {{ --dot: var(--light-red); }}

/* A quiz slide: the quiz and the folder its file goes in, side by side */
.qr-pair {{ display: flex; justify-content: center; gap: 160px; margin-top: 8px; }}
.qr-pair .qr-col {{ width: 520px; }}
.reveal .slides section .qr-pair img.qr {{ width: 330px; height: 330px; }}
.reveal .slides section .qr-pair p.qr-caption {{ color: var(--navy); }}
.reveal .slides section .qr-pair p.qr-caption b {{ display: block; font-family: var(--font-title); font-weight: 800; font-size: 26pt; letter-spacing: -0.015em; text-transform: none; margin-bottom: 6px; }}

/* A check-in's traffic light on one line, above its codes */
.reveal .slides section .lights {{ display: flex; justify-content: center; gap: 56px; font-size: 24pt; margin: 0 0 24px; }}
.reveal .slides section .lights > span {{ display: inline-flex; align-items: center; gap: 14px; }}

/* The workbook slide: what is where beside its code */
.reveal .slides section .split.qr-split .rows > div {{ font-size: 26pt; }}
.reveal .slides section .split.qr-split img.qr {{ width: 390px; height: 390px; }}

/* A row's label keeps to one line; its text wraps beside it */
.reveal .slides section .rows > div > b {{ flex: none; }}

/* A highlighted word on a navy slide stays whole: "open-source" never breaks at its hyphen */
.reveal .slides section.section-slide h1 em {{ white-space: nowrap; }}
"""


def qr_column(number: int | None, what: str, image: str, alt: str, shown: str) -> str:
    label = f"{number} · {what}" if number else what
    return (f'<div class="qr-col"><img class="qr" src="{image}" alt="{html.escape(alt)}"><p class="qr-caption">'
            f"<b>{html.escape(label)}</b>{shown}</p></div>")


def quiz_slide(q: QuizSlide, outputs: bool, hand_in: str) -> str:
    noun = {"pre": "test", "post": "test"}.get(q.round, q.label.lower())
    if q.round == "pre":
        heading = f"Day {q.day} {q.label.lower()}: nobody expects you to know these *yet*."
    elif q.round == "post":
        heading = f"Day {q.day} {q.label.lower()}: the same questions, *again*."
    else:
        heading = f"{html.escape(q.title)}."
    parts = [f"## {heading}", ""]
    if q.round in TIMERS:
        minutes, extra = TIMERS[q.round]
        parts += [f'<bnhr-timer minutes="{minutes}" extra="{extra}"></bnhr-timer>', ""]
    if q.light:
        parts += ['<div class="lights"><span><span class="dot light-green"></span>On my own data tomorrow</span><span><span class="dot '
                  'light-yellow"></span>With the notes</span><span><span class="dot light-red"></span>Not yet</span></div>', ""]
    alt = f"QR code for the Day {q.day} {q.label.lower()}" if q.round in ("pre", "post") else f"QR code for {q.title}"
    columns = [qr_column(1 if outputs else None, f"The {noun}", q.qr, alt, caption(q.url))]
    if outputs:
        columns.append(qr_column(2, "The shared folder", "img/qr/outputs-folder.svg", "QR code for the shared folder", "Your downloaded file goes here"))
    parts += ['<div class="qr-pair">', *columns, "</div>", "", "Note:",
              f"{q.title} ({q.label.lower()}). Scan the code, answer and submit, then {HAND_IN.get(hand_in, HAND_IN['assistant'])}."
              + (" T starts the timer." if q.round in TIMERS else "")]
    return "\n".join(parts)


def plan(training_id: str, hub: Path, listing_at: str | None, folder: str | None, root: Path = ROOT, run_command: Run | None = None) -> Deck:
    training = read_training(training_id, hub, run_command)
    days = [dt.date.fromisoformat(d) for d in training["days"]]
    where = listing_at or training["quizzes"] + "cohorts.json"
    cohort = delivery_of(read_listing(where), training_id, where)
    if [d.get("date") for d in cohort.get("days", [])] != training["days"]:
        raise Stop(DATA, f"the quizzes run {training_id} on {', '.join(d.get('date', '?') for d in cohort.get('days', []))}, and the "
                         f"record on {', '.join(training['days'])}: the delivery and the record disagree on its days")
    agenda = training["agenda"]
    if agenda and [d["date"] for d in agenda["days"]] != training["days"]:
        raise Stop(DATA, f"{agenda['trainer']}'s {agenda['file']} runs on other days than the record")

    given = folder
    folder = folder or f"{days[0].isoformat()}-{cohort['courseId']}"
    if not FOLDER.fullmatch(folder):
        raise Stop(USAGE, f"a deck's folder is its first day and a name, lowercase, as 2027-02-02-python-essentials, not {folder!r}")
    index = (root / "index.html").read_text(encoding="utf-8")
    cards = {m["id"]: m["href"].rstrip("/") for m in CARD.finditer(index)}
    if training_id in cards:
        if given is not None and given != cards[training_id]:
            raise Stop(CONFLICT, f"{training_id}'s deck is {cards[training_id]}/ already (its card in index.html), not {given}/")
        if not (root / cards[training_id]).is_dir():
            raise Stop(CONFLICT, f"index.html's card for {training_id} names {cards[training_id]}/, which is not here: restore the "
                                 "folder, or remove the card, then start the deck again")
        return Deck(training, cards[training_id], True)
    if (root / folder).exists():
        raise Stop(CONFLICT, f"{folder}/ is here already, and no card in index.html names it {training_id}'s: it is another "
                             "deck; choose another folder with --folder")
    if owner := next((t for t, f in cards.items() if f == folder), None):
        raise Stop(CONFLICT, f"index.html's card for {owner} names {folder}/ already: choose another folder with --folder")

    deck = Deck(training, folder, False)
    base = training["quizzes"]
    outputs = agenda["outputs_url"] if agenda else None
    files: dict[str, bytes] = {}
    named = dates_text(days)
    courses = training["courses"]
    title = training["title"]
    front = ["---", "style: 2026", f"title: {yaml_text(html.escape(title, quote=False))}",
             f"subtitle: {yaml_text('<br>'.join(html.escape(x, quote=False) for x in (' + '.join(c['name'] for c in courses), named, who(training))))}",
             f"project: {yaml_text(courses[0]['site']['name'])}",
             f"page_title: {yaml_text(f'{title}, {named}')}",
             "favicon: '../assets/favicon.svg'", "share:", f"  url: {yaml_text(SITE + folder + '/')}",
             f"  description: {yaml_text(f'The room deck of {title} ({named}): each day’s plan, and the codes for every test and check-in.')}",
             "---", "", '<link rel="stylesheet" href="deck.css">', ""]
    slides = []
    day_titles = [(agenda["days"][i]["title"] if agenda else None) for i in range(len(days))]
    workbooks = [c for c in courses if c["workbook"]]
    toc = [*([f"<li>The workbook{'s' if len(workbooks) > 1 else ''}</li>"] if workbooks else []),
           *(f"<li>Day {n} · {html.escape(t)}</li>" if t else f"<li>Day {n}</li>" for n, t in enumerate(day_titles, start=1))]
    slides.append("\n".join(['<!-- .slide: class="toc-slide" -->', "", "## Contents", "", '<ol class="toc-list">', *toc, "</ol>", "",
                             "Note:", f"Started by new-deck from {training['id']}'s record: the days, their agenda and every quiz's code. "
                             "The rest is yours: write it with the slides skill, and build index.html with it."]))
    for c in courses:
        if not c["workbook"]:
            continue
        image = f"img/qr/workbook-{c['id']}.svg"
        files[image] = qr_svg(c["workbook"])
        slides.append("\n".join([
            f"## {html.escape(c['name'])}: the workbook is yours to *keep*.", "", '<div class="split qr-split">', "<div>", '<div class="rows">',
            f"<div><b>Online</b>every module of {html.escape(c['name'])}, on {html.escape(c['site']['name'])}</div>",
            "<div><b>After the training</b>it stays there, free, for the next time you need it</div>", "</div>", "</div>",
            f'<div class="qr-col"><img class="qr" src="{image}" alt="{html.escape("QR code for the " + c["name"] + " workbook")}">'
            f'<p class="qr-caption">{caption(c["workbook"])}</p></div>', "</div>"]))
    if outputs:
        files["img/qr/outputs-folder.svg"] = qr_svg(outputs)
    for n, (day, listed) in enumerate(zip(days, cohort["days"]), start=1):
        day_title = day_titles[n - 1]
        slides.append("\n".join(['<!-- .slide: class="section-slide" -->', f'<span class="section-label">{day:%A} {day.day} {day:%B}</span>', "",
                                 f"# Day {n}. {html.escape(day_title)}" if day_title else f"# Day {n}."]))
        for half, rows in halves(agenda["days"][n - 1]["schedule"]) if agenda else []:
            table = ["| Time | What |", "|:--|:--|", *(f"| {cell(r[0])} | {cell(r[1])} |" for r in rows)]
            slides.append("\n".join([f"## Day {n}, the {half}.", "", *table]))
        quizzes = day_quizzes(n, listed, cohort, base)
        for q in quizzes:
            files[q.qr] = qr_svg(q.url)
            slides.append(quiz_slide(q, bool(outputs), cohort.get("handIn", "assistant")))
        deck.quizzes += quizzes
    slides.append("\n".join(['<!-- .slide: class="section-slide" -->', "", "# Questions?<br>Humayo kayo at magpaka-*open-source*."]))
    files["index.md"] = ("\n".join(front) + "\n" + "\n\n---\n\n".join(slides) + "\n").encode()
    files["deck.css"] = DECK_CSS.format(title=title).encode()
    files[".gitignore"] = b"index.md\n"
    deck.files = files
    if not agenda:
        deck.notes.append("no agenda: no trainer of its courses has a delivery file for it, so its days have no agenda slides")
    if not outputs:
        deck.notes.append("no shared folder: its trainer's file gives no outputs_url, so its quiz slides have no folder code")
    when = f"{named} · {' + '.join(c['name'] for c in courses)}, {who(training)}"
    deck.card = "\n".join([f'    <li data-training="{html.escape(training_id)}">', f'      <span class="when">{html.escape(when)}</span>',
                           f'      <h3 class="what"><a href="{folder}/">{html.escape(title)}</a></h3>',
                           f"      <p>The room deck for {counted_days(len(days))}: each day’s plan, and the codes for every test and check-in.</p>",
                           "    </li>"])
    return deck


def with_card(index: str, card: str, year: int) -> str:
    """index.html with the card at the top of its year's list, the year's heading added in year order when it has none."""
    heading = f"  <h2>{year}</h2>\n  <ul>\n"
    if heading in index:
        return index.replace(heading, heading + card + "\n", 1)
    section = f"{heading}{card}\n  </ul>\n\n"
    for m in re.finditer(r"  <h2>(\d{4})</h2>\n", index):
        if int(m[1]) < year:
            return index[:m.start()] + section + index[m.start():]
    end = index.index("</main>")
    return index[:end] + section + index[end:]


def apply(deck: Deck, root: Path = ROOT) -> None:
    folder = root / deck.folder
    for name, content in deck.files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    index = root / "index.html"
    year = dt.date.fromisoformat(deck.training["days"][0]).year
    index.write_text(with_card(index.read_text(encoding="utf-8"), deck.card, year), encoding="utf-8")


def report(deck: Deck, applied: bool) -> str:
    if deck.present:
        return f"present  {deck.folder}/  ({deck.training['id']}'s deck, with its card in index.html: the presenter's; nothing written)"
    verb = "wrote" if applied else "create"
    rows = [f"{verb:8s} {deck.folder}/: {', '.join(sorted(n for n in deck.files if not n.startswith('img/')))}, "
            f"{sum(1 for n in deck.files if n.startswith('img/'))} QR codes",
            f"{'added' if applied else 'add':8s} index.html: its card, marked data-training=\"{deck.training['id']}\""]
    rows += [f"         day {q.day} {q.label.lower():<10} {q.url}" for q in deck.quizzes]
    rows += [f"{'note':8s} {note}" for note in deck.notes]
    return "\n".join(rows)


# ── deck-of ────────────────────────────────────────────────────────────────────────────────────────────────────────


def deck_of(training: str, root: Path = ROOT) -> dict:
    """The folder of a training's deck, from its card in index.html, and the paths a copy of it needs."""
    cards = {m["id"]: m["href"].rstrip("/") for m in CARD.finditer((root / "index.html").read_text(encoding="utf-8"))}
    if training not in cards:
        raise Stop(NO_INPUT, f"index.html has no card for {training} (<li data-training=\"{training}\">): start its deck with "
                             f"`decks.py new-deck {training}`; a deck made by hand is found once its card has that mark")
    folder = cards[training]
    if not (root / folder).is_dir():
        raise Stop(DATA, f"index.html's card for {training} names {folder}/, which is not here")
    return {"training": training, "folder": folder, "paths": [folder, *SHARED]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="decks.py", description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new-deck", help="start a training's deck from its record; writes only with --apply")
    new.add_argument("training", help="the training's id, as in the hub's record and the quizzes")
    new.add_argument("--apply", action="store_true", help="write the deck's folder and its card; without it, only plan them")
    new.add_argument("--listing", help="the quizzes' listing, a file or an address (default: cohorts.json on the quizzes site)")
    new.add_argument("--folder", help="the deck's folder (default: <first day>-<quiz set>)")
    new.add_argument("--hub", type=Path, default=ROOT.parent / "learn-factory", help="the hub (default: learn-factory/ beside this repository)")
    new.add_argument("--json", action="store_true", help="print what it planned or did as JSON")
    of = commands.add_parser("deck-of", help="the folder of a training's deck, and the paths a copy of it needs")
    of.add_argument("training")
    of.add_argument("--json", action="store_true", help="print the answer as JSON")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == "deck-of":
            found = deck_of(args.training, args.root)
            print(json.dumps(found) if args.json else found["folder"])
            return DONE
        deck = plan(args.training, args.hub.resolve(), args.listing, args.folder, args.root)
        if args.apply and not deck.present:
            apply(deck, args.root)
        if args.json:
            print(json.dumps({"training": args.training, "folder": deck.folder, "applied": args.apply, "present": deck.present,
                              "files": sorted(deck.files), "quizzes": [q.url for q in deck.quizzes], "notes": deck.notes}))
        else:
            print(report(deck, args.apply))
        sys.stdout.flush()
        if not args.apply:
            print("DRY RUN: nothing written. Run again with --apply to write it.", file=sys.stderr)
        elif not deck.present:
            print(f"Next, the presenter's: write the rest of {deck.folder}/index.md with the slides skill, build index.html from it, "
                  f"then `uv run scripts/check_links.py {deck.folder}`; commit on a branch.", file=sys.stderr)
    except Stop as stop:
        print(f"error: {stop}", file=sys.stderr)
        return stop.code
    return DONE


if __name__ == "__main__":
    sys.exit(main())
