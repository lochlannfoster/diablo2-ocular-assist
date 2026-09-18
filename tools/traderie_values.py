#!/usr/bin/env python3
"""Print Traderie's current HR values for runes and gems, next to the
snapshot in runes.py / gems.py, so the tables can be refreshed by hand.

    python3 tools/traderie_values.py

The values page itself sits behind Cloudflare, but the JSON the page loads
does not: https://traderie.com/api/diablo2resurrected/items/values
"""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gems  # noqa: E402
import runes  # noqa: E402

URL = "https://traderie.com/api/diablo2resurrected/items/values"
# Cloudflare turns away the default urllib agent.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


def fetch() -> dict[str, float]:
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    live = {}
    for item in data["prices"]:
        if item["type"] not in ("runes", "gems"):
            continue
        base = [v for v in item["values"] if v.get("variant_id") is None]
        if base and base[0].get("user_value") is not None:
            live[item["name"]] = float(base[0]["user_value"])
    return live


def main():
    live = fetch()
    print(f"{'item':<20} {'snapshot':>9} {'live':>9}")
    for rune in runes.RUNES:
        now = live.get(f"{rune} Rune")
        mark = "" if now == runes.VALUES[rune] else "  <-"
        print(f"{rune:<20} {runes.VALUES[rune]:>9} {now if now is not None else '-':>9}{mark}")
    for gem in gems.GEMS:
        now = live.get(f"Perfect {gem}")
        mark = "" if now == gems.PERFECT_VALUES[gem] else "  <-"
        print(f"{'Perfect ' + gem:<20} {gems.PERFECT_VALUES[gem]:>9} {now if now is not None else '-':>9}{mark}")
    unpriced = [n for n in live if n.startswith(tuple(gems.GRADES[:-1])) or n in gems.GEMS]
    if unpriced:
        print(f"\nlower-grade gems now priced on Traderie: {', '.join(unpriced)}")


if __name__ == "__main__":
    main()
