"""iRacing live timing backend.
Run on the same Windows PC as iRacing:  python server.py
Then open http://localhost:8080 in a browser.
"""
import bisect, json, math, os, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import irsdk

PORT = 8080
# When packaged as an .exe, bundled files live in sys._MEIPASS
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ir = irsdk.IRSDK()
state = {"connected": False}
cars = {}
fuel = {"lap": None, "level": None, "burns": []}
session_key = None
trk = [None] * 200  # my car's lat/lon by lap position, used to draw the track
NSEC = 3


def new_car():
    return {"times": {}, "lastkey": None, "sec": None, "sectime": 0.0, "dirty": False,
            "secs": [None] * NSEC, "bests": [None] * NSEC, "inpit": None,
            "pitin": 0.0, "pits": 0, "lastpit": None, "stint0": 0,
            "drv": {}, "cur": None, "curstart": 0.0, "tprev": None,
            "grid": None, "hist": [], "histlap": None, "ahead": None, "best": None}


def gap(a, b, race):
    """Seconds car a is behind car b (or '+N LAP')."""
    ca, cb = cars[a], cars[b]
    if not race:  # practice/quali: difference in best lap
        if ca["best"] and cb["best"]:
            return round(ca["best"] - cb["best"], 3)
        return None
    ka, kb = ca["lastkey"], cb["lastkey"]
    if ka is None or kb is None:
        return None
    behind = kb - ka
    if behind >= 100:
        return "+%d LAP%s" % (behind // 100, "S" if behind >= 200 else "")
    ta, tb = ca["times"].get(ka), cb["times"].get(ka)
    if ta is None or tb is None:
        return None
    return round(max(ta - tb, 0.0), 3)


def track_shape():
    """Return the track outline (metres) once my car has driven a full lap, else None."""
    if sum(p is not None for p in trk) < 190:
        return None
    pts, prev = [], next(p for p in trk if p)
    for p in trk:
        prev = p or prev
        pts.append(prev)
    la0, lo0 = pts[0]
    k = math.cos(math.radians(la0))
    return [[round((lo - lo0) * 111000 * k, 1), round((la - la0) * 111000, 1)] for la, lo in pts]


def tick():
    global session_key, NSEC, cars
    ir.freeze_var_buffer_latest()
    key = (ir["WeekendInfo"]["SubSessionID"], ir["SessionNum"])
    sectors = (ir["SplitTimeInfo"] or {}).get("Sectors") or [{"SectorStartPct": 0}]
    starts = [s["SectorStartPct"] for s in sectors]
    if key != session_key:
        session_key, cars = key, {}
        NSEC = len(starts)
        fuel.update(lap=None, level=None, burns=[])
        trk[:] = [None] * 200

    t = ir["SessionTime"]
    sess = ir["SessionInfo"]["Sessions"][ir["SessionNum"]]
    race = sess["SessionType"] == "Race"
    drivers = {d["CarIdx"]: d for d in ir["DriverInfo"]["Drivers"]
               if not d.get("CarIsPaceCar") and not d.get("IsSpectator")}
    pct, lapc = ir["CarIdxLapDistPct"], ir["CarIdxLapCompleted"]
    pos, cpos = ir["CarIdxPosition"], ir["CarIdxClassPosition"]
    onpit, last, best = ir["CarIdxOnPitRoad"], ir["CarIdxLastLapTime"], ir["CarIdxBestLapTime"]

    active = []
    for i in drivers:
        if pct[i] < 0:
            continue
        c = cars.setdefault(i, new_car())
        k = int((max(lapc[i], 0) + pct[i]) * 100)
        if c["lastkey"] is None or k - c["lastkey"] > 100 or k < c["lastkey"] - 50:
            c["lastkey"] = k - 1  # first sight or teleport: restart the log
        if k > c["lastkey"]:
            for j in range(c["lastkey"] + 1, k + 1):
                c["times"][j] = t
                c["times"].pop(j - 300, None)
            c["lastkey"] = k
        # sectors
        s = max(bisect.bisect_right(starts, pct[i]) - 1, 0)
        if onpit[i]:
            c["dirty"] = True
        if c["sec"] is None:
            c["sec"], c["sectime"] = s, t
        elif s != c["sec"]:
            if s == (c["sec"] + 1) % len(starts) and not c["dirty"] and c["sec"] < NSEC:
                d = t - c["sectime"]
                c["secs"][c["sec"]] = d
                b = c["bests"][c["sec"]]
                c["bests"][c["sec"]] = d if b is None else min(b, d)
            c["sec"], c["sectime"], c["dirty"] = s, t, bool(onpit[i])
        # pit stops
        if c["inpit"] is not None and onpit[i] and not c["inpit"]:
            c["pitin"], c["pits"] = t, c["pits"] + 1
        if c["inpit"] and not onpit[i]:
            c["lastpit"], c["stint0"] = t - c["pitin"], lapc[i]
        c["inpit"] = bool(onpit[i])
        c["best"] = best[i] if best[i] > 0 else None
        name = drivers[i]["UserName"]  # team events: driver swaps change this name
        if c["cur"] != name:
            c["cur"], c["curstart"] = name, t
            c["drv"].setdefault(name, 0.0)
        if c["tprev"] is not None and 0 < t - c["tprev"] < 5:
            c["drv"][name] += t - c["tprev"]
        c["tprev"] = t
        if c["grid"] is None and race and pos[i] > 0:
            c["grid"] = pos[i]  # first race position we saw = grid slot
        active.append(i)

    if any(pos[i] > 0 for i in active):
        order = sorted(active, key=lambda i: (pos[i] if pos[i] > 0 else 999, -cars[i]["lastkey"]))
    else:
        order = sorted(active, key=lambda i: -cars[i]["lastkey"])
    if not race:
        order = sorted(active, key=lambda i: cars[i]["best"] or 1e9)

    # own-car fuel estimate
    me = ir["PlayerCarIdx"]
    lvl = ir["FuelLevel"]
    mylap = lapc[me]
    lat, lon = ir["Lat"], ir["Lon"]
    if lat is not None and lon is not None and pct[me] >= 0:
        trk[min(int(pct[me] * 200), 199)] = (lat, lon)
    if fuel["lap"] is not None and mylap > fuel["lap"] and not onpit[me]:
        burn = fuel["level"] - lvl
        if burn > 0:
            fuel["burns"] = (fuel["burns"] + [burn])[-5:]
    if fuel["lap"] is None or mylap != fuel["lap"]:
        fuel["lap"], fuel["level"] = mylap, lvl
    avg = sum(fuel["burns"]) / len(fuel["burns"]) if fuel["burns"] else None

    cap = (ir["DriverInfo"] or {}).get("DriverCarFuelMaxLtr")
    slr, trem = ir["SessionLapsRemain"], ir["SessionTimeRemain"]
    mylast = last[me] if last[me] > 0 else None
    if slr is not None and 0 <= slr < 32000:
        laps_left = slr
    elif trem is not None and trem < 600000 and mylast:
        laps_left = trem / mylast + 1
    else:
        laps_left = None
    plan = None
    if avg and laps_left:
        add = max(laps_left * avg + avg - lvl, 0.0)  # includes a one-lap safety margin
        plan = {"lapsLeft": round(laps_left, 1), "add": add, "pitBy": mylap + int(lvl / avg),
                "stops": math.ceil(add / cap) if cap else None}
    rows = []
    for n, i in enumerate(order):
        c, d = cars[i], drivers[i]
        g = gap(i, order[0], race) if n > 0 else None
        it = gap(i, order[n - 1], race) if n > 0 else None
        ahead = order[n - 1] if n > 0 else None
        if ahead != c["ahead"]:  # new car ahead: restart the gap trend
            c["ahead"], c["hist"], c["histlap"] = ahead, [], None
        if race and lapc[i] != c["histlap"]:
            c["histlap"] = lapc[i]
            if isinstance(it, float):
                c["hist"] = (c["hist"] + [it])[-8:]
        rows.append({
            "drv": [[k, round(v)] for k, v in c["drv"].items()], "cur": c["cur"],
            "drvStint": round(t - c["curstart"]), "grid": c["grid"], "hist": c["hist"], "pct": pct[i],
            "idx": i, "pos": n + 1, "cpos": cpos[i], "num": d["CarNumber"], "name": d["UserName"],
            "cls": d.get("CarClassShortName") or "", "car": d.get("CarScreenNameShort", ""),
            "lap": lapc[i], "me": i == me,
            "gap": g,
            "int": it,
            "last": last[i] if last[i] > 0 else None, "best": c["best"],
            "secs": c["secs"], "bests": c["bests"], "pits": c["pits"],
            "pit": c["lastpit"], "inpit": c["inpit"], "stint": lapc[i] - c["stint0"],
        })
    pit_times = sorted(c["lastpit"] for c in cars.values() if c["lastpit"])
    pit_loss = pit_times[len(pit_times) // 2] if pit_times else 35.0
    fastest = min((r for r in rows if r["best"]), key=lambda r: r["best"], default=None)
    flags = ir["SessionFlags"]
    flag = ("CHECKERED" if flags & 0x1 else "RED" if flags & 0x10 else
            "CAUTION" if flags & (0x8 | 0x4000 | 0x8000) else "GREEN" if flags & 0x4 else "")
    tl = ir["SessionTimeRemain"]
    laps_total = sess.get("SessionLaps")
    state.clear()
    state.update({
        "connected": True, "session": sess["SessionType"], "race": race,
        "lapsTotal": int(laps_total) if str(laps_total).isdigit() else None,
        "leaderLap": (lapc[order[0]] + 1) if order else 0,
        "timeRemain": tl if tl is not None and tl < 600000 else None,
        "flag": flag, "track": ir["WeekendInfo"]["TrackDisplayName"],
        "fastest": {"time": fastest["best"], "num": fastest["num"], "name": fastest["name"]} if fastest else None,
        "me": {"idx": me, "fuel": lvl, "burn": avg, "fuelLaps": lvl / avg if avg else None, "cap": cap, "plan": plan},
        "nsec": NSEC, "cars": rows, "pitLoss": pit_loss, "trk": track_shape(), "starts": starts,
    })


def poll():
    while True:
        try:
            if not (ir.is_initialized and ir.is_connected):
                ir.shutdown()
                state.clear(); state["connected"] = False
                if not ir.startup():
                    time.sleep(1)
                    continue
            tick()
        except Exception as e:  # keep running, show the problem in the page
            state.clear(); state.update({"connected": False, "error": repr(e)})
        time.sleep(0.1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/data"):
            body, ctype = json.dumps(state).encode(), "application/json"
        else:
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body, ctype = f.read(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=poll, daemon=True).start()
    print("Live timing running. Open http://localhost:%d" % PORT)
    webbrowser.open("http://localhost:%d" % PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
