#!/usr/bin/env python3
"""Tea Time Mumble bot.

Runs next to the Mumble server. It logs in as SuperUser and listens for the
small messages the TeaTime Mumble plugin sends from each player's client:

    "TT1 seated=1 map=1420 x=276.8 y=2224.6"   sitting at a campfire here
    "TT1 seated=0 map=-1"                      stood up

The server tells the bot which Mumble user a message came from, so nobody can
move anybody but themselves, and the Mumble user name does not have to match
the WoW character name.

What the bot does with that:

  * The first person to sit down somewhere starts a new "fire": a channel
    "Tea Time / <zone> - Fire <n>" is created and they are moved into it.
  * Anyone who sits down within JOIN_YARDS of an existing fire in the same
    zone is moved into that fire's channel. Fires that are very close to each
    other simply share a channel; voices still fade with distance.
  * When someone stands up, or stops sending updates for --timeout seconds,
    they are moved back to the channel they came from.
  * A fire that stays empty for --empty-after seconds is deleted.
  * Players are not allowed to enter "Tea Time" channels themselves; only this
    bot moves them (disable with --no-acl).

Campfires have no identifier that an addon can read, so a fire is recognised by
where people sit. The position of the fire is the average of the seated players.

The superuser password is read from the environment, never the command line:

    MUMBLE_SUPERUSER_PASSWORD=...  python teatime_mumble.py --host mumble.example.org

Requires:  pip install pymumble
"""
import argparse
import json
import math
import os
import ssl
import sys
import threading
import time

# pymumble (last release 2021) calls ssl.wrap_socket, which Python 3.12
# removed. This shim gives it an equivalent. Mumble servers use self-signed
# certificates, so the certificate is not verified (same as the Mumble client
# on first connect).
if not hasattr(ssl, "wrap_socket"):
    def _wrap_socket(sock, keyfile=None, certfile=None, **_ignored):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if certfile:
            ctx.load_cert_chain(certfile, keyfile)
        return ctx.wrap_socket(sock)
    ssl.wrap_socket = _wrap_socket

# pymumble imports an Opus audio library even though this bot never handles
# audio. If it isn't installed (normal in slim containers and on Windows), a
# do-nothing stand-in is enough.
try:
    import opuslib  # noqa: F401
except Exception:
    import types

    class _NoOpus:
        def __init__(self, *args, **kwargs):
            pass

    _stub = types.ModuleType("opuslib")
    _stub.Encoder = _NoOpus
    _stub.Decoder = _NoOpus
    _stub.exceptions = types.SimpleNamespace(OpusError=Exception)
    sys.modules["opuslib"] = _stub

import pymumble_py3
from pymumble_py3 import messages, mumble_pb2
from pymumble_py3.constants import (PYMUMBLE_CONN_STATE_CONNECTED,
                                    PYMUMBLE_CONN_STATE_FAILED,
                                    PYMUMBLE_MSG_TYPES_ACL)

PARENT = "Tea Time"
DATA_ID = "TeaTime"
MSG_PLUGIN_DATA = 26   # Mumble control message type PluginDataTransmission
PERM_ENTER = 0x4       # Mumble permission bit for entering a channel

JOIN_YARDS = 30.0      # sit this close to a fire and you join its channel
STAY_YARDS = 60.0      # once in a fire you stay until you are this far away
EMPTY_AFTER = 60.0     # seconds an empty fire lives before its channel is deleted

# Cosmetic channel names. Only 1420 is confirmed from the game; the rest are
# from memory of the retail map IDs, so correct any that look wrong.
# Unknown maps just become "Map <id>".
ZONES = {
    1411: "Durotar", 1412: "Mulgore", 1413: "The Barrens",
    1420: "Tirisfal Glades", 1421: "Silverpine Forest",
    1426: "Dun Morogh", 1429: "Elwynn Forest", 1436: "Westfall",
    1438: "Teldrassil",
    1453: "Stormwind City", 1454: "Orgrimmar", 1455: "Ironforge",
    1456: "Thunder Bluff", 1457: "Darnassus", 1458: "Undercity",
}


def zone_channel(map_id):
    name = ZONES.get(map_id)
    return f"{name} ({map_id})" if name else f"Map {map_id}"


# --------------------------------------------- plugin-data message decoding
# pymumble does not know PluginDataTransmission, so the few protobuf fields
# needed are decoded by hand:
#   1 senderSession (varint), 2 receiverSessions, 3 data (bytes), 4 dataID

def _varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def decode_plugin_data(buf):
    sender, data, data_id = None, b"", ""
    i = 0
    while i < len(buf):
        tag, i = _varint(buf, i)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            val, i = _varint(buf, i)
            if field == 1:
                sender = val
        elif wire == 2:
            ln, i = _varint(buf, i)
            chunk = buf[i:i + ln]
            i += ln
            if field == 3:
                data = chunk
            elif field == 4:
                data_id = chunk.decode("utf-8", errors="replace")
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            raise ValueError("unsupported wire type")
    return sender, data_id, data


