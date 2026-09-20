#!/usr/bin/env python3
"""Tea Time companion (optional, for testing and debugging).

Players do NOT need this: the Mumble plugin reads the log itself. This script
does the same job on its own, printing the events the addon writes and keeping
a small JSON state file of who is sitting where. The bot can read that file
(--state) to move you around without the Mumble plugin installed.

Usage:
    python teatime_companion.py
    python teatime_companion.py --log "D:\\path\\to\\Logs\\General.log"
    python teatime_companion.py --from-start      # also process old lines
"""
import argparse
import json
import os
import re
import sys
import time

DEFAULT_LOG = r"C:\Program Files (x86)\World of Warcraft\_classic_beta_\Logs\General.log"
TIMEOUT = 90  # seconds without a BEAT before a player is dropped

# TEATIME_E v2 <KIND> <map> <instance> <x> <y> <facing> <name, may contain spaces>
LINE = re.compile(
    r"TEATIME_E v2 (\w+) (\S+) (\S+) (\S+) (\S+) (\S+) (.+?)\s*$"
)


def num(s):
    if s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse(line):
    m = LINE.search(line)
    if not m:
        return None
    kind, map_id, inst, x, y, facing, name = m.groups()
    return {
        "kind": kind,
        "name": name,
        "map": None if map_id == "-" else int(map_id),
        "instance": None if inst == "-" else inst,
        "x": num(x),
        "y": num(y),
        "facing": num(facing),
    }


class State:
    def __init__(self, path):
        self.path = path
        self.players = {}

    def write(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"updated": time.time(), "players": self.players}, f, indent=2)
        os.replace(tmp, self.path)

    def apply(self, ev):
        name = ev["name"]
        if ev["kind"] == "LEAVE":
            if self.players.pop(name, None) is not None:
                print(f"[leave] {name}")
                self.write()
            return
        is_new = name not in self.players
        self.players[name] = {
            "map": ev["map"],
            "instance": ev["instance"],
            "x": ev["x"],
            "y": ev["y"],
            "facing": ev["facing"],
            "seen": time.time(),
        }
        tag = "join" if is_new else ev["kind"].lower()
        print(f"[{tag}] {name} map={ev['map']} x={ev['x']} y={ev['y']} facing={ev['facing']}")
        self.write()

    def expire(self):
        now = time.time()
        gone = [n for n, p in self.players.items() if now - p["seen"] > TIMEOUT]
        for n in gone:
            del self.players[n]
            print(f"[timeout] {n}")
        if gone:
            self.write()


def tail(path, from_start, state):
    pos = None
    buf = b""
    f = None
    last_expire = time.time()
    while True:
        try:
            if f is None:
                f = open(path, "rb")
                if pos is None and not from_start:
                    f.seek(0, os.SEEK_END)
                else:
                    f.seek(pos or 0)
                pos = f.tell()
                print(f"watching {path}")
            size = os.path.getsize(path)
            if size < pos:  # file was replaced or truncated: start over
                f.close()
                f, pos, buf = None, 0, b""
                continue
            chunk = f.read()
            if chunk:
                pos = f.tell()
                buf += chunk
                # The game flushes in ~50 KB steps, which can cut a line in
                # half, so only complete lines are handled.
                *lines, buf = buf.split(b"\n")
                for raw in lines:
                    if b"TEATIME_E " not in raw:
                        continue
                    ev = parse(raw.decode("utf-8", errors="replace"))
                    if ev:
                        state.apply(ev)
            else:
                time.sleep(0.05)
        except FileNotFoundError:
            f, pos = None, 0
            time.sleep(1)
        if time.time() - last_expire > 1:
            state.expire()
            last_expire = time.time()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--state", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "teatime_state.json"))
    ap.add_argument("--from-start", action="store_true")
    args = ap.parse_args()
    try:
        tail(args.log, args.from_start, State(args.state))
    except KeyboardInterrupt:
        print("bye")
        sys.exit(0)


if __name__ == "__main__":
    main()
