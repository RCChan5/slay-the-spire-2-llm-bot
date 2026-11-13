# Slay the Spire 2 LLM bot

A bot that plays Slay the Spire 2 the way a person does: it **reads the screen** with local OCR and **plays
with the mouse**. Nothing is read from, injected into, or changed in the game's files or process. Every
decision runs on your own PC: a combat simulator, card and route rules, and a **local LLM** (Ollama) that
reads guides you write and has the final say.

Highlights:

- **Fights:** reads hand, energy, HP, block, enemy intents and statuses; a depth-first simulator ranks play
  orders (block first, kills when they save more HP); the local LLM plans the whole turn from real card
  text and the simulator's options, and is asked again only when a card is drawn.
- **Card picks with a build:** the LLM commits to an Ironclad build (Exhaust, Self-damage, Strength,
  Barricade) by floor 6 and skips cards that do not serve it.
- **Act route planning:** at each new act it scrolls the whole map, lists every route with the facts a
  pathing guide cares about (elites, campfire before the first elite, easy and hard hallway fights, shops,
  events, pivots), lets the LLM pick from the best five, **draws the route in red** with the map pen and
  walks it, re-planning at forks when things change.
- **Learns from every run:** after a death or a win the LLM reviews the run's log and keeps a short list of
  rules that go into its future prompts.
- **Everything else a run needs:** rewards, campfires, upgrades and removals, potions (one slot kept free),
  events, treasure, Neow, new runs, and pausing whenever you touch the mouse.
- **Dashboard** (local page): run status, settings, the LLM's answers streaming in, what it learned, and a
  button to draw a picture from a folder on the map.

## Setup