def _coord(text):
    value = float(text)
    if not math.isfinite(value) or abs(value) > 1e6:
        raise ValueError("bad coordinate")
    return value


def parse_status(data):
    """b'TT1 seated=1 map=1420 x=1.0 y=2.0' -> (True, 1420, 1.0, 2.0).
    x and y are optional (None). Anything malformed -> None."""
    try:
        parts = data.decode("ascii").split()
        if parts[0] != "TT1":
            return None
        kv = dict(p.split("=", 1) for p in parts[1:])
        seated = kv["seated"] == "1"
        map_id = int(kv["map"])
        if seated and not 0 <= map_id < 100000:
            return None
        x = _coord(kv["x"]) if "x" in kv else None
        y = _coord(kv["y"]) if "y" in kv else None
        if (x is None) != (y is None):
            x = y = None
        return seated, map_id, x, y
    except (UnicodeDecodeError, IndexError, KeyError, ValueError):
        return None


# ---------------------------------------------------------------- the mover

class Fire:
    """One campfire: a group of people sitting together, and their channel."""

    def __init__(self, fid, map_id, number, x, y):
        self.id = fid
        self.map = map_id
        self.number = number
        self.x = x            # None = a zone-wide room (no position known)
        self.y = y
        self.members = set()  # Mumble sessions
        self.empty_since = None

    def name(self):
        base = zone_channel(self.map)
        return base if self.x is None else f"{base} - Fire {self.number}"


def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


