"""Deck view page merging on made-up pages (run: python -m tests.test_deckview)."""

import sys

from stsbot.campfire import GridCard
from stsbot.deckview import merge_pages

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def row(names, y):
    return [GridCard(n, "Attack", "", 0.2 + 0.15 * i, y) for i, n in enumerate(names)]


r1 = ["Strike"] * 5
r2 = ["Defend"] * 4 + ["Bash+"]
r3 = ["Shrug It Off", "Ashen Strike", "Cinder"]

# Page 1 shows rows 1 and 2; after scrolling, page 2 shows rows 2 and 3 (row 2 overlaps).
p1 = row(r1, 0.29) + row(r2, 0.64)
p2 = row(r2, 0.25) + row(r3, 0.6)
names = [c.name for c in merge_pages([p1, p2])]
check("overlapping row counted once", names, r1 + r2 + r3)
check("13 cards", len(names), 13)

# No overlap (scrolled a whole page).
check("pages without overlap", [c.name for c in merge_pages([row(r1, 0.3), row(r3, 0.3)])], r1 + r3)

# A single page.
check("one page", len(merge_pages([p1])), 10)

# The real failure: "+" read as "t", one name unreadable (its text read instead), last page read twice.
from stsbot.deckview import clean_name  # noqa: E402

check("Basht -> Bash+", clean_name("Basht"), "Bash+")
check("Shrug It Offt -> Shrug It Off+", clean_name("Shrug It Offt"), "Shrug It Off+")
check("text read as a name", clean_name("Until next turn, prevents"), "Unknown card")
check("a real name stays", clean_name("Ashen Strike"), "Ashen Strike")
check("capitals do not matter", clean_name("Shrug It offt"), "Shrug It Off+")
page1 = row(["Strike"] * 5, 0.3) + row(["Defend"] * 4 + ["Basht"], 0.65)
page2 = row(["Defend", "Defend", "Defend", "Until next turn, prevents", "Basht"], 0.3) +     row(["Shrug It Off+", "Ashen Strike", "Body Slam", "Until next turn, prevents"], 0.65)
page3 = row(["Shrug It Offt", "Ashen Strike", "Body Slam", "Until next turn,prevents"], 0.3)
got = [c.name for c in merge_pages([page1, page2, page3, page3], target=14)]
check("real deck view: 14 cards", len(got), 14)
check("real deck view: names", sorted(set(got)),
      sorted({"Strike", "Defend", "Bash+", "Shrug It Off+", "Ashen Strike", "Body Slam", "Unknown card"}))

print(f"test_deckview: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
