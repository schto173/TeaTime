# Server guide

This guide is for the person who hosts a Tea Time voice server for others.
Players do not need it; theirs is the [Player guide](PLAYER-GUIDE.md).

## What you are setting up

Two programs that run together in Docker:

- **A Mumble server.** The voice chat server that players connect to.
- **The Tea Time bot.** It logs in to that server as its administrator and
  listens for messages from the players' plugins. It creates one channel per
  campfire, moves people into it when they sit down, and moves them back when
  they stand up.

You need a machine that is on all the time, Docker with Docker Compose, and the
ability to make port 64738 reachable from the internet. The load is small.

Note: the compose file and Dockerfile in this repository were written and checked
for syntax, but were not run as a whole with Docker by the author. The bot
itself was tested against a real Mumble server. If something does not work, the
"Troubleshooting" section below lists the likely causes.

## Setup

1. Copy this repository to the server, or clone it, and go to the `server`
   folder.
2. Create the settings file:

   ```
   cp .env.example .env
   ```

   Open `.env` and replace the password with a long random one. This is the
   Mumble administrator (SuperUser) password. Keep it private.

3. Start everything:

   ```
   docker compose up -d --build
   ```

4. Check the bot connected:

   ```
   docker compose logs -f teatime-bot
   ```

   You should see `connected to mumble-server:64738, listening for TeaTime
   plugins`. If you see `could not connect` followed by `retrying in ...`, give
   the Mumble server a minute to start; the bot keeps trying by itself.

5. Make the server reachable (next section), then give players your address.

## Making it reachable

Players connect to TCP and UDP port 64738.

- On your router, forward **both TCP and UDP port 64738** to the machine running
  Docker. Voice travels over UDP. If only TCP works, Mumble falls back to
  carrying voice over TCP, which works but adds delay.
- If the machine has a firewall, allow the same port. Docker publishes ports
  in a way that can bypass some firewalls such as `ufw`, so check from outside
  rather than assuming.
- Use a name that does not change, such as a dynamic DNS name, if your home
  address changes.
- If your internet provider shares one public address between customers
  (carrier-grade NAT), port forwarding will not work at all. You will need a
  provider option that gives you a public address, or to host on a rented server.
- To test from outside, connect from a phone on mobile data (not your Wi-Fi) with
  a Mumble app. Many routers cannot reach their own public address from inside
  the network, so testing from inside can mislead.

To require a password before anyone can even connect, uncomment
`MUMBLE_CONFIG_SERVERPASSWORD` in `docker-compose.yml` and set one.

## How channels and permissions work

- A channel named **Tea Time** is created at the top level.
- The first person to sit at a campfire causes a channel such as
  `Tirisfal Glades (1420) - Fire 1` to be created inside it. The fire is
  recognised by where people sit: anyone who sits within about 30 yards of an
  existing fire in the same zone joins its channel. Campfires have no identifier
  that the addon can read, so this is the best available.
- Fires that are close together share a channel. Voices still fade with distance
  inside it, so this is not a problem in practice.
- About a minute after the last person leaves a fire, its channel is deleted.
  Empty channels left behind by an earlier run are deleted when the bot starts.
- Players are not allowed to enter anything under Tea Time themselves. Only the
  bot moves them. The bot sets this permission on the Tea Time channel when it
  starts, replacing any permissions you set on that one channel. Start the bot
  with `--no-acl` if you want to manage it yourself.
- The lobby is the normal top-level channel. Players who are not sitting stay
  wherever they are, usually there.

## Administering the server

The bot logs in as **SuperUser**, and Mumble allows only one login per name. So
do not connect to the server as SuperUser while the bot runs, or the bot cannot
connect. To do administration as SuperUser, stop the bot first:

```
docker compose stop teatime-bot
# connect as SuperUser, make your changes, disconnect
docker compose start teatime-bot
```

Players' plugins send their updates to the user named SuperUser, so that name
cannot be changed without also changing the plugin.

## Options

The bot takes these options in the `command:` line of `docker-compose.yml`:

| Option | Default | Meaning |
| --- | --- | --- |
| `--join-yards` | 30 | How close to a fire you must sit to join its channel |
| `--stay-yards` | 60 | You stay in a fire's channel until you are this far from it |
| `--empty-after` | 60 | Seconds an empty fire's channel is kept |
| `--timeout` | 90 | Seconds without any update before someone counts as gone |
| `--no-acl` | off | Do not stop players from entering the fire channels themselves |

## Updating and backups

- To update: get the new files, then `docker compose up -d --build`.
- Everything the Mumble server stores is in the `data` folder next to the compose
  file. Back that folder up if you care about registered users and settings.

## Security notes

- The SuperUser password gives complete control of the Mumble server. Keep `.env`
  private and do not commit it. The repository's `.gitignore` already excludes it.
- Mumble usernames are not verified. Anyone can pick any name. What they cannot do
  is move other people: the bot moves only the person whose plugin sent the
  message, because the Mumble server itself says who sent it.
- Everyone who connects can hear and talk in the lobby, like on any Mumble server.
  Use a server password if you want a closed group.
- Repeated failed logins from one address make Mumble ban that address for a few
  minutes. The bot waits longer between attempts to avoid this.

## Troubleshooting

**The bot keeps saying `could not connect`.**
Check `docker compose ps` that the Mumble server is running, and
`docker compose logs mumble-server`. Make sure both services see the same
`.env` password. If the server was only just started, wait a minute.

**The Mumble server cannot write to `data`.**
The current image fixes the ownership of that folder itself. If you use an
older image or a hardened setup, give the folder to user 10000 with
`sudo chown -R 10000:10000 data`.

**People connect but are never moved.**
Look at `docker compose logs -f teatime-bot` while someone sits at a fire. You
should see a `[fire] new` or `[move]` line. If you see nothing, the player's
plugin is not sending: see the [Player guide](PLAYER-GUIDE.md) troubleshooting.

**Players can be heard from far away or all at full volume.**
Positional audio needs the plugin active on each player's Mumble, and the
setting enabled on the player's side. People without it hear everyone at the
same volume.
