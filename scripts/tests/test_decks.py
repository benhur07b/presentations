"""A training's deck started from its record (scripts/decks.py): every link and QR code made by the quizzes' rule from
the listing's ids and read back as the link check reads it, the agenda from the trainer's file, a redacted client's
name on no page, the deck never written twice, and its card the one way to find it.

The tests work on a fixture training: the hub's answer (scripts/training.py --json) stood in, a quizzes listing written
as the quizzes' build writes cohorts.json, and a copy of this repository's index.html in a scratch folder."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

import check_links
import decks

TRAINING = "acme-2027-02"
BASE = "https://bnhr.xyz/quizzes/"
PSA_LINKS = [f"{BASE}python-data-management/{q}" for d in (1, 2, 3)
             for q in (f"day{d}/pre/", f"day{d}-morning/", f"day{d}-afternoon/", f"day{d}/post/")]


def answer(**changes) -> dict:
    """The hub's answer for the fixture training: two days of Python Essentials, its agenda from its trainer's file."""
    found = {
        "id": TRAINING, "title": "Python Essentials for ACME", "type": "client",
        "client": {"type": "private", "label": "Private company", "name": "ACME"}, "venue": None,
        "days": ["2027-02-02", "2027-02-03"],
        "courses": [{"id": "python-essentials", "name": "Python Essentials", "code": "ESS",
                     "site": {"id": "python", "name": "Learn Python with BNHR", "url": "https://learn-python.bnhr.xyz/"},
                     "workbook": "https://learn-python.bnhr.xyz/essentials/00-about/", "trainer": "python"}],
        "quizzes": BASE, "trainers": [{"id": "python", "repo": "/x/learn-python-trainer", "delivery": "essentials/deliveries/acme-2027-02.toml"}],
        "agenda": {"trainer": "python", "file": "essentials/deliveries/acme-2027-02.toml", "outputs_url": "https://example.org/acme-folder",
                   "days": [{"date": "2027-02-02", "title": "Values and decisions", "schedule": [
                       ["08:00–08:30", "Arrival and preparation", ""], ["08:30–08:45", "**Pre-test**", "essentials/00_start.ipynb"],
                       ["08:45–10:00", "Values | names", ""], ["10:00–10:15", "*Break*", ""], ["10:15–11:00", "Collections", ""],
                       ["11:00–11:30", "Decisions", ""], ["11:30–12:00", "Repetition", ""], ["12:00–13:00", "*Lunch*", ""],
                       ["13:00–16:30", "Functions", ""], ["16:30–16:45", "**Post-test**", ""]]},
                            {"date": "2027-02-03", "title": None, "schedule": []}]},
    }
    return found | changes


def quiz(id_: str, kind: str, title: str) -> dict:
    rounds = {"test": ["pre", "post"], "check-in": ["check-in"], "survey": ["survey"]}[kind]
    return {"id": id_, "title": title, "kind": kind, "label": kind.capitalize(), "rounds": rounds, "reveal": "open",
            "light": kind == "check-in", "questions": 4}


def listing(days: list[str] | None = None, cohort_id: str = TRAINING) -> dict:
    """cohorts.json, as the quizzes' build writes it: day 1 with its test and two check-ins, day 2 with a check-in and a
    survey and no test."""
    days = days or ["2027-02-02", "2027-02-03"]
    return {"v": 2, "site": "x", "types": [], "selfPaced": [], "cohorts": [{
        "id": cohort_id, "title": "Python Essentials, ACME", "courseId": "python-essentials", "course": "Python Essentials",
        "roundLabels": {"pre": "Pre-test", "post": "Post-test", "check-in": "Check-in", "survey": "Feedback"},
        "group": "table", "handIn": "assistant",
        "days": [{"date": days[0], "quizzes": [quiz("day1-test", "test", "Day 1: Values and names, Collections"),
                                               quiz("values-and-names", "check-in", "Check-in: Values and names"),
                                               quiz("collections", "check-in", "Check-in: Collections")]},
                 *({"date": d, "quizzes": [quiz("functions", "check-in", "Check-in: Functions"), quiz("feedback", "survey", "Feedback")]}
                   for d in days[1:])]}]}


class Hub:
    """The hub's training.py, stood in: answers as its --json does, or refuses as it would."""

    def __init__(self, found: dict | None = None, refuse: tuple[int, str] | None = None) -> None:
        self.found, self.refuse, self.runs = found or answer(), refuse, []

    def __call__(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess:
        self.runs.append((command, cwd))
        if self.refuse:
            return subprocess.CompletedProcess(command, self.refuse[0], "", self.refuse[1])
        return subprocess.CompletedProcess(command, 0, json.dumps(self.found) + "\n", "")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A scratch presentations folder: this repository's index.html, and a hub with its training.py beside it."""
    root = tmp_path / "presentations"
    root.mkdir()
    (root / "index.html").write_text((decks.ROOT / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "learn-factory" / "scripts").mkdir(parents=True)
    (tmp_path / "learn-factory" / "scripts" / "training.py").write_text("", encoding="utf-8")
    (tmp_path / "cohorts.json").write_text(json.dumps(listing()), encoding="utf-8")
    return root


def plan(repo: Path, hub: Hub | None = None, folder: str | None = None, listed: str | None = None) -> decks.Deck:
    return decks.plan(TRAINING, repo.parent / "learn-factory", listed or str(repo.parent / "cohorts.json"), folder, repo, hub or Hub())


def written(repo: Path) -> dict[str, bytes]:
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in sorted(repo.rglob("*")) if p.is_file()}


# ── The deck ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_deck_is_planned_from_the_record_and_the_listing_and_written_only_with_apply(repo: Path) -> None:
    hub = Hub()
    deck = plan(repo, hub)
    assert hub.runs == [(decks.TRAINING + [TRAINING, "--json"], repo.parent / "learn-factory")]
    assert deck.folder == "2027-02-02-python-essentials" and not deck.present
    assert not (repo / deck.folder).exists()  # planned, nothing written
    decks.apply(deck, repo)
    assert sorted(p.relative_to(repo / deck.folder).as_posix() for p in (repo / deck.folder).rglob("*") if p.is_file()) == sorted(deck.files)
    assert (repo / deck.folder / ".gitignore").read_text() == "index.md\n"  # as every deck here keeps its source out of git
    md = (repo / deck.folder / "index.md").read_text(encoding="utf-8")
    assert md.startswith("---\nstyle: 2026\ntitle: 'Python Essentials for ACME'\n")
    assert "subtitle: 'Python Essentials<br>2 and 3 February 2027<br>ACME'" in md
    assert "  url: 'https://bnhr.xyz/presentations/2027-02-02-python-essentials/'" in md


def test_every_quiz_link_is_made_by_the_quizzes_rule_and_the_room_takes_them_in_order(repo: Path) -> None:
    deck = plan(repo)
    assert [(q.day, q.label, q.url) for q in deck.quizzes] == [
        (1, "Pre-test", f"{BASE}python-essentials/day1-test/pre/"),
        (1, "Check-in", f"{BASE}python-essentials/values-and-names/"),
        (1, "Check-in", f"{BASE}python-essentials/collections/"),
        (1, "Post-test", f"{BASE}python-essentials/day1-test/post/"),
        # a day without a test: its check-in and its survey, each with one round, so no round in its link
        (2, "Check-in", f"{BASE}python-essentials/functions/"),
        (2, "Feedback", f"{BASE}python-essentials/feedback/"),
    ]


def test_every_qr_code_decodes_to_the_address_its_caption_shows_as_the_link_check_reads_them(repo: Path) -> None:
    deck = plan(repo)
    decks.apply(deck, repo)
    folder = repo / deck.folder
    page = check_links.read_page((folder / "index.md").read_text(encoding="utf-8"))
    assert len(page.qrs) == 6 * 2 + 1  # each quiz round with the shared folder beside it, and the workbook
    for qr in page.qrs:
        decoded = check_links.decode_qr(folder / qr["src"])
        shown = check_links.caption_address(qr["caption"])
        if qr["src"] == "img/qr/outputs-folder.svg":
            assert decoded == "https://example.org/acme-folder" and shown is None  # its caption says what it is for
        else:
            assert check_links.bare(shown) == check_links.bare(decoded), qr["src"]
    assert {check_links.decode_qr(folder / q.qr) for q in deck.quizzes} == {q.url for q in deck.quizzes}
    # every image the slides name is there
    assert all((folder / src).is_file() for src in re.findall(r'src="([^"]+)"', (folder / "index.md").read_text()))


def test_the_rule_gives_back_the_twelve_links_psa_was_given(repo: Path) -> None:
    """PSA's links were made by hand, and are in materials given out: the deck's rule, on PSA's listing, makes the same."""
    cohort = {"id": "psa-2026-10", "courseId": "python-data-management", "roundLabels": {"pre": "Pre-test", "post": "Post-test"},
              "days": [{"date": d, "quizzes": [quiz(f"day{n}", "test", ""), quiz(f"day{n}-morning", "check-in", ""),
                                               quiz(f"day{n}-afternoon", "check-in", "")]}
                       for n, d in enumerate(["2026-10-28", "2026-10-29", "2026-10-30"], start=1)]}
    made = [q.url for n, day in enumerate(cohort["days"], start=1) for q in decks.day_quizzes(n, day, cohort, BASE)]
    assert made == PSA_LINKS


def test_the_agenda_is_a_table_per_half_day_never_longer_than_a_slide_holds(repo: Path) -> None:
    deck = plan(repo)
    md = deck.files["index.md"].decode()
    assert "## Day 1, the *morning*.\n" in md and "## Day 1, the *morning*, continued.\n" in md and "## Day 1, the *afternoon*.\n" in md
    tables = re.findall(r"\| Time \| What \|\n\|:--\|:--\|\n((?:\|.*\n?)+)", md)
    assert [len(t.strip().splitlines()) for t in tables] == [4, 3, 3]  # seven morning rows as four and three, then the afternoon
    assert r"| 08:45–10:00 | Values \| names |" in md  # a pipe in a row stays in its cell
    assert "# Day 2.\n" in md  # a day the trainer's file gives no title, and no schedule: its section, and no table


def test_a_training_whose_course_has_no_trainer_gets_its_quizzes_and_no_agenda(repo: Path) -> None:
    deck = plan(repo, Hub(answer(agenda=None, trainers=[])))
    md = deck.files["index.md"].decode()
    assert "| Time | What |" not in md and "outputs-folder" not in md and "img/qr/outputs-folder.svg" not in deck.files
    assert len(deck.quizzes) == 6
    assert any("no agenda" in n for n in deck.notes) and any("no shared folder" in n for n in deck.notes)


def test_a_redacted_clients_name_is_on_no_page(repo: Path) -> None:
    hub = Hub(answer(client={"type": "private", "label": "Private company", "name": None}))
    deck = plan(repo, hub)
    decks.apply(deck, repo)
    for name, content in written(repo).items():
        assert b"ACME" not in content.replace(b"Python Essentials for ACME", b""), name  # the title is the author's
    assert "Private company" in (repo / "index.html").read_text() and "Private company" in deck.files["index.md"].decode()


def test_the_card_goes_at_the_top_of_its_year_marked_with_the_training(repo: Path) -> None:
    before = (repo / "index.html").read_text()
    decks.apply(plan(repo), repo)
    after = (repo / "index.html").read_text()
    assert after.count('<li data-training="acme-2027-02">') == 1
    assert after.index("  <h2>2027</h2>") < after.index("  <h2>2026</h2>")  # a year it had no heading for, in order
    assert after.replace(plan_card(after), "") .replace("  <h2>2027</h2>\n  <ul>\n  </ul>\n\n", "") == before
    assert decks.deck_of(TRAINING, repo) == {"training": TRAINING, "folder": "2027-02-02-python-essentials",
                                              "paths": ["2027-02-02-python-essentials", "assets"]}


def plan_card(index: str) -> str:
    return re.search(r'    <li data-training="acme-2027-02">.*?</li>\n', index, re.S).group(0)


def test_with_card_puts_a_card_under_an_existing_year():
    index = "<main>\n  <h2>2027</h2>\n  <ul>\n    <li>old</li>\n  </ul>\n\n  <h2>2026</h2>\n  <ul>\n  </ul>\n</main>"
    assert decks.with_card(index, "    <li>new</li>", 2027) == index.replace("  <ul>\n    <li>old", "  <ul>\n    <li>new</li>\n    <li>old")
    assert decks.with_card(index, "    <li>new</li>", 2025).endswith("  <h2>2025</h2>\n  <ul>\n    <li>new</li>\n  </ul>\n\n</main>")


def test_the_command_writes_once_and_a_second_run_writes_nothing(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(decks, "run", Hub())
    command = ["--root", str(repo), "new-deck", TRAINING, "--hub", str(repo.parent / "learn-factory"), "--listing", str(repo.parent / "cohorts.json")]
    before = written(repo)
    assert decks.main(command) == decks.DONE and written(repo) == before  # planned only
    assert "DRY RUN" in capsys.readouterr().err
    assert decks.main([*command, "--apply"]) == decks.DONE
    (repo / "2027-02-02-python-essentials" / "index.md").write_text("the presenter's own", encoding="utf-8")
    edited = written(repo)
    assert decks.main([*command, "--apply", "--json"]) == decks.DONE
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["present"] is True
    assert written(repo) == edited  # the presenter's deck, never written over


def test_a_folder_or_a_card_of_another_deck_stops_it(repo: Path) -> None:
    (repo / "2027-02-02-python-essentials").mkdir()
    with pytest.raises(decks.Stop) as stop:
        plan(repo)
    assert stop.value.code == decks.CONFLICT and "another deck" in str(stop.value)
    decks.apply(plan(repo, folder="2027-02-02-acme"), repo)
    with pytest.raises(decks.Stop) as stop:
        plan(repo, folder="2027-02-02-other")
    assert stop.value.code == decks.CONFLICT and "2027-02-02-acme/ already" in str(stop.value)
    with pytest.raises(decks.Stop) as stop:
        plan(repo, folder="Not a Folder")
    assert stop.value.code == decks.USAGE


def test_the_record_and_the_quizzes_must_agree_on_the_days(repo: Path) -> None:
    (repo.parent / "cohorts.json").write_text(json.dumps(listing(["2027-02-02", "2027-02-04"])), encoding="utf-8")
    with pytest.raises(decks.Stop) as stop:
        plan(repo)
    assert stop.value.code == decks.DATA and "disagree" in str(stop.value)


def test_a_delivery_the_listing_doesnt_have_says_how_to_build_one(repo: Path) -> None:
    (repo.parent / "cohorts.json").write_text(json.dumps(listing(cohort_id="someone-else")), encoding="utf-8")
    with pytest.raises(decks.Stop) as stop:
        plan(repo)
    assert stop.value.code == decks.NO_INPUT and "build --cohort acme-2027-02" in str(stop.value)
    with pytest.raises(decks.Stop) as stop:
        plan(repo, listed=str(repo.parent / "missing.json"))
    assert stop.value.code == decks.NO_INPUT


def test_the_hubs_refusal_and_a_wrong_answer_stop_it_with_their_reason(repo: Path) -> None:
    with pytest.raises(decks.Stop) as stop:
        plan(repo, Hub(refuse=(66, "error: no training 'acme-2027-02'")))
    assert stop.value.code == decks.NO_INPUT and "no training" in str(stop.value)
    with pytest.raises(decks.Stop) as stop:
        plan(repo, Hub({"id": TRAINING}))
    assert stop.value.code == decks.CONFIG
    with pytest.raises(decks.Stop) as stop:
        decks.plan(TRAINING, repo.parent / "nowhere", None, None, repo, Hub())
    assert stop.value.code == decks.CONFIG


def test_deck_of_a_training_without_a_card(repo: Path) -> None:
    with pytest.raises(decks.Stop) as stop:
        decks.deck_of(TRAINING, repo)
    assert stop.value.code == decks.NO_INPUT


# ── Words ──────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("days", "text"), [
    (["2026-10-28", "2026-10-29", "2026-10-30"], "28–30 October 2026"),
    (["2026-11-14", "2026-11-15", "2026-11-21", "2026-11-22"], "14, 15, 21 and 22 November 2026"),
    (["2026-10-30", "2026-11-02"], "30 October 2026; 2 November 2026"),
])
def test_dates_text(days: list[str], text: str) -> None:
    import datetime as dt

    assert decks.dates_text([dt.date.fromisoformat(d) for d in days]) == text


@pytest.mark.parametrize("url", ["https://bnhr.xyz/quizzes/python-essentials/day1-test/pre/",
                                 "https://learn-qgis.bnhr.xyz/sflma-mapping/00-about/", "https://bnhr.xyz/quizzes/x/y"])
def test_a_caption_reads_back_as_its_address(url: str) -> None:
    page = check_links.read_page(f'<img class="qr" src="x.svg"><p class="qr-caption"><b>1 · The test</b>{decks.caption(url)}</p>')
    assert check_links.bare(check_links.caption_address(page.qrs[0]["caption"])) == check_links.bare(url)