class Mover:
    def __init__(self, mumble, timeout, lock_rooms=True, join_yards=JOIN_YARDS,
                 stay_yards=STAY_YARDS, empty_after=EMPTY_AFTER):
        self.m = mumble
        self.timeout = timeout
        self.lock_rooms = lock_rooms
        self.join_yards = join_yards
        self.stay_yards = stay_yards
        self.empty_after = empty_after

        self.lock = threading.Lock()
        self.reported = {}    # session -> (map, x, y, time of last message)
        self.origin = {}      # session -> channel id to go back to
        self.pending = set()  # channel names we've asked the server to create

        self.fires = {}       # fire id -> Fire
        self.member_of = {}   # session -> fire id
        self.pos = {}         # session -> (x, y)
        self.since = {}       # session -> when this sitting started
        self.next_id = 1

        self.acl_done = False
        self.cleaned = False

    # called from pymumble's thread whenever a plugin-data message arrives
    def on_plugin_message(self, raw):
        try:
            sender, data_id, data = decode_plugin_data(raw)
        except (ValueError, IndexError):
            return
        if data_id != DATA_ID or sender is None:
            return
        status = parse_status(data)
        if status is None:
            return
        seated, map_id, x, y = status
        with self.lock:
            if seated:
                self.reported[sender] = (map_id, x, y, time.time())
            else:
                self.reported.pop(sender, None)

    def desired(self, file_players):
        """session -> (map, x, y) for everyone who is sitting at a fire."""
        now = time.time()
        out = {}
        with self.lock:
            for session, (map_id, x, y, seen) in list(self.reported.items()):
                if now - seen > self.timeout or session not in self.m.users:
                    del self.reported[session]  # silent for too long / left Mumble
                    continue
                out[session] = (map_id, x, y)
        for name, entry in (file_players or {}).items():
            user = self.find_user_by_name(name)
            if user is not None:
                out.setdefault(user["session"], entry)
        return out

    # -- who sits at which fire
    def _new_fire(self, map_id, x, y):
        used = {f.number for f in self.fires.values() if f.map == map_id and f.x is not None}
        number = next(n for n in range(1, len(used) + 2) if n not in used)
        fire = Fire(self.next_id, map_id, number, x, y)
        self.next_id += 1
        self.fires[fire.id] = fire
        where = "" if x is None else f" at ({x:.0f}, {y:.0f})"
        print(f"[fire] new: {fire.name()!r}{where}")
        return fire

    def _nearest_fire(self, map_id, x, y):
        best, best_d = None, None
        for f in self.fires.values():
            if f.map != map_id:
                continue
            if x is None or y is None:
                if f.x is None:
                    return f  # the zone-wide room for players without a position
                continue
            if f.x is None:
                continue
            d = _dist(f.x, f.y, x, y)
            if d <= self.join_yards and (best_d is None or d < best_d):
                best, best_d = f, d
        return best

    def _still_belongs(self, fire, map_id, x, y):
        if fire.map != map_id:
            return False
        if fire.x is None or x is None or y is None:
            return fire.x is None and (x is None or y is None)
        return _dist(fire.x, fire.y, x, y) <= self.stay_yards

    def _leave_fire(self, session):
        fid = self.member_of.pop(session, None)
        fire = self.fires.get(fid)
        if fire is not None:
            fire.members.discard(session)
        self.pos.pop(session, None)
        self.since.pop(session, None)

    def assign(self, desired):
        now = time.time()
        for session in list(self.member_of):
            if session not in desired:
                self._leave_fire(session)
        # oldest sitters first, so the first person to sit is the one who
        # starts the fire
        for session, (map_id, x, y) in sorted(desired.items(),
                                              key=lambda kv: self.since.get(kv[0], now)):
            self.pos[session] = (x, y)
            fire = self.fires.get(self.member_of.get(session))
            if fire is not None and self._still_belongs(fire, map_id, x, y):
                continue
            if fire is not None:
                self._leave_fire(session)
                self.pos[session] = (x, y)
            self.since.setdefault(session, now)
            fire = self._nearest_fire(map_id, x, y) or self._new_fire(map_id, x, y)
            fire.members.add(session)
            fire.empty_since = None
            self.member_of[session] = fire.id
        # a fire's position is the average of the people sitting at it
        for f in self.fires.values():
            pts = [self.pos[s] for s in f.members if self.pos.get(s, (None, None))[0] is not None]
            if pts and f.x is not None:
                f.x = sum(p[0] for p in pts) / len(pts)
                f.y = sum(p[1] for p in pts) / len(pts)

    # -- channels
    def find_user_by_name(self, name):
        for u in list(self.m.users.values()):
            if u["name"].lower() == name.lower():
                return u
        return None

    def channel_id(self, name, parent_id=None):
        for ch in list(self.m.channels.values()):
            if ch["name"] == name and (parent_id is None or ch.get("parent") == parent_id):
                return ch["channel_id"]
        return None

    def ensure_channel(self, name, parent_id):
        cid = self.channel_id(name, parent_id)
        if cid is not None:
            self.pending.discard(name)
            return cid
        if name not in self.pending:  # creation is asynchronous
            self.pending.add(name)
            print(f"[create] channel {name!r}")
            self.m.channels.new_channel(parent_id, name, False)
        return None

    def move(self, user, channel_id):
        self.m.execute_command(messages.MoveCmd(user["session"], channel_id))

    def lock_zone_rooms(self, parent_id):
        """Players may not walk into "Tea Time" or its channels themselves;
        only this bot (SuperUser ignores permissions) puts them there.
        Replaces the permission list of the "Tea Time" channel. Sent once per
        connection, right after the channel exists."""
        acl = mumble_pb2.ACL()
        acl.channel_id = parent_id
        acl.inherit_acls = True
        acl.query = False
        entry = acl.acls.add()
        entry.apply_here = True
        entry.apply_subs = True
        entry.group = "all"
        entry.deny = PERM_ENTER
        self.m.send_message(PYMUMBLE_MSG_TYPES_ACL, acl)
        self.acl_done = True
        print(f"[acl] {PARENT!r}: players may not enter it themselves")

    def remove_orphans(self, parent_id):
        """Delete empty channels left under "Tea Time" by an earlier run."""
        occupied = {u["channel_id"] for u in list(self.m.users.values())}
        for ch in list(self.m.channels.values()):
            if ch.get("parent") == parent_id and ch["channel_id"] not in occupied:
                print(f"[remove] leftover empty channel {ch['name']!r}")
                self.m.channels.remove_channel(ch["channel_id"])

    def remove_empty_fires(self, parent_id):
        now = time.time()
        for fid, fire in list(self.fires.items()):
            if fire.members:
                fire.empty_since = None
                continue
            if fire.empty_since is None:
                fire.empty_since = now
                continue
            if now - fire.empty_since < self.empty_after:
                continue
            cid = self.channel_id(fire.name(), parent_id)
            if cid is not None:
                if any(u["channel_id"] == cid for u in list(self.m.users.values())):
                    fire.empty_since = now  # someone is still in there: wait
                    continue
                print(f"[remove] {fire.name()!r} (empty)")
                self.m.channels.remove_channel(cid)
            del self.fires[fid]

    # -- one pass
    def tick(self, file_players=None):
        parent_id = self.ensure_channel(PARENT, 0)
        if parent_id is None:
            return  # try again next tick, once the server has created it
        if self.lock_rooms and not self.acl_done:
            self.lock_zone_rooms(parent_id)
        if not self.cleaned:
            self.remove_orphans(parent_id)
            self.cleaned = True

        desired = self.desired(file_players)
        self.assign(desired)

        tea_channels = {ch["channel_id"] for ch in list(self.m.channels.values())
                        if ch.get("parent") == parent_id or ch["channel_id"] == parent_id}

        # 1. everyone sitting at a fire goes to that fire's channel
        for session in desired:
            user = self.m.users.get(session)
            if user is None:
                continue  # disconnected from Mumble
            fire = self.fires[self.member_of[session]]
            cid = self.ensure_channel(fire.name(), parent_id)
            if cid is None:
                continue
            if user["channel_id"] != cid:
                if user["channel_id"] not in tea_channels:
                    self.origin[session] = user["channel_id"]
                print(f"[move] {user['name']} -> {fire.name()}")
                self.move(user, cid)

        # 2. everyone we moved earlier who is no longer sitting goes back
        for session in list(self.origin):
            if session in desired:
                continue
            back = self.origin.pop(session)
            user = self.m.users.get(session)
            if user is not None and user["channel_id"] in tea_channels:
                print(f"[back] {user['name']} -> channel {back}")
                self.move(user, back)

        # 3. fires nobody sits at any more
        self.remove_empty_fires(parent_id)


