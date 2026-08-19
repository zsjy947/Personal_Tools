"""Shanghai Metro: shortest path and fare before/after the price reform.

Given an origin and a destination station, prints the shortest path, its
track-length estimate, and the fare under three schemes:

    current  - the 2005 fare scheme (3 yuan first 6 km, +1 yuan / 10 km)
    plan1    - hearing plan A   (3 yuan first 4 km, then 4/4/4/7/7/7/10/10/10
               km bands, +1 yuan / 15 km above 67 km)
    plan2    - hearing plan B   (4 yuan first 6 km, then 6/8/8/10/10/12/12
               km bands, +1 yuan / 14 km above 72 km)

Distances are haversine straight-line estimates between adjacent stations
scaled by STRAIGHT_TO_TRACK_FACTOR (see README for calibration notes).
"""

import argparse
import heapq
import json
import math
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
# Calibrated against the three officially published fare examples
# (人民广场-陆家嘴, 虹桥火车站-南京东路, 西岑-滴水湖): the implied factor
# window is ~(0.99, 1.08); 1.03 also matches the network-wide track/straight
# ratio (official ~831 km of track vs 766 km straight-line sum).
STRAIGHT_TO_TRACK_FACTOR = 1.03

FARE_SCHEMES = {
    "current": {"label": "现行票价", "base": 3, "base_km": 6.0, "bands": [10.0]},
    "plan1": {"label": "方案一(3元起乘)", "base": 3, "base_km": 4.0,
              "bands": [4, 4, 4, 7, 7, 7, 10, 10, 10, 15.0]},
    "plan2": {"label": "方案二(4元起乘)", "base": 4, "base_km": 6.0,
              "bands": [6, 8, 8, 10, 10, 12, 12, 14.0]},
}


def load_data() -> tuple[dict, dict[str, dict[str, float]]]:
    """Load stations and build the adjacency graph (weight in track km)."""
    stations = json.loads((DATA_DIR / "stations.json").read_text(encoding="utf-8"))
    edges = json.loads((DATA_DIR / "edges.json").read_text(encoding="utf-8"))
    graph: dict[str, dict[str, float]] = {}
    for a, b, straight_km in edges:
        w = straight_km * STRAIGHT_TO_TRACK_FACTOR
        graph.setdefault(a, {})[b] = w
        graph.setdefault(b, {})[a] = w
    return stations, graph


def dijkstra(graph: dict, start: str, end: str) -> tuple[float, list[str]]:
    """Shortest path from start to end; returns (distance_km, station_list)."""
    dist = {start: 0.0}
    prev: dict[str, str] = {}
    queue = [(0.0, start)]
    while queue:
        d, node = heapq.heappop(queue)
        if node == end:
            break
        if d > dist.get(node, math.inf):
            continue
        for nxt, w in graph.get(node, {}).items():
            nd = d + w
            if nd < dist.get(nxt, math.inf):
                dist[nxt] = nd
                prev[nxt] = node
                heapq.heappush(queue, (nd, nxt))
    if end not in dist:
        raise ValueError(f"no path from '{start}' to '{end}'")
    path = [end]
    while path[-1] != start:
        path.append(prev[path[-1]])
    return dist[end], path[::-1]


TRANSFER_WEIGHT = 1000.0  # dominates any km sum, so transfers are minimized first


