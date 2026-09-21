# Player guide

Tea Time lets you talk to the people sitting around the same campfire as you in
WoW Forever, with voices that get quieter with distance. This guide takes you
from nothing to talking.

## What you need

- A Windows PC with the WoW Forever beta installed.
- The free Mumble voice chat program, version 1.4 or newer.
- A working microphone and headphones or speakers.
- The address of a Tea Time server, from whoever hosts one (a friend, a guild or
  a community). If you are the host, start with the [Server guide](SERVER-GUIDE.md).

## Step 1: install the addon

1. Download `TeaTime-addon.zip` from the
   [latest release](https://github.com/schto173/TeaTime/releases/latest) and
   extract it. You get a `TeaTime` folder containing `TeaTime.lua` and
   `TeaTime.toc`.
2. Find your game folder. It is the folder that contains the game itself and,
   inside it, a folder for the beta, for example
   `World of Warcraft\_classic_beta_`. The name can differ between beta builds.
3. Put the `TeaTime` folder into `Interface\AddOns` inside that folder. You
   should end up with `...\Interface\AddOns\TeaTime\TeaTime.lua`.
4. Start the game. On the character selection screen, open the AddOns list and
   make sure Tea Time is ticked. If it is marked "out of date", tick the option
   to load out of date addons.

To check it works, log in and type `/teatime` in chat. It should answer with a
short status line.

## Step 2: install Mumble and the plugin

1. Download and install Mumble from https://www.mumble.info/downloads/.
2. Download `TeaTime.mumble_plugin` from the
   [latest release](https://github.com/schto173/TeaTime/releases/latest) and
   double-click it. Mumble installs it. If double-clicking does nothing, open
   Mumble, go to Configure, then Settings, then Plugins, and use the Install
   plugin button.
3. In the same Plugins list, find TeaTime and make sure it is enabled, including
   its positional audio option.
4. Under the Audio Output settings, make sure positional audio is switched on.

Menu names differ a little between Mumble versions, so if a label here does not
match exactly, look for the closest one.

## Step 3: connect to the server

In Mumble, open the server list and add a new server:

- Address: the server address you were given
- Port: 64738, unless you were told otherwise
- Username: anything you like. It does not have to match your character name.
- Password: only if the server has one

Connect. You will be in the main lobby. Talking there works like any Mumble
server.

## Using it

1. Start the game. Start Mumble too. The order does not matter, but see the
   troubleshooting section if nothing happens.
2. Build or find a campfire and sit down next to it. You will get the
   "Welcoming Campfire" buff.
3. Within a few seconds Mumble moves you into a channel for that fire. If you
   are the first person there, the channel is created for you. If others are
   already sitting at the fire (or within about 30 yards of it), you join them.
4. Talk. You hear the others from the direction they are sitting, and they get
   quieter the further they are from you.
5. Stand up and, after about 15 seconds, Mumble moves you back to where you were.

Some things that are normal:

- The 15 second delay when you stand up is deliberate. The buff briefly drops
  and comes back once a minute while you sit, and the addon waits so that this
  is not mistaken for standing up.
- You cannot walk into a fire channel yourself in Mumble. Only sitting at a fire
  puts you there.
- A fire's channel disappears about a minute after the last person leaves.

## Commands

| Command | What it does |
| --- | --- |
| `/teatime` | Shows whether you are currently counted as sitting |
| `/teatime test` | Sends a test event without needing a campfire |
| `/teatime verbose` | Prints what the addon is doing, useful for troubleshooting |
| `/teatime grace 15` | Sets how many seconds a missing buff is tolerated before counting as standing up |
| `/teatime auras` | Lists your buffs with their spell IDs |

## Troubleshooting

**Nothing happens when I sit down.**
Work through these in order.

1. Type `/teatime verbose`, then sit down. You should see a line starting with
   `TEATIME_E v2 JOIN`. If not, the addon is not seeing the campfire buff. Check
   that the addon is loaded (`/teatime` answers) and try `/teatime auras` while
   sitting to see whether "Welcoming Campfire" appears in the list.
2. In Mumble, open the console or log window and look for a line saying TeaTime
   is watching the game log. If it is missing, the plugin has not found the game.
   Make sure the plugin is enabled, then close and restart Mumble while the game
   is running.
3. Check that the file `Logs\General.log` exists inside your game folder. The
   game creates it. If you use a different game folder than usual, the plugin
   finds it from the running game, so it should still work.
4. Ask the server host whether the bot is running.

**I was moved, but I cannot hear anyone.**
Check your speakers and that Mumble is not muted or deafened. Only people sitting
at the same fire are in your channel. Someone sitting far away is very quiet.

**Left and right sound reversed.**
The plugin assumes how the game's coordinates map to directions and this has not
been checked with several players yet. Please report it as an issue, with which
side you heard someone on and where they were sitting.

**The addon says it is out of date.**
The beta changes. Tick "load out of date addons", or open `TeaTime.toc` and set
the `## Interface:` number to the value shown by
`/run print(select(4, GetBuildInfo()))`.

**The log file gets big.**
The addon writes about 57 KB to the game's log for each message it sends, and it
sends one every 30 seconds while you sit. That is roughly 7 MB per hour of
sitting. The log is a plain text file and can be deleted when the game is closed.

## Privacy

What the pieces do with your information:

- On your PC, the plugin reads one file the game writes, `Logs\General.log`. It
  does not read the game's memory, does not change game files and does not press
  any keys for you. To find the log it asks Windows for the location of the
  running game program.
- While you are sitting, the plugin tells the server operator's bot three things:
  that you are sitting, which zone you are in, and your two position numbers in
  that zone. It never sends your character name.
- Mumble's positional audio sends your position and facing direction along with
  your voice, so other players' Mumble programs can place your voice. It goes to
  the other people in your channel.
- The server operator can see your Mumble username and your connection address,
  as on any Mumble server, and the bot's log records the position where each new
  fire started.
- While you are not sitting, no position is sent. Mumble is given a fixed
  placeholder instead, and the only message to the server is a short note that
  you stood up.

## Is this allowed?

Tea Time is an unofficial community project. It uses an addon function that the
game provides for writing messages to its log, and it reads a log file the game
writes. It does not automate gameplay or read the game's memory. Blizzard has not
reviewed it and you use it at your own risk.

## Uninstall

Delete the `TeaTime` folder from `Interface\AddOns`. In Mumble, go to
Configure, Settings, Plugins, select TeaTime and remove it (or delete its file
from Mumble's plugin folder).
