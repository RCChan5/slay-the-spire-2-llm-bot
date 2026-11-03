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
C:\SAS\.venv\Scripts\python -m tests.test_screen    # saved screenshots in shots/ (skipped if missing)
```

Calibration tools: `python -m tools.snap name` saves a screenshot, `python -m tools.ocrdump shots/x.png`
prints every OCR line with its position, `python -m tools.poke click 0.5 0.5 name` clicks then saves.

## Status

- Done: combat turns for single and multiple enemies, starter Ironclad deck checked live (2 turns played).
- Next: read enemy and player statuses (Vulnerable, Weak, Strength icons under the health bars), intent
  tooltips for multi-hit and non-attack intents, card choice screens (reward, upgrade, remove), map routes,
  events and shops (the local Qwen3-VL model for choices that need judgment), potions.