def fewest_transfers(graph: dict, stations: dict, start: str, end: str) -> tuple[float, int, list[str]]:
    """Path with the fewest line changes (ties broken by shorter distance).

    State-space Dijkstra over (station, line) pairs: riding on the same line
    costs the edge km, changing lines at a station costs TRANSFER_WEIGHT.
    Returns (distance_km, transfers, station_list).
    """
    inf = math.inf
    dist = {(start, ln): 0.0 for ln in stations[start]["lines"]}
    prev: dict[tuple[str, str], tuple[str, str]] = {}
    queue = [(0.0, start, ln) for ln in stations[start]["lines"]]
    heapq.heapify(queue)
    while queue:
        cost, node, line = heapq.heappop(queue)
        if cost > dist.get((node, line), inf) + 1e-9:
            continue
        if node == end:
            break  # settled: first popped end state is optimal
        for nxt, w in graph[node].items():
            shared = set(stations[node]["lines"]) & set(stations[nxt]["lines"])
            if line in shared:  # ride on
                state, nc = (nxt, line), cost + w
                if nc < dist.get(state, inf):
                    dist[state], prev[state] = nc, (node, line)
                    heapq.heappush(queue, (nc, nxt, line))
        for ln in stations[node]["lines"]:  # transfer here
            state, nc = (node, ln), cost + TRANSFER_WEIGHT
            if nc < dist.get(state, inf):
                dist[state], prev[state] = nc, (node, line)
                heapq.heappush(queue, (nc, node, ln))

    end_state = (end, next(iter(stations[end]["lines"])))
    for ln in stations[end]["lines"]:
        if dist.get((end, ln), inf) < dist.get(end_state, inf):
            end_state = (end, ln)
    if end_state not in dist:
        raise ValueError(f"no path from '{start}' to '{end}'")

    chain = [end_state]
    while chain[-1] != (start, chain[-1][1]) and chain[-1] in prev:
        chain.append(prev[chain[-1]])
    path = [s for s, _ in chain[::-1]]
    dedup = [path[0]]
    for s in path[1:]:
        if s != dedup[-1]:
            dedup.append(s)
    transfers = int(round(dist[end_state] / TRANSFER_WEIGHT))
    km = sum(graph[a][b] for a, b in zip(dedup, dedup[1:]))
    return km, transfers, dedup


def fare(distance_km: float, scheme: dict) -> int:
    """Fare for a distance under a scheme.

    Price = base + number of price-step boundaries strictly below the
    distance.  Boundaries start at base_km (the base-price span) and grow by
    each band in turn, repeating the last band indefinitely.
    """
    base, base_km, bands = scheme["base"], scheme["base_km"], scheme["bands"]
    bounds = [base_km]
    while bounds[-1] < distance_km:
        i = min(len(bounds) - 1, len(bands) - 1)
        bounds.append(bounds[-1] + bands[i])
    return base + sum(1 for b in bounds if b < distance_km)


def normalize(name: str) -> str:
    return name.replace(" ", "").replace("　", "").rstrip("站")


ALIASES = {"浦东机场": "浦东1号2号航站楼", "虹桥机场": "虹桥2号航站楼"}


def find_station(query: str, stations: dict) -> list[str]:
    """Return matching station names, best matches first."""
    q = normalize(query)
    if not q:
        return []
    q = ALIASES.get(q, q)
    if q in stations:
        return [q]
    hits = [n for n in stations if q in normalize(n) or normalize(n) in q]
    hits.sort(key=len)
    return hits


def pick_station(query: str, stations: dict) -> str:
    """Resolve a station name; prompt interactively when ambiguous."""
    hits = find_station(query, stations)
    if not hits:
        sys.exit(f"找不到站点 '{query}'，请检查名称（如：人民广场、虹桥火车站）")
    if len(hits) == 1:
        return hits[0]
    print(f"'{query}' 匹配到多个站点：")
    for i, name in enumerate(hits[:8], 1):
        lines = "/".join(stations[name]["lines"])
        print(f"  {i}. {name}（{lines}）")
    if len(hits) > 8:
        print(f"  ... 共 {len(hits)} 个候选")
    try:
        choice = input("请输入序号选择（回车选 1）：").strip() or "1"
    except EOFError:
        sys.exit("无法交互选择，请改用更精确的站名")
    try:
        return hits[int(choice) - 1]
    except (ValueError, IndexError):
        sys.exit(f"无效序号 '{choice}'")


def path_edge_lines(path: list[str], stations: dict) -> list[list[str]]:
    """Per-edge line sets along the path (sorted; edges may be on 2+ lines)."""
    lines = []
    for i in range(len(path) - 1):
        shared = set(stations[path[i]]["lines"]) & set(stations[path[i + 1]]["lines"])
        lines.append(sorted(shared))
    return lines


def line_for(shared: list[str], prev: str | None, nxt: str | None) -> str:
    """Pick a line for an edge: keep the previous line, else prefer the next
    edge's line (so the first edge of a ride reads naturally), else the first."""
    for cand in (prev, nxt):
        if cand and cand in shared:
            return cand
    return shared[0]


def short_name(name: str) -> str:
    """Strip a trailing disambiguation tag like '国家会展中心(17号线)'."""
    return name[: name.rfind("(")] if name.endswith(")") and "(" in name else name