def read_state_file(path):
    """{character name: (map, x, y)} from the companion's teatime_state.json,
    or None if it can't be read right now."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return None
    now = time.time()
    return {name: (p["map"], p.get("x"), p.get("y"))
            for name, p in data.get("players", {}).items()
            if p.get("map") is not None and now - p.get("seen", 0) <= 90}


def _quiet_connection_errors(hook_args):
    # pymumble's network thread raises this when a connection attempt fails;
    # run_once() already reports that in one line, so hide the traceback.
    if hook_args.exc_type.__name__ == "ConnectionRejectedError":
        return
    sys.__excepthook__(hook_args.exc_type, hook_args.exc_value, hook_args.exc_traceback)


def run_once(args, pw):
    """One connection to the server. Returns True if it got connected at all."""
    m = pymumble_py3.Mumble(args.host, "SuperUser", port=args.port,
                            password=pw, reconnect=False)
    m.set_application_string("TeaTime bot")
    m.set_receive_sound(False)  # we only manage channels, never audio

    mover = Mover(m, args.timeout, lock_rooms=not args.no_acl,
                  join_yards=args.join_yards, stay_yards=args.stay_yards,
                  empty_after=args.empty_after)
    original_dispatch = m.dispatch_control_message

    def dispatch(msg_type, message):
        if msg_type == MSG_PLUGIN_DATA:
            mover.on_plugin_message(message)
        else:
            original_dispatch(msg_type, message)
    m.dispatch_control_message = dispatch

    m.start()
    try:
        deadline = time.time() + 20
        while m.connected != PYMUMBLE_CONN_STATE_CONNECTED:
            if (m.connected == PYMUMBLE_CONN_STATE_FAILED or not m.is_alive()
                    or time.time() > deadline):
                print(f"could not connect to {args.host}:{args.port} "
                      "(server not ready, or wrong host/port/password)")
                return False
            time.sleep(0.2)
        m.is_ready()  # returns once the server has sent the full channel/user list
        print(f"connected to {args.host}:{args.port}, listening for TeaTime plugins"
              + (f", also reading {args.state}" if args.state else ""))

        while m.is_alive() and m.connected == PYMUMBLE_CONN_STATE_CONNECTED:
            file_players = read_state_file(args.state) if args.state else None
            mover.tick(file_players)
            time.sleep(args.interval)
        print("lost the connection to the server")
        return True
    finally:
        try:
            m.stop()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="Tea Time Mumble bot")
    ap.add_argument("--host", default="127.0.0.1", help="Mumble server address")
    ap.add_argument("--port", type=int, default=64738)
    ap.add_argument("--timeout", type=float, default=90.0,
                    help="seconds without an update before a player counts as gone")
    ap.add_argument("--join-yards", type=float, default=JOIN_YARDS,
                    help="sit within this distance of a fire to join its channel")
    ap.add_argument("--stay-yards", type=float, default=STAY_YARDS,
                    help="leave a fire's channel only when this far from it")
    ap.add_argument("--empty-after", type=float, default=EMPTY_AFTER,
                    help="seconds an empty fire's channel is kept before it is deleted")
    ap.add_argument("--state", default=None,
                    help="also read teatime_state.json from tools/teatime_companion.py (testing without the plugin)")
    ap.add_argument("--no-acl", action="store_true",
                    help="don't set the 'players cannot enter Tea Time channels themselves' permission")
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    pw = os.environ.get("MUMBLE_SUPERUSER_PASSWORD")
    if not pw:
        sys.exit("Set MUMBLE_SUPERUSER_PASSWORD in the environment first.")

    threading.excepthook = _quiet_connection_errors

    # Keep trying forever, with a growing pause. Hammering a server with
    # failed logins can get this machine's IP auto-banned by Mumble.
    delay = 5
    try:
        while True:
            connected = run_once(args, pw)
            delay = 5 if connected else min(delay * 2, 60)
            print(f"retrying in {delay} s")
            time.sleep(delay)
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
