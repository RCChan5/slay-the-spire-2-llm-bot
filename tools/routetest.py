"""Try the act route planning on the map screen without playing (the map must be open in the game).

Reads the whole map by scrolling, lists the best routes by the map guide's rules, lets the local LLM
pick one, and draws it in red. Nothing else is clicked. Old drawings on the map are cleared first.

    python -m tools.routetest            # LLM picks
    python -m tools.routetest --no-llm   # rules only
    python -m tools.routetest --no-draw  # plan only
"""

import sys
import time

from stsbot import inputs, llm, mapfull, pathplan as pp
from stsbot.builds import deck_builds
from stsbot.route import deck_power
from stsbot.run import Run
from stsbot.window import find_game, grab, user32

win = find_game()
if win is None:
    sys.exit("Slay the Spire 2 is not running.")
user32.SetForegroundWindow(win.hwnd)
time.sleep(0.3)
s = Run.load()
p = deck_power(s.deck, s.floor)
st = pp.State(s.act, s.hp or 80, s.max_hp or 80, s.gold, p.quality >= 0.8 or (p.aoe and p.scaling >= 1))
t = time.time()
frames, offs = mapfull.capture(win, inputs, grab)
fm = mapfull.build(frames, offs)
print(f"whole map: {len(fm.rooms)} rooms in {len(fm.rows)} rows ({time.time() - t:.0f}s)")
if not fm.rows:
    sys.exit("no rooms read: is the map open?")
nodes = [pp.Node(r.kind, next(k for k, row in enumerate(fm.rows) if i in row), r.x, list(r.up))
         for i, r in enumerate(fm.rooms)]
visited = [i for i, r in enumerate(fm.rooms) if r.visited]
starts = list(fm.rooms[min(visited, key=lambda i: fm.rooms[i].y)].up) if visited else list(fm.rows[0])
routes = pp.top_routes(nodes, starts, st)
print(f"{len(pp.routes_from(nodes, starts))} routes; best 5 by the guide's rules:")
for k, r in enumerate(routes, 1):
    print(f"{k}. [{r.score}] {r.summary()}")
pick = (pp.RoutePick(routes[0], "rules only", "rules") if "--no-llm" in sys.argv
        else pp.pick_route(routes, st, deck_builds(s.deck.cards).describe()))
print(f"pick ({pick.source}, {llm.last['seconds']:.1f}s): route {routes.index(pick.route) + 1}: {pick.reason}")
if "--no-draw" not in sys.argv:
    start = (fm.rooms[visited[0]].x, fm.rooms[visited[0]].y) if visited else None
    n = mapfull.draw_route(win, inputs, fm, pick.route.nodes, start=start)
    print(f"drew {n} segments in red")
