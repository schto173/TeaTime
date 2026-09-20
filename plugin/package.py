#!/usr/bin/env python3
"""Packages build/teatime_plugin.dll into ../dist/TeaTime.mumble_plugin.

A .mumble_plugin bundle is a zip file with a manifest.xml (see Mumble's
docs/dev/plugins/Bundling.md). Players install it by double-clicking it, or in
Mumble via Configure -> Settings -> Plugins -> Install plugin."""
import os
import zipfile

VERSION = "0.2.0"

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<bundle version="1.0.0">
  <assets>
    <plugin os="windows" arch="x64">teatime_plugin.dll</plugin>
  </assets>
  <name>TeaTime</name>
  <version>%s</version>
</bundle>
""" % VERSION

here = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(here, "..", "dist", "TeaTime.mumble_plugin")
os.makedirs(os.path.dirname(out), exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("manifest.xml", MANIFEST)
    z.write(os.path.join(here, "build", "teatime_plugin.dll"), "teatime_plugin.dll")
print("created", os.path.normpath(out))
