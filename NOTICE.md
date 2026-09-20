# Third-party components

Tea Time's own code is MIT licensed (see LICENSE). It builds on the following.

**Mumble plugin header** (`plugin/MumblePlugin.h`)
Copyright The Mumble Developers. Used under the BSD-style license stated at the
top of that file (Mumble's LICENSE). It is Mumble's official header for writing
plugins, included unmodified so that the plugin builds without downloading
anything.

**pymumble** (used by the server bot, installed with pip, not included here)
GPLv3, by Azlux and contributors: https://github.com/azlux/pymumble
The bot imports it at runtime. If you build and distribute the Docker image,
that image contains pymumble and its GPLv3 terms apply to what you distribute.
This is a note, not legal advice: if that matters to you, read the license or
ask someone who can advise on it.

**Mumble server** (`mumblevoip/mumble-server` Docker image)
BSD-3-Clause, by the Mumble developers. Pulled by Docker Compose, not included.

Tea Time is an independent community project. It is not affiliated with or
endorsed by Blizzard Entertainment or the Mumble project. World of Warcraft is
a trademark of Blizzard Entertainment.
