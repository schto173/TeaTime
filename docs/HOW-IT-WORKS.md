# How it works

This document is for people who want to understand, verify or change Tea Time.

## The problem

A WoW addon cannot talk to anything outside the game: no network, no other
programs. Blizzard's own voice chat has no proximity mode, and an addon cannot
create voice channels for strangers (the function that would do it,
`C_VoiceChat.CreateChannel`, answers "Disabled", and joining by channel type
refuses community channels). So the addon needs some way to get a message out of
the game, and something on the player's computer has to pick it up.

## The pieces

```
  WoW addon           Mumble plugin                 Mumble server + bot
  (in the game)       (inside the player's Mumble)  (on the host's machine)

  sees the campfire
  buff, writes a
  line to the game's --> reads Logs/General.log
  log file                gives Mumble position   -->  sends "seated, zone,
                          for positional audio         position" to the bot
                                                        |
                                                        v
                                               bot creates/finds the fire's
                                               channel and moves the player
```

## The addon

`addon/TeaTime/TeaTime.lua` watches for the 60 second "Welcoming Campfire" buff
(spell 1229739) that the game gives you while sitting at a campfire. A different
buff, "Campfire nearby" (spell 1283391), appears when you merely stand close to a
fire and is deliberately ignored.

When the buff appears the addon writes a JOIN line, roughly every 30 seconds while
you sit it writes a BEAT line, and when the buff is gone it writes LEAVE. The
buff drops off and returns about once a minute while you stay seated, so a missing
buff only counts as standing up after a grace period (15 seconds by default,
`/teatime grace <seconds>` changes it while playing).

The line format is one line of plain text:

```
TEATIME_E v2 <KIND> <map id> <instance id> <x> <y> <facing> <character name>
```

`x` and `y` are world positions in yards as returned by the game's `UnitPosition`,
`facing` is in radians. The character name comes last because names can contain
spaces. Nothing later in the chain uses the name.

### How a line gets out of the game

The addon uses `C_Log.LogMessage`, which appends to the game's `Logs/General.log`.
The game buffers that file and only writes it to disk when the buffer fills, so a
single short line would sit in memory for a long time. The addon therefore follows
each event with 14 filler lines of 4000 characters, about 57 KB, which always
pushes the event out.

What was measured in the WoW Forever beta while developing this:

- Each log message is cut at about 4,096 characters.
- The buffer flushes in steps of roughly 49 to 52 KB.
- A message that is flushed this way reaches the disk about 0.1 seconds after the
  game logged it.
- Level (normal, warning, error) makes no difference to flushing, and neither does
  waiting: only writing more data does.
- Chat logging (`/chatlog`) is unsuitable: addon output does not reach it and the
  file is only written when the game closes.

This is a workaround for the missing outside channel and is not something Blizzard
documents or promises. It costs about 7 MB of log per hour of sitting. If Blizzard
changes how the log is written, this would stop working.

## The Mumble plugin

`plugin/teatime_plugin.c` is a small plugin for Mumble's plugin interface, built
against Mumble's official header (`plugin/MumblePlugin.h`, plugin API 1.0.0 so
that it also loads in older clients).

- **Finding the game.** Mumble gives positional plugins a list of running programs.
  The plugin picks one whose name starts with "Wow", asks Windows for its
  location, and opens `Logs/General.log` next to it. It starts reading at the end
  of the file so old events are never replayed, and copes with the game replacing
  the file.
- **Positional audio.** While you are seated, the plugin gives Mumble your
  position (in metres, converted from yards), your facing direction and a context
  of `map<zone id>`. Only people whose context matches get positional audio with
  each other. While you are not seated it provides a fixed placeholder so that
  nothing about your position is shared. The identity string is always empty.
- **Telling the bot.** Mumble lets plugins send small messages to other users. The
  plugin sends `TT1 seated=1 map=1420 x=276.8 y=2224.6` to the user named
  `SuperUser` when you sit, when you move to a different spot, when you change
  zone and every 30 seconds as a heartbeat. When you stand up (or the heartbeat
  stops for 90 seconds) it sends `TT1 seated=0 map=-1`.