Windows, Python 3.12, an NVIDIA GPU (PaddleOCR GPU), and [Ollama](https://ollama.com) with
`qwen3-vl:8b-instruct` (any fast JSON-capable model works; set `MODEL` in `stsbot/llm.py`). The game runs in
a 16:9 window (measured at 2560x1440).

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
# then paddlepaddle-gpu for your CUDA version from PaddlePaddle's index
ollama pull qwen3-vl:8b-instruct
```

The launchers use `.venv` in this folder (or the `STSBOT_PYTHON` environment variable, else `python`).

### The `context` folder (your own data, not included)

The LLM reads game knowledge and strategy from `context/`, which you supply (game data and guides are not
published here). Without it the bot still plays with its built-in rules. Files it reads:

| File | Contents |
|---|---|
| `sts2_cards.json` | `{"cards": [{"id", "name", "character", "type", "rarity", "cost", "cost_upgraded", "text", "text_upgraded"}]}` |
| `sts2_card_tiers.json` | `{"by_id": {"<card id>": "S" \| "A" \| ... \| "F"}}` |
| `sts2_monsters.json` | `{"monsters": [{"name", "type", "hp", "moves": [...], "powers": [...]}]}` |
| `sts2_relics.json` | `{"relics": [{"name", "text"}]}` |
| `ironclad_play_guide.md` | Markdown with `## Build types at a glance`, `## Build 1:` to `## Build 4:`, `## Rules for the bot` |
| `map_pathing_guide.md` | Markdown with numbered sections: `## 1.` core idea, `## 3.` fight types, `## 4.`/`## 7.`/`## 8.` Acts 1 to 3, `## 5.` shops, `## 6.` pivots, `## 11.` decision rules |

The bot writes `what_i_learned.md` and `learned_rules.md` there itself after each run.

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
    draws it with right-button drags (the map draws on right-drag, so no room is chosen), about a minute
    per picture. The subject is cut out with the U-2-Net background-removal model (`models/u2net.onnx`,
    176 MB, from the rembg project's releases; GrabCut is used if the file is missing); its outline is
    drawn first (leaving out where it runs off the photo), then the inner details (face, tie, hands) from
    edges found after smoothing away texture, with thresholds from the picture's own contrast. When the
    cut-out is small the whole picture is traced. Pictures with "flag" in the file name also get the flag
    of Israel behind the person. Strokes go most important first (outline, flag, then inner lines longest
    first), at most 100, with a short pause between them: in multiplayer the game stopped taking strokes
    partway once, and whatever is lost should be minor detail. `python -m stsbot.mapdraw --preview images/x.jpg` shows the strokes;
    the dashboard has Draw now buttons; `--no-draw` turns drawings off. images/ and models/ are not
    committed to git.
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

19. **Dashboard** (`stsbot/dashboard.py`, double-click `StsBot Dashboard.cmd`): a page on this PC only
    (http://localhost:8765) with the run (HP, floor, ascension, gold, deck, build), the bot's latest log,
    Start and Stop, the settings it starts with (draw on each act's map, seconds of still mouse before
    resuming, number of new runs), and the images folder with Draw now on each picture and Draw random.
    Drawing stops a running bot, opens the map if needed, draws, closes the map, and starts the bot again.
    **LLM thinking** shows each question the LLM is asked as it answers: the answer streams in live, then
    the plan or pick and its reason, with "What it was told" (the full prompt) folded away; the last 15
    calls stay listed. The bot writes these to two small files in data/ at most every 0.3 s, so watching
    costs the game nothing (measured: a fight decision still takes about 1.1 s).

20. **LLM decisions** (`stsbot/brain.py`, `stsbot/llm.py`, `stsbot/context.py`): a local model in Ollama
    (`qwen3-vl:8b-instruct`, the user's choice of a fast 8B model; answers in well under a second once
    loaded) makes the fight and card-pick decisions, with the final say. It reads the user's game knowledge
    in `context/`: all cards, relics and monsters, the card tier list, and the Ironclad play guide (with its
    "Rules for the bot"). Only the entries each decision needs go into the prompt.
    - Fights: after every play the hand is read again and the LLM gets HP, block, energy, the whole hand
      with real card text and tiers, each enemy's intent, statuses and known moves (enemy names are read
      by hovering each enemy once per fight), and the simulator's best orders with predicted damage taken
      and dealt. Its rules: avoid HP loss when attacks come, spend all energy and cards unless harmful,
      Powers and draw first, Vulnerable before attacks. An illegal answer (card not in hand, too
      expensive) is asked again; after two, or if Ollama does not answer, the simulator plays.
      The LLM plans the whole turn at once and the bot follows that order card by card without asking
      again. Only when a card is drawn (the hand has a card the last hand did not) is it asked again,
      told which cards are new; card text is read by hovering only cards not yet read this turn.
    - Card picks: it leans toward a build early, commits by floor 4-6 using the guide's build rules
      (saved with the run, it then sticks), and skips off-build cards, watching the deck's counts of
      damage, block, AoE, draw and scaling to fill real gaps.
    - `--no-llm` (or the dashboard switch) uses the built-in rules instead. The built-in card values now
      use the tier list in `context/` too.
21. **Speed** (measured in a 4-player fight: about 13 s per card, the LLM about 1 s of it). The bot now
    reuses what it already knows: the read taken right after a card play starts the next decision (no second
    full read); enemy intents and status numbers are read again only when an enemy's HP or block changed or
    a card that could debuff them was played; an intent tooltip is hovered once per number per turn; a status
    icon whose tooltip gives no name (a teammate's power) is not hovered again that fight; card text is kept
    across turns while the player's statuses are the same. Hovers wait until the card or tooltip has
    appeared and stopped moving instead of a fixed pause. Every card play logs `time: read, details, think,
    play` so the gain can be checked. Shrinking the screen before reading was measured and left out: it
    saves 0.1 s but loses card costs, block and intent numbers.
22. **Learning from each run** (`stsbot/review.py`): when a run ends (death or win) the bot turns the run's
    log into a short story (each fight with its enemies, HP lost each enemy turn against what the plan
    predicted, the death, card picks and skips with reasons, the build, campfires, events) and the local LLM
    reviews it: what happened, mistakes, what worked, lessons. They are added to
    `context/what_i_learned.md`, and a second call keeps the top 10 rules in `context/learned_rules.md`,
    which go into every fight and card-pick prompt. Lessons and rules must fit the play guide's strategy
    (commit to a build, skip what does not serve it). It takes about 5 to 10 seconds, once per run (a restart
    on the game-over screen does not review again). `python -m stsbot.review` reviews the last run by hand;
    `--story` only prints the story. The dashboard shows the rules and the latest review. Both files are
    written by the bot and kept out of git; edit or delete them freely.
23. **Act route planning** (`stsbot/mapfull.py`, `stsbot/pathplan.py`, `context/map_pathing_guide.md`): on a
    fresh act map the bot scrolls through the whole map (about 3 screens; 3 wheel notches move it 0.222 of
    the window, checked on every step) and joins the screens into one graph of rooms and paths. Every route
    from the start to the boss is listed with the guide's facts (elites, a campfire before the first elite,
    easy and hard hallway fights, events, shops by timing and gold, treasure, pivots, hard stretches with no
    campfire) and scored by the guide's decision rules; the local LLM picks from the best 5 with the guide's
    sections for that act. The route is drawn in red with the map pen (right-drag; the pen is red in single
    player; the broom clears old drawings first, pictures included) and walked room by room. It is planned
    again at a fork after an elite, when HP falls below half, when gold crosses the shop plan, or when the
    next planned room is not reachable. `python -m tools.routetest` tries it on the open map without playing
    (`--no-llm`, `--no-draw`). Reading the map takes about 15 to 25 seconds, the LLM pick about 1 to 4.
    **Mapping modes** (dashboard section "Mapping", or `--mapping`): `plan` (the above), `random` (one
    random route from start to boss, kept for the act), `teammates` (multiplayer: follow the room a
    teammate votes for, spotted as a new colourful mark beside a reachable room; the guide plan if no vote
    shows within 15 s; screens are saved to `shots/teammates_*.png` to tune the detector), `off` (the old
    room-by-room choice). "Draw the planned route in red" can be switched off (`--no-route-line`).

## Run

Easiest: double-click `Start StsBot.cmd`. It stops any copy already running, starts the dashboard (if it is
not up) and opens it in the browser, checks Ollama, and runs
the bot in that window with the dashboard's saved settings (close the window or press Ctrl+C to stop).

From the command line:

```
.venv\Scripts\python -m stsbot                  # advise only: prints plays, never touches the game
.venv\Scripts\python -m stsbot --play           # plays itself
.venv\Scripts\python -m stsbot --play --turns 3 # stops after 3 turns
```

Moving the mouse or switching away from the game **pauses** play mode; it resumes once the game is in front
and the mouse has been still for 5 seconds (`--still 8` to change, `--no-resume` to stop for good instead).
Ctrl+C quits. Only one bot can run at a time; `python -m tools.stop` stops any that are running.

Every decision is logged to `logs/YYYYMMDD.jsonl` (state, plan, score, card texts read).

## Tests

```
.venv\Scripts\python -m tests.test_planner   # made-up states, no game needed
.venv\Scripts\python -m tests.test_draft     # card reward choices, no game needed
.venv\Scripts\python -m tests.test_route     # route choices (made-up maps + saved map shots)
.venv\Scripts\python -m tests.test_potions   # potion rules
.venv\Scripts\python -m tests.test_builds    # build-aware card picks
.venv\Scripts\python -m tests.test_deckview  # deck view page merging
.venv\Scripts\python -m tests.test_mapdraw   # map drawing helpers
.venv\Scripts\python -m tests.test_handpick  # choosing cards from the hand
.venv\Scripts\python -m tests.test_pathplan  # act route planning on a made-up map
.venv\Scripts\python -m tests.test_review    # run review (stand-in model); --live for the real one
.venv\Scripts\python -m tests.test_speed     # hover wait, unnamed icons
.venv\Scripts\python -m tests.test_brain     # the LLM layer (stand-in model); add --live for the real one
.venv\Scripts\python -m tests.test_screen    # saved screenshots in shots/ (skipped if missing)
```

Calibration tools: `python -m tools.snap name` saves a screenshot, `python -m tools.ocrdump shots/x.png`
prints every OCR line with its position, `python -m tools.poke click 0.5 0.5 name` clicks then saves.

## Status

Plays full Ironclad runs unattended in single player (multiplayer works too, waiting while teammates act).
Measured: about 2 to 3 seconds per card once a turn is planned, 6 to 8 seconds for a turn's first card,
about 1 second per LLM answer on an RTX 5080. Known gaps: enemy powers such as Slippery are not simulated,
and the 8B model's stated reasons are sometimes wrong even when its move is reasonable.

## License

MIT (see `LICENSE`). Slay the Spire 2 is a game by Mega Crit; this project is not affiliated with it.
