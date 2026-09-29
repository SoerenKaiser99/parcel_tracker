"""Download carrier icons (Simple Icons, CC0) and print a JS object literal."""

import json
import re
import urllib.request

ICONS = {"dhl": "#FFCC00", "dpd": "#DC0032"}

out = {}
for slug, color in ICONS.items():
    svg = urllib.request.urlopen(
        f"https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/{slug}.svg", timeout=20
    ).read().decode()
    path = re.search(r' d="([^"]+)"', svg).group(1)
    out[slug] = {"path": path, "color": color}
print("const CARRIER_ICONS = " + json.dumps(out) + ";")