The coordinate conversion assumes that the value the addon logs as `x` grows
towards north and `y` towards west, and that facing 0 is north increasing towards
west. These are assumptions from documentation and have not been confirmed in the
game with several players. If left and right sound swapped or turned, the three
constants `TT_NORTH_FROM_X`, `TT_EAST_FROM_Y` and `TT_FACING_SIGN` at the top of
the file are the only things to change.

## The bot

`server/bot/teatime_mumble.py` logs in to the Mumble server as SuperUser and
listens for the plugins' messages. Mumble tells the bot which user each message
came from, and the bot only ever moves that user, so nobody can move anybody else.

Campfires are player-made objects and no identifier for them is available to an
addon, so the bot recognises a fire by where people sit:

1. The first person to sit down where no fire exists starts a new one and a
   channel named `<zone> - Fire <n>` is created.
2. Anyone who sits within 30 yards of an existing fire in the same zone joins it.
   A fire's position is the average of the people sitting at it, so it follows the
   group.
3. Someone already at a fire stays with it until they are more than 60 yards away.
4. When everyone has left, the channel is deleted after a minute.
5. Players that stand up are moved back to the channel they were in before.

It also sets a permission so that players cannot enter these channels themselves,
reconnects by itself if the server restarts, and tidies up leftover empty channels
when it starts. A message without a position (from an older plugin) puts the
player into one channel for the whole zone.

## What has and has not been tested

Tested:

- The addon's sit, stand and grace-period logic against a stand-in for the game's
  functions, and manually in the real game beta: JOIN, BEAT and LEAVE lines appear
  in the game's log within a fraction of a second, and positions and facing are
  recorded correctly.
- The Mumble plugin through its real C interface, using a small program that
  plays the role of Mumble (finding the game, reading the log, handling half-written
  lines and file replacement, timeouts, the messages it sends, positional output).
- The bot against a real Mumble 1.5 server with simulated players: creating,
  joining and deleting fire channels, the permission that stops players entering
  them, message spoofing attempts and malformed messages, reconnecting after a
  server restart, and starting before the server exists. It was also run with the
  same package versions the Docker image installs.

Not tested:

- Loading the plugin in a real Mumble client, and hearing positional audio through
  it. The Windows plugin was cross-compiled and inspected but never run.
- Left and right direction of positional audio (see above).
- Sitting at another player's campfire, and several real players at once. Only one
  player was available during development.
- The Docker Compose setup as a whole and the GitHub Actions workflow. They were
  written and checked for syntax only.
- Whether the buff really returns within the 15 second grace period in every case.
  Only the buff dropping was observed, not how long it stays away.
- How often Mumble looks for a game again after it started before or after the
  game, and whether plugin calls made from Mumble's positional thread are always
  safe. The plugin was written according to the header's documentation.
- Zone names: only Tirisfal Glades (map 1420) was confirmed in the game. Other
  names in the bot are from memory of the retail map IDs and only affect channel
  labels. Unknown maps are shown as "Map <id>".
- Blizzard's view of it.

## Building and running from source

**Plugin** (needs MinGW-w64, on Linux or in WSL):

```
cd plugin
sh build.sh          # creates build/teatime_plugin.dll
python3 package.py   # creates ../dist/TeaTime.mumble_plugin
```

**Bot without Docker:**

```
pip install pymumble==1.6.1
export MUMBLE_SUPERUSER_PASSWORD=...
python3 server/bot/teatime_mumble.py --host your.server
```

**Testing without the Mumble plugin:** `tools/teatime_companion.py` does the same
log reading as the plugin and writes a state file that the bot can read with
`--state`. It matches the Mumble username to the character name, so use the
character name as your Mumble username in that mode.

**Mumble's plugin documentation:** https://github.com/mumble-voip/mumble/tree/master/docs/dev/plugins
