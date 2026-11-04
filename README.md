# stsbot

A Slay the Spire 2 bot that reads the game from screen pixels with local OCR and plays through Windows
mouse input. Nothing is read from, injected into, or changed in the game's files or process.

## How it works

1. **Window** (`stsbot/window.py`): finds `SlayTheSpire2.exe`'s window and grabs its client area.
2. **OCR** (`stsbot/ocr.py`): PaddleOCR PP-OCRv5 on the GPU, about 0.6 s for a full 1440p frame.
3. **Screen** (`stsbot/screen.py`): which screen it is (combat, map, menu, reward), and for combat: HP,
   block, energy, turn, each card's name, cost and position, each enemy's HP and intent number.
   Positions are fractions of the window, so any 16:9 size works.
4. **Cards** (`stsbot/cards.py`): in play mode each card is hovered once per turn and its live text read
   (Strength and upgrades already counted), then parsed: damage, hits, ALL enemies, block, Vulnerable,
   Weak, Strength, draw, energy, Exhaust, Unplayable. Cards it does not understand are left out.
5. **Planner** (`stsbot/planner.py`): tries every order of playable cards and targets, simulates damage
   (x1.5 on Vulnerable), block against the shown intents (x0.75 when Weak), and scores the result.
6. **Bot** (`stsbot/bot.py`): plays the first card of the best plan by dragging it onto its target,
   reads the screen again, re-plans, and clicks End Turn when nothing is worth playing.
7. **Intents and statuses**: small numbers are read again at 2x to 3x zoom. In play mode each intent is
   hovered and counts as damage only if its tooltip says Attack (advise mode checks for a red icon
   instead). Status icons (`stsbot/status.py`) are hovered once to learn their name from the tooltip and
   saved to `data/status_icons/`; after that they are recognized from the picture. Enemy block and
   Vulnerable are used in the simulation.
8. **Rewards** (`stsbot/draft.py`, `stsbot/run.py`): the Loot screen is taken top to bottom. On a card
   choice each card's text is read and valued: per-energy damage and block, draw, energy, debuffs,
   Strength and powers, AoE, synergy with what the deck is building toward (Strength, Exhaust, Block,
   Vulnerable, self damage, Strike, draw), and what the deck lacks (early damage, a first AoE), minus
   copies already owned. **It skips** unless the best card beats the deck's average by a margin that
   grows with deck size (0.5 at 10 cards, 2.5 at 30), because every added card makes the good ones come
   up less often. Screens with no Skip (some events) take the best card. The deck is tracked in
   `data/run.json` from the starter deck and checked against the deck count on screen.
   Put your own ratings in `data/card_ratings.json` (`{"Card Name": 8.5}`, same scale; basics are about
   3) to override cards it misjudges.

## Run

For now it uses Daivid's Python environment, which already has PaddleOCR on the GPU:

```
cd C:\stsbot
C:\SAS\.venv\Scripts\python -m stsbot                  # advise only: prints plays, never touches the game
C:\SAS\.venv\Scripts\python -m stsbot --play           # plays combat itself
C:\SAS\.venv\Scripts\python -m stsbot --play --turns 3 # stops after 3 turns
```

Play mode stops by itself when you move the mouse, when the game is not the window in front, or on Ctrl+C.
Daivid's gaming mode pauses Daivid while the game is in front; that is expected.

Every decision is logged to `logs/YYYYMMDD.jsonl` (state, plan, score, card texts read).

## Tests

```
C:\SAS\.venv\Scripts\python -m tests.test_planner   # made-up states, no game needed
C:\SAS\.venv\Scripts\python -m tests.test_draft     # card reward choices, no game needed
C:\SAS\.venv\Scripts\python -m tests.test_screen    # saved screenshots in shots/ (skipped if missing)
```

Calibration tools: `python -m tools.snap name` saves a screenshot, `python -m tools.ocrdump shots/x.png`
prints every OCR line with its position, `python -m tools.poke click 0.5 0.5 name` clicks then saves.

## Status

- Done: combat (single and several enemies, intents, enemy block, statuses), Loot, card choices with
  skipping, Proceed buttons. Played live: three fights won, Pommel Strike, Fight Me! and Battle Trance
  picked. A card the game sends back (a missed drop) is retried at other drop points, then left out for
  the turn, so a turn can never loop.
- Next: map routes (node icons from the legend), events (local Qwen3-VL for choices that need judgment),
  rest sites, shops, card upgrade and removal screens, potions.
