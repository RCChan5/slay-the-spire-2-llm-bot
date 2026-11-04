"""Run the deck sync once: open the deck view, read every card, fix the tracked deck if the count matches.

    python -m tools.syncdeck
"""

import time

from stsbot.bot import Bot
from stsbot.run import read_top_bar
from stsbot.window import find_game, user32


def main():
    b = Bot(play=True)
    b.win = find_game()
    user32.SetForegroundWindow(b.win.hwnd)
    time.sleep(0.3)
    b.move(0.5, 0.3)
    img = b.frame()
    lines, W, H = b.read(img)
    count = read_top_bar(lines, W, H).deck_count
    print("deck count on screen:", count, "| tracked:", len(b.state.deck.cards))
    ok = b.sync_deck(count)
    print("synced" if ok else "not synced", "| tracked now:", len(b.state.deck.cards))


if __name__ == "__main__":
    main()
