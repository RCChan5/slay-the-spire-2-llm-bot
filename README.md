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
   **Block first** (the user's rule, at any HP): each HP lost weighs 10 against 1 per point of damage dealt,
   so it blocks before attacking. A kill counts through the damage that enemy no longer deals, so it kills
   only when that saves at least as much HP as blocking would. Status cards that hurt at the end of the
   turn (Infection, Burn) count as coming damage. When two sets of block cards stop the same damage, the
   cheaper one is played (the most block per energy).
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

9. **Map** (`stsbot/mapread.py`, `stsbot/route.py`): room icons are found by matching the legend's own
   icons on the map (types: unknown, merchant, treasure, rest, enemy, elite); reachable rooms are the ones
   drawn dark, visited ones carry an ink ring, and paths are the dotted lines between rooms in neighboring
   rows. Every path through the visible map is simulated room by room (HP after each fight, Burning Blood,
   rest heals of 30%, gold) and scored:
   - fights cost HP according to the deck built so far (quality versus the starter deck, AoE, block,
     Strength and powers), each fight's chance of killing the run, and the lowest HP along the way;
   - elites are worth a guaranteed relic but cost about three hallway fights of HP; with an unimproved
     starter deck in the first floors they cost more (take two or three normal fights first);
   - rests heal when HP is under 55%, otherwise they are an upgrade;
   - shops count when gold covers a card removal and there are basics or a curse to cut.

   Ascension levels change the weights (A1 to A10 are cumulative): A3 less gold, A4 one fewer potion
   slot, A5 Ascender's Bane in the starting deck (tracked, and removal worth more), A6 removal costs 100,
   A7 fewer rares (relics worth more), A8 and A9 tougher and deadlier enemies (fights cost more, elites
   need a stronger deck), A10 two Act 3 bosses (HP matters more late in Act 3). The ascension number is
   read from the character badge on the top bar.

10. **Potions** (`stsbot/potions.py`): the belt is read from the top bar (three slots, two from A4) and
    each potion's tooltip gives its name and effect. Rule: **keep one slot open**. When every slot is full,
    the potion that helps most in this fight is used, so the next potion reward has room. In an emergency
    (the coming attacks would kill even after the best plays) whatever helps is used, full belt or not.
    Potions it cannot judge (for example ones that open a card choice) are never used automatically.

11. **Builds** (`stsbot/builds.py`): card picks know the Ironclad builds from Slay the Spire 2 guides
    (FinalBoss, PCGamesN, slay-the-spire-2.pages.dev), each with key cards, support cards and what it still
    needs:
    - Strength stacking: Demon Form, Limit Break, Inflame, Spot Weakness; Whirlwind, Twin Strike, Heavy Blade...
    - Vulnerable: Molten Fist, Tremble, Dismantle, Uppercut, Cruelty; Taunt, Colossus, Dominate (needs block)
    - Barricade / Body Slam: Barricade, Body Slam, Entrench, Juggernaut; Shrug It Off, Flame Barrier... (needs draw)
    - Exhaust: Corruption, Feel No Pain, Dark Embrace; True Grit, Burning Pact, Second Wind, Fiend Fire...
    - Self-damage / Rupture: Rupture, Inferno, Crimson Mantle; Bloodletting, Offering, Hemokinesis, Brand...
    - Strike: Perfected Strike, Hellraiser; Pommel Strike, Twin Strike, Ashen Strike...

    **Block cards** (the user's rule) are judged by block per energy, with Defend's 5 per energy as the
    baseline, plus 0.8 for each thing they do besides blocking (draw, damage, Vulnerable, Weak, energy,
    Strength), minus 0.4 per HP they cost. This is added on top of the tier, so Shrug It Off (8 block and
    a draw for 1) or Taunt (6 block and Vulnerable for 1) beat a plain 2-energy block card.
    Known cards start from the guides' tier (S 8, A 6.5, B 5, C 3.5, D 2.5, so D-tier cards such as Fight Me!
    are usually skipped); unknown cards are valued from their text and lean toward a build by keywords.
    Progress in a build is 3 per key card and 1 per support card. Once one build has 5 or more and leads the
    next by 2, the deck **commits**: its key cards are worth +4, support +2.5, other builds' key cards -1.5,
    and cards covering the build's needs +1.5. Before committing it leans toward the two leading builds. The
    build is shown on every card choice and map line. Your own ratings in `data/card_ratings.json` still win.

12. **New runs, Neow and events** (`stsbot/events.py`): from the main menu the bot continues a saved run, or
    starts a new one (Singleplayer, Standard, the Ironclad at the ascension selected in the game) and clicks
    through the game-over screen after a death (`--runs N` stops after N new runs). Neow's starting choice
    and every event (option boxes on the right: gold title over effect text) are read and scored the same
    way: upgrades, removals, relics, free items, gold, max HP, healing and card choices count for an option;
    curses and losing HP, max HP or gold count against it. One-button follow-up screens are clicked through.

13. **Campfires** (`stsbot/campfire.py`): rest when HP is under 55% of max, otherwise Smith. The upgrade
    screen shows the whole deck; the bot scrolls through it (and adds cards it had not tracked), then
    upgrades Bash first early, then key cards of the committed build, then the best non-basic card (block
    cards a little higher), Defend before Strike, never a card already upgraded, and confirms with the
    check mark.

14. **Deck sync** (`stsbot/deckview.py`): when the deck count on the top bar differs from the tracked deck
    (you picked or removed cards yourself, or an event did), the bot opens the deck view on the map, reads
    every card while scrolling, merges the overlapping rows and replaces the tracked deck if the count
    matches. Once per floor at most.

15. **Map drawings** (`stsbot/mapdraw.py`): put pictures in **`C:\stsbot\images`** (png, jpg, webp). At
    the start of each act's map the bot picks one at random (no repeats in a run until all are used) and
    draws it with right-button drags (the map draws on right-drag, so no room is chosen) as a plain outline
    (the subject is cut out of the background first). Pictures with "flag" in the file name also get the
    flag of Israel behind the person. About 35 seconds per picture. (A shaded, faster version was tried and
    looked worse in the game; it is off.)
    `python -m stsbot.mapdraw --preview images/x.jpg` shows the strokes; `python -m tools.drawtest` draws
    once on the open map; `--no-draw` turns drawings off. The images folder is not committed to git.

16. **Choosing from the hand** (`stsbot/handpick.py`): cards like Armaments (upgrade a card in hand) or
    True Grit and Burning Pact (exhaust or discard one) open a "choose a card" prompt mid-fight. Upgrade:
    Bash first if it is still to be played, then a card the plan still plays this turn (attacks, or block),
    never a curse, status or upgraded card. Discard or exhaust: curses and status cards first, then cards
    that cannot be paid for this turn, then Strike before Defend (block first), never a card the plan
    needs. The planner credits Armaments for its upgrade and values clearing a curse or status card from
    the hand (no more dead draws this fight). The first prompts are saved to `shots/` to check the layout.
17. **Card removal** (events, shops): curses first, then Strike, then Defend, then the weakest card,
    confirmed with the check mark.

18. **Treasure rooms**: after choosing a treasure on the map, the bot clicks the closed chest (the gold is
    added by itself), takes the relic on the "What's Inside?" screen, then clicks Proceed.

## Run

For now it uses Daivid's Python environment, which already has PaddleOCR on the GPU:

```
cd C:\stsbot
C:\SAS\.venv\Scripts\python -m stsbot                  # advise only: prints plays, never touches the game
C:\SAS\.venv\Scripts\python -m stsbot --play           # plays combat itself
C:\SAS\.venv\Scripts\python -m stsbot --play --turns 3 # stops after 3 turns
```

Moving the mouse or switching away from the game **pauses** play mode; it resumes once the game is in front
and the mouse has been still for 5 seconds (`--still 8` to change, `--no-resume` to stop for good instead).
Ctrl+C quits. Only one bot can run at a time; `python -m tools.stop` stops any that are running.
Daivid's gaming mode pauses Daivid while the game is in front; that is expected.

Every decision is logged to `logs/YYYYMMDD.jsonl` (state, plan, score, card texts read).

## Tests

```
C:\SAS\.venv\Scripts\python -m tests.test_planner   # made-up states, no game needed
C:\SAS\.venv\Scripts\python -m tests.test_draft     # card reward choices, no game needed
C:\SAS\.venv\Scripts\python -m tests.test_route     # route choices (made-up maps + saved map shots)
C:\SAS\.venv\Scripts\python -m tests.test_potions   # potion rules
C:\SAS\.venv\Scripts\python -m tests.test_builds    # build-aware card picks
C:\SAS\.venv\Scripts\python -m tests.test_deckview  # deck view page merging
C:\SAS\.venv\Scripts\python -m tests.test_mapdraw   # map drawing helpers
C:\SAS\.venv\Scripts\python -m tests.test_handpick  # choosing cards from the hand
C:\SAS\.venv\Scripts\python -m tests.test_screen    # saved screenshots in shots/ (skipped if missing)
```

Calibration tools: `python -m tools.snap name` saves a screenshot, `python -m tools.ocrdump shots/x.png`
prints every OCR line with its position, `python -m tools.poke click 0.5 0.5 name` clicks then saves.

## Status

- Done: combat (single and several enemies, intents, enemy block, statuses), Loot, card choices with
  skipping, Proceed buttons. Played live: three fights won, Pommel Strike, Fight Me! and Battle Trance
  picked. A card the game sends back (a missed drop) is retried at other drop points, then left out for
  the turn, so a turn can never loop.
- Map routing done (read checked on four saved maps and the live map; the first live click was stopped
  because the game was not the window in front).
- Next: shops (the route already plans removals), rest sites (heal or upgrade), events (local Qwen3-VL
  for choices that need judgment), card upgrade and removal screens, potions.
