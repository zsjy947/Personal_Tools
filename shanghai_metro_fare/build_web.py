"""Generate a self-contained index.html with the metro data inlined.

Run after fetch_data.py (or after editing web_template.html):
    python build_web.py

The output index.html works by double-clicking it in a browser — no server
and no network needed.
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE / "web_template.html"
OUT = HERE / "index.html"


def main() -> None:
    stations = json.loads((HERE / "data" / "stations.json").read_text(encoding="utf-8"))
    edges = json.loads((HERE / "data" / "edges.json").read_text(encoding="utf-8"))
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*__STATIONS__*/", json.dumps(stations, ensure_ascii=False))
    html = html.replace("/*__EDGES__*/", json.dumps(edges, ensure_ascii=False))
    OUT.write_text(html, encoding="utf-8")
    print(f"index.html generated: {OUT} ({len(html)/1024:.0f} KB, "
          f"{len(stations)} stations, {len(edges)} edges)")


if __name__ == "__main__":
    main()
