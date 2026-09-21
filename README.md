# Tea Time

Voice chat around the campfire for World of Warcraft Forever.

Sit down at a campfire and you can talk to the other people sitting there. Voices
come from the direction of the person speaking and get quieter the further away
they sit. Stand up and you are back where you were. Nobody has to run a helper
program: players install a game addon and a Mumble plugin, and that is all.

Tea Time is an unofficial community project for the WoW Forever beta. It works
alongside the campfire mechanic in the game (the "Welcoming Campfire" buff you
get while sitting) and uses the free, open source Mumble voice chat for the audio.

## For players

You need Windows, the WoW Forever beta, and the address of a Tea Time server from
whoever hosts one.

1. Copy the `addon/TeaTime` folder into your game's `Interface/AddOns` folder.
2. Install [Mumble](https://www.mumble.info), then double-click
   `dist/TeaTime.mumble_plugin` to install the plugin into it. In Mumble's
   plugin list, enable TeaTime, and make sure the **"Link to game and transmit
   positional audio"** checkbox at the top of that list is ticked — Mumble does
   not run any plugin until it is, so this is required for Tea Time to work.
3. In Mumble, add a server using the Tea Time server address you got from its
   host (there is no public one — someone has to run it; see below if that is
   you), connect, then sit down at a campfire in the game.

The full walk-through with pictures of what to expect, troubleshooting and a
privacy summary is in the [Player guide](docs/PLAYER-GUIDE.md).

## For people running a server

You need a machine with Docker and the ability to open one port (64738, TCP and
UDP) to the internet. One command starts a Mumble server and the bot that creates
a channel for each campfire and moves people in and out.

See the [Server guide](docs/SERVER-GUIDE.md).

## How it works, in one paragraph

The addon notices when you sit at a campfire and writes a short line to the game's
own log file. The Mumble plugin, running inside your Mumble, reads that line,
gives Mumble your position for positional audio, and tells the server bot where
you are sitting. The bot puts everyone sitting near the same fire into the same
channel. The technical details, including the unusual way the addon gets its
message out of the game, are in [How it works](docs/HOW-IT-WORKS.md).

## Status

This is early software, written and tested without access to a second player or
to a real Mumble client on Windows. What has been tested and what has not is
listed honestly in [How it works](docs/HOW-IT-WORKS.md#what-has-and-has-not-been-tested).
Read that before you rely on it. It is not endorsed or reviewed by Blizzard, and
you use it at your own risk.

## Repository layout

| Folder | What is in it |
| --- | --- |
| `addon/TeaTime` | The WoW addon |
| `plugin` | Source of the Mumble plugin (C) and the scripts that build it |
| `dist` | The ready-to-install plugin, `TeaTime.mumble_plugin` |
| `server` | Docker Compose setup and the bot's source |
| `tools` | An optional helper for testing and debugging |
| `docs` | Guides |

## License

MIT, see [LICENSE](LICENSE). Third-party components and their licenses are listed
in [NOTICE.md](NOTICE.md).
