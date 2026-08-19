"""Fetch and parse Shanghai Metro network data into graph JSON files.

Downloads the current network layout (per-line ordered station lists with
coordinates) from Amap's subway service and converts it into:

    data/stations.json   station name -> {"lat", "lon", "lines"}
    data/edges.json      [[stationA, stationB, straight_km], ...]

Edges are undirected; one edge per pair of adjacent stations on the same
line, plus the closing edge of the line-4 ring.  Stations sharing the same
name across lines are merged into a single node (free transfer).

Excluded from the graph (per the official fare scheme): the Maglev (磁浮线)
and the Airport Link Line (市域机场线); the Jinshan Railway is not part of
the Amap dataset either.

Distances are haversine great-circle straight-line distances in km between
adjacent stations; the real track mileage is longer (see README).  The
coordinates are GCJ-02 (Amap datum), consistent across the whole dataset.
"""

import json
import math
import sys
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = ("https://map.amap.com/service/subway?_1504240247655"
              "&srhdata=3100_drw_shanghai.json")
RAW_FILE = Path(__file__).parent / "data" / "raw" / "amap_srh.json"
OUT_DIR = Path(__file__).parent / "data"
EXCLUDED_LINES = {"磁浮线", "市域机场线"}

EARTH_RADIUS_KM = 6371.0088


def fetch_source() -> dict:
    """Return the Amap subway JSON, downloading it if not cached locally."""
    if RAW_FILE.exists():
        return json.loads(RAW_FILE.read_text(encoding="utf-8"))
    req = Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urlopen(req, timeout=30).read().decode("utf-8"))
    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
    RAW_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def main() -> None:
    data = fetch_source()
    line_entries = [ln for ln in data["l"] if ln["ln"] not in EXCLUDED_LINES]

    # ---- merge stations by name (same name across lines = one node) ----
    nodes: dict[str, dict] = {}
    for ln in line_entries:
        for st in ln["st"]:
            name = st["n"]
            if name not in nodes:
                nodes[name] = {"lat": 0.0, "lon": 0.0, "count": 0, "lines": []}
            node = nodes[name]
            lon, lat = map(float, st["sl"].split(","))
            node["lat"] += lat
            node["lon"] += lon
            node["count"] += 1
            node["lines"].append(ln["ln"])
    for node in nodes.values():
        node["lat"] /= node["count"]
        node["lon"] /= node["count"]

    # ---- edges: consecutive stations per line entry ----
    edge_pairs: set[tuple[str, str]] = set()
    for ln in line_entries:
        seq = [st["n"] for st in ln["st"]]
        for i in range(len(seq) - 1):
            edge_pairs.add(tuple(sorted((seq[i], seq[i + 1]))))
        if ln["ln"] == "4号线":  # ring line: close the loop
            edge_pairs.add(tuple(sorted((seq[0], seq[-1]))))

    edges = []
    for a, b in sorted(edge_pairs):
        na, nb = nodes[a], nodes[b]
        d = haversine_km(na["lat"], na["lon"], nb["lat"], nb["lon"])
        if d < 0.01:  # same physical location, e.g. ring closure
            d = 0.0
        edges.append([a, b, round(d, 3)])

    # ---- persist ----
    out = {
        name: {"lat": round(n["lat"], 6), "lon": round(n["lon"], 6),
               "lines": sorted(set(n["lines"]))}
        for name, n in sorted(nodes.items())
    }
    (OUT_DIR / "stations.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "edges.json").write_text(
        json.dumps(edges, ensure_ascii=False), encoding="utf-8")

    # ---- summary ----
    total_km = sum(e[2] for e in edges)
    print(f"stations: {len(out)}  edges: {len(edges)}")
    print(f"total straight-line track length: {total_km:.1f} km")
    by_line: dict[str, int] = {}
    for ln in line_entries:
        by_line[ln["ln"]] = len(ln["st"])
    for ln, n in by_line.items():
        print(f"  {ln}: {n} stations")


if __name__ == "__main__":
    main()