def describe_path(path: list[str], stations: dict) -> str:
    """Render the path with line changes, e.g. '人民广场(2号线) → 南京东路(2号线) → 陆家嘴'."""
    lines = path_edge_lines(path, stations)
    cur = None
    parts = []
    for i, name in enumerate(path[:-1]):
        nxt = lines[i + 1][0] if i + 1 < len(lines) else lines[i][0]
        cur = line_for(lines[i], cur, nxt)
        parts.append(f"{short_name(name)}({cur})")
    parts.append(short_name(path[-1]))
    return " → ".join(parts)


def build_legs(path: list[str], graph: dict, stations: dict) -> list[tuple]:
    """Split the path into line segments; returns (line, from, to, km)."""
    lines = path_edge_lines(path, stations)
    legs, cur_line, seg_start, seg_km = [], None, path[0], 0.0
    for i in range(len(path) - 1):
        nxt = lines[i + 1][0] if i + 1 < len(lines) else lines[i][0]
        line = line_for(lines[i], cur_line, nxt)
        if cur_line is not None and line != cur_line:
            legs.append((cur_line, seg_start, path[i], seg_km))
            seg_start, seg_km = path[i], 0.0
        cur_line = line
        seg_km += graph[path[i]][path[i + 1]]
    legs.append((cur_line, seg_start, path[-1], seg_km))
    return legs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="上海地铁最短路径与调价前后票价查询")
    parser.add_argument("origin", nargs="?", help="起点站，如：人民广场")
    parser.add_argument("destination", nargs="?", help="终点站，如：陆家嘴")
    parser.add_argument("--plan", choices=["all", "current", "plan1", "plan2"],
                        default="all", help="要显示的票价方案（默认 all）")
    parser.add_argument("--selftest", action="store_true",
                        help="运行官方示例票价自检")
    args = parser.parse_args()

    if args.selftest:
        selfcheck()
        return
    if not args.origin or not args.destination:
        parser.print_usage()
        sys.exit("请输入起点站和终点站，如：python metro_fare.py 人民广场 陆家嘴")

    stations, graph = load_data()
    start = pick_station(args.origin, stations)
    end = pick_station(args.destination, stations)
    if start == end:
        sys.exit("起点和终点相同（票价 3 元起，试试不同的两站）")

    distance, path = dijkstra(graph, start, end)
    legs = build_legs(path, graph, stations)

    print(f"\n最短路径（计费依据）：{describe_path(path, stations)}")
    for line, a, b, km in legs:
        print(f"  {short_name(a)} → {short_name(b)}（{line}，约 {km:.1f} km）")
    print(f"总里程：约 {distance:.1f} km（{len(path)} 站，换乘 {len(legs) - 1} 次）")

    km2, transfers2, path2 = fewest_transfers(graph, stations, start, end)
    if path2 != path:
        legs2 = build_legs(path2, graph, stations)
        print(f"\n少换乘路线：{describe_path(path2, stations)}")
        for line, a, b, km in legs2:
            print(f"  {short_name(a)} → {short_name(b)}（{line}，约 {km:.1f} km）")
        print(f"换乘 {transfers2} 次，约 {km2:.1f} km —— 票价按最短路径里程计价，两条路线票价相同")
    print()

    names = {"all": ["current", "plan1", "plan2"],
             "current": ["current"], "plan1": ["plan1"], "plan2": ["plan2"]}
    for key in names[args.plan]:
        scheme = FARE_SCHEMES[key]
        print(f"{scheme['label']}：{fare(distance, scheme)} 元")


def selfcheck() -> None:
    """Verify the fare tables against the officially published examples."""
    cases = [
        # (origin, dest, expected current, plan1, plan2)
        ("人民广场", "陆家嘴", 3, 3, 4),
        ("虹桥火车站", "南京东路", 5, 7, 6),
        ("西岑", "滴水湖", 15, 16, 15),
    ]
    stations, graph = load_data()
    ok = True
    for origin, dest, c, p1, p2 in cases:
        d, _ = dijkstra(graph, origin, dest)
        got = (fare(d, FARE_SCHEMES["current"]), fare(d, FARE_SCHEMES["plan1"]),
               fare(d, FARE_SCHEMES["plan2"]))
        expected = (c, p1, p2)
        status = "OK" if got == expected else "MISMATCH"
        if got != expected:
            ok = False
        print(f"{status}  {origin} → {dest}: {d:6.2f} km  官方 {expected}  计算 {got}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
