# ╔══════════════════════════════════════════════════════════════╗
# ║           NavisphereX Maritime Router — FINAL                ║
# ║                                                              ║
# ║  Graph Data : NavisphereX proprietary route database         ║
# ║               38,679 nodes · 52,093 edges                    ║
# ║               Built from 5,681 NavisphereX RTZ routes        ║
# ║                                                              ║
# ║  Routing    : A* shortest path on NavisphereX graph          ║
# ║  Land Check : Natural Earth 10m polygons                     ║
# ║  Safety     : TSS · Dangers · Depth                          ║
# ║  Fallback   : searoute (open ocean gaps only)                ║
# ║                                                              ║
# ║  Files required (same folder):                               ║
# ║    main_FINAL.py          ← this file                        ║
# ║    world_graph.json       ← NavisphereX route graph          ║
# ║                                                              ║
# ║  Endpoints:                                                  ║
# ║    GET  /route            compute sea route                  ║
# ║    POST /safety-check     validate waypoint list             ║
# ║    GET  /health           service status                     ║
# ║    GET  /graph/stats      graph info                         ║
# ╚══════════════════════════════════════════════════════════════╝

import os, sys, math, heapq, threading, json, requests
from flask import Flask, request, jsonify
from shapely.geometry import LineString
import geopandas as gpd

app = Flask(__name__)

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r

# ══════════════════════════════════════════════════════════════
# LOAD NavisphereX ROUTING GRAPH
# world_graph.json must be in same folder as this file
# ══════════════════════════════════════════════════════════════
_GRAPH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_graph.json")

_N   = {}   # node_id → {name, lat, lon}
_ADJ = {}   # node_id → [(neighbor_id, dist_nm)]
_GRAPH_LOADED = False

def _load_graph():
    global _N, _ADJ, _GRAPH_LOADED
    try:
        with open(_GRAPH_FILE) as f:
            db = json.load(f)
        for row in db["n"]:
            nid, name, lat, lon = row
            _N[nid]   = {"name": name or "", "lat": lat, "lon": lon}
            _ADJ[nid] = []
        for row in db["e"]:
            f, t, d = row
            _ADJ[f].append((t, d))
            _ADJ[t].append((f, d))
        _GRAPH_LOADED = True
        print(f"[NavisphereX] Graph loaded: {len(_N):,} nodes, {len(db['e']):,} edges", flush=True)
    except Exception as ex:
        print(f"[NavisphereX] GRAPH LOAD ERROR: {ex}", file=sys.stderr, flush=True)

_load_graph()

# ══════════════════════════════════════════════════════════════
# BACKGROUND INIT — land polygons + searoute fallback
# Port binds immediately, heavy work runs after
# ══════════════════════════════════════════════════════════════
SR    = None
LAND  = None
READY = False

def _bg_init():
    global SR, LAND, READY
    # Land polygon checker (Natural Earth 10m)
    try:
        gdf  = gpd.read_file(
            "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
        )
        LAND = gdf.geometry.union_all()
        print("[NavisphereX] Land polygons loaded ✅", flush=True)
    except Exception as e:
        print(f"[NavisphereX] Land WARNING: {e}", file=sys.stderr, flush=True)
    # searoute — fallback only for routes with no graph path
    try:
        import searoute as sr
        sr.searoute([2.35, 48.85], [103.82, 1.27], units="naut")
        SR = sr
        print("[NavisphereX] searoute fallback ready ✅", flush=True)
    except Exception as e:
        print(f"[NavisphereX] searoute N/A: {e}", file=sys.stderr, flush=True)
    READY = True
    print(f"[NavisphereX] READY — {len(_N):,} nodes loaded", flush=True)

threading.Thread(target=_bg_init, daemon=True).start()

# ══════════════════════════════════════════════════════════════
# GEOMETRY HELPERS
# ══════════════════════════════════════════════════════════════
def hav(lat1, lon1, lat2, lon2):
    """Haversine distance in nautical miles."""
    R = 3440.065
    a = (math.sin(math.radians((lat2-lat1)/2))**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(math.radians((lon2-lon1)/2))**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))

def brg(lon1, lat1, lon2, lat2):
    """True bearing in degrees."""
    dl = math.radians(lon2-lon1)
    la, lb = math.radians(lat1), math.radians(lat2)
    return (math.degrees(math.atan2(
        math.sin(dl) * math.cos(lb),
        math.cos(la)*math.sin(lb) - math.sin(la)*math.cos(lb)*math.cos(dl)
    )) + 360) % 360

def crosses_land(c1, c2):
    if LAND is None: return False
    try:   return LineString([c1, c2]).intersects(LAND)
    except: return False

def any_land(coords):
    return any(crosses_land(coords[i], coords[i+1]) for i in range(len(coords)-1))

def rdp_simplify(coords, eps=1.5):
    """Ramer-Douglas-Peucker simplification in nautical miles."""
    if len(coords) <= 2: return coords
    def pt_dist(p, a, b):
        dx, dy = b[0]-a[0], b[1]-a[1]
        if dx == dy == 0:
            return hav(p[1], p[0], a[1], a[0])
        t = max(0, min(1, ((p[0]-a[0])*dx + (p[1]-a[1])*dy) / (dx*dx+dy*dy)))
        return hav(p[1], p[0], a[1]+t*dy, a[0]+t*dx)
    def rdp(pts, e):
        if len(pts) <= 2: return pts
        dm, idx = 0, 0
        for i in range(1, len(pts)-1):
            d = pt_dist(pts[i], pts[0], pts[-1])
            if d > dm: dm, idx = d, i
        if dm > e:
            return rdp(pts[:idx+1], e)[:-1] + rdp(pts[idx:], e)
        return [pts[0], pts[-1]]
    return rdp(coords, eps)

# ══════════════════════════════════════════════════════════════
# A* ROUTING ON NavisphereX GRAPH
# ══════════════════════════════════════════════════════════════
def knn(lat, lon, k=5):
    """Find k nearest graph nodes."""
    return sorted(
        [(hav(lat, lon, n["lat"], n["lon"]), i) for i, n in _N.items()]
    )[:k]

def astar(s, e):
    """A* shortest path through NavisphereX graph."""
    eLat, eLon = _N[e]["lat"], _N[e]["lon"]
    h = lambda n: hav(_N[n]["lat"], _N[n]["lon"], eLat, eLon)
    g = {i: float("inf") for i in _N}
    g[s] = 0; prev = {}
    pq = [(h(s), 0.0, s)]; vis = set()
    while pq:
        f, c, u = heapq.heappop(pq)
        if u in vis: continue
        vis.add(u)
        if u == e: break
        for v, w in _ADJ.get(u, []):
            nc = c + w
            if nc < g[v]:
                g[v] = nc; prev[v] = u
                heapq.heappush(pq, (nc + h(v), nc, v))
    if g[e] == float("inf"): return None, float("inf")
    path, cur = [], e
    while cur in prev: path.append(cur); cur = prev[cur]
    path.append(s)
    return list(reversed(path)), g[e]

def build_route(flat, flon, tlat, tlon):
    """
    Route via NavisphereX graph:
      origin → nearest graph node → A* → nearest graph node → destination
    """
    from_cands = knn(flat, flon, 5)
    to_cands   = knn(tlat, tlon, 5)
    best_path, best_nm = None, float("inf")

    for d1, n1 in from_cands:
        for d2, n2 in to_cands:
            if n1 == n2: continue
            path, nm = astar(n1, n2)
            if path and (d1 + nm + d2) < best_nm:
                best_nm   = d1 + nm + d2
                best_path = path

    if best_path is None:
        return None, None, float("inf"), "no-graph-path"

    coords = [[flon, flat]]
    for nid in best_path:
        nd = _N[nid]
        coords.append([nd["lon"], nd["lat"]])
    coords.append([tlon, tlat])

    return coords, best_path, best_nm, "navisphereX-astar"

def searoute_fallback(flat, flon, tlat, tlon):
    """Open ocean fallback when graph has no path."""
    if SR is None:
        return [[flon, flat], [tlon, tlat]], 0.0, "no-fallback"
    try:
        r = SR.searoute([flon, flat], [tlon, tlat],
                        units="naut", append_orig_dest=True)
        return (r.geometry["coordinates"],
                float(r.properties.get("length", 0)),
                "searoute-fallback")
    except Exception as ex:
        return [[flon, flat], [tlon, tlat]], 0.0, f"fallback-error:{ex}"

# ══════════════════════════════════════════════════════════════
# SAFETY CHECKS
# ══════════════════════════════════════════════════════════════
GEBCO = "https://api.odb.ntu.edu.tw/gebco"
OVP   = "https://overpass-api.de/api/interpreter"
_TC, _DC = {}, {}

DANGER_TYPES = [
    "rock", "wreck", "obstruction", "shoal", "reef",
    "underwater_rock", "foul_ground", "snag"
]

def check_tss(coords, buf=0.3):
    if not coords: return []
    lons = [c[0] for c in coords]; lats = [c[1] for c in coords]
    s = round(min(lats)-buf, 2); n = round(max(lats)+buf, 2)
    w = round(min(lons)-buf, 2); e = round(max(lons)+buf, 2)
    key = f"{s}_{w}_{n}_{e}"
    if key in _TC: return _TC[key]
    q = (f'[out:json][timeout:20];'
         f'(way["seamark:type"="separation_lane"]({s},{w},{n},{e});'
         f'way["seamark:type"="separation_zone"]({s},{w},{n},{e});'
         f'relation["seamark:type"="traffic_separation_scheme"]({s},{w},{n},{e}););'
         f'out tags center;')
    zs = []
    try:
        r = requests.post(OVP, data={"data": q}, timeout=15)
        if r.status_code == 200:
            for el in r.json().get("elements", []):
                t  = el.get("tags", {})
                nm = t.get("seamark:name") or t.get("name") or "TSS"
                if nm not in zs: zs.append(nm)
    except: pass
    _TC[key] = zs
    return zs

def check_dangers(coords, buf_nm=2.0):
    lons = [c[0] for c in coords]; lats = [c[1] for c in coords]
    s = round(min(lats)-.1, 2); n = round(max(lats)+.1, 2)
    w = round(min(lons)-.1, 2); e = round(max(lons)+.1, 2)
    key = f"{s}_{w}_{n}_{e}"
    if key in _DC:
        dm = _DC[key]
    else:
        fi = "\n".join(
            [f'  node["seamark:type"="{t}"]({s},{w},{n},{e});' for t in DANGER_TYPES]
        )
        q  = f"[out:json][timeout:20];\n(\n{fi}\n);\nout body;"
        dm = []
        try:
            r = requests.post(OVP, data={"data": q}, timeout=15)
            if r.status_code == 200:
                for el in r.json().get("elements", []):
                    tags = el.get("tags", {})
                    dm.append({
                        "type": tags.get("seamark:type", "?"),
                        "name": tags.get("name", ""),
                        "lon":  el.get("lon"),
                        "lat":  el.get("lat"),
                    })
        except: pass
        _DC[key] = dm
    nearby = []
    for d in dm:
        dl, da = d.get("lon"), d.get("lat")
        if dl is None: continue
        md = min(hav(da, dl, c[1], c[0]) for c in coords)
        if md < buf_nm:
            nearby.append({**d, "nearest_nm": round(md, 2)})
    return {"safe": not nearby, "dangers": nearby, "total": len(dm)}

def check_depth(coords, draft=10.0, safety=2.0):
    mr  = draft + safety
    pts = []
    for i in range(len(coords)-1):
        c1, c2 = coords[i], coords[i+1]
        st = max(1, int(hav(c1[1], c1[0], c2[1], c2[0]) / 15))
        for s in range(st):
            t = s / st
            pts.append((c1[0]+t*(c2[0]-c1[0]), c1[1]+t*(c2[1]-c1[1])))
    if coords: pts.append((coords[-1][0], coords[-1][1]))
    shallow, depths = [], []
    try:
        lns = ",".join(str(round(p[0], 4)) for p in pts)
        lts = ",".join(str(round(p[1], 4)) for p in pts)
        r   = requests.get(
            f"{GEBCO}?lon={lns}&lat={lts}&mode=zonly", timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            zs   = data.get("z", []) if isinstance(data, dict) else data
            for i, p in enumerate(pts):
                if i < len(zs) and zs[i] is not None:
                    wd = abs(zs[i]) if zs[i] < 0 else 0
                    depths.append(wd)
                    if 0 < wd < mr:
                        shallow.append({
                            "lon":      p[0],
                            "lat":      p[1],
                            "depth":    round(wd, 1),
                            "required": mr,
                        })
    except: pass
    return {
        "safe":      not shallow,
        "min_depth": round(min(depths), 1) if depths else None,
        "shallow":   shallow,
        "checked":   len(pts),
        "required":  mr,
    }

# ══════════════════════════════════════════════════════════════
# GET /route
# ══════════════════════════════════════════════════════════════
@app.route("/route")
def route_ep():
    try:
        flat  = float(request.args["fromLat"])
        flon  = float(request.args["fromLon"])
        tlat  = float(request.args["toLat"])
        tlon  = float(request.args["toLon"])
        draft = float(request.args.get("draft",    10.0))
        saf   = float(request.args.get("safety",    2.0))
        eps   = float(request.args.get("simplify",  1.5))
        do_tss    = request.args.get("tss",    "true").lower()  == "true"
        do_danger = request.args.get("danger", "true").lower()  == "true"
        do_depth  = request.args.get("depth",  "false").lower() == "true"
    except (KeyError, ValueError) as ex:
        return jsonify({"error": f"Bad param: {ex}"}), 400

    if not _GRAPH_LOADED:
        return jsonify({"error": "Graph not loaded — world_graph.json missing"}), 503

    # ── Step 1: Route via NavisphereX graph ───────────────────
    coords, path, dist_nm, method = build_route(flat, flon, tlat, tlon)

    if coords is None:
        # Fallback for truly uncovered areas
        print("[NavisphereX] No graph path — searoute fallback", flush=True)
        coords, dist_nm, method = searoute_fallback(flat, flon, tlat, tlon)
        path = []

    # ── Step 2: Simplify ──────────────────────────────────────
    simp = rdp_simplify(coords, eps)

    # ── Step 3: Recalculate total NM ─────────────────────────
    total_nm = sum(
        hav(simp[i][1], simp[i][0], simp[i+1][1], simp[i+1][0])
        for i in range(len(simp)-1)
    )

    # ── Step 4: Land check ────────────────────────────────────
    lc = any_land(simp)

    # ── Step 5: Named waypoints on route ─────────────────────
    named = [
        {"name": _N[nid]["name"], "lat": _N[nid]["lat"], "lon": _N[nid]["lon"]}
        for nid in (path or []) if _N[nid]["name"]
    ]

    # ── Step 6: Safety checks ─────────────────────────────────
    tss = check_tss(simp)    if do_tss    else []
    dng = check_dangers(simp) if do_danger else {"safe": True, "dangers": [], "total": 0}
    dep = check_depth(simp, draft, saf) if do_depth else {
        "safe": True, "shallow": [], "checked": 0, "required": draft+saf
    }

    # ── Step 7: Warnings ──────────────────────────────────────
    warns = []
    if lc:
        warns.append("🚨 Route crosses land — add manual waypoints to correct")
    for z in tss:
        warns.append(f"🚢 TSS zone: {z} — verify correct separation lane")
    for sp in dep.get("shallow", []):
        warns.append(
            f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})"
            f" — vessel needs {sp['required']}m"
        )
    for d in dng.get("dangers", []):
        warns.append(
            f"🪨 {d['type'].upper()} '{d['name']}'"
            f" ({d.get('lat',0):.3f},{d.get('lon',0):.3f})"
            f" {d['nearest_nm']}NM from route"
        )

    print(
        f"[NavisphereX] {total_nm:.0f}NM | "
        f"{len(coords)}→{len(simp)}pts | "
        f"{method} | named={len(named)} | land={lc}",
        flush=True
    )

    return jsonify({
        "waypoints":       [{"lat": float(c[1]), "lon": float(c[0])} for c in simp],
        "namedWaypoints":  named,
        "totalNM":         round(total_nm, 1),
        "source":          "NavisphereX-Router",
        "method":          method,
        "graphNodes":      len(_N),
        "pointsRaw":       len(coords),
        "pointsFinal":     len(simp),
        "landCrossing":    lc,
        "tssZones":        tss,
        "overallSafe":     not lc and dep["safe"] and dng["safe"],
        "warnings":        warns,
        "safetyReport":    {"depth": dep, "danger": dng},
    })

# ══════════════════════════════════════════════════════════════
# POST /safety-check
# ══════════════════════════════════════════════════════════════
@app.route("/safety-check", methods=["POST", "OPTIONS"])
def safety_ep():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({"error": "JSON body required"}), 400
        raw = body.get("waypoints", [])
        if len(raw) < 2:
            return jsonify({"error": "Need ≥2 waypoints"}), 400

        coords = [[float(w["lon"]), float(w["lat"])] for w in raw]
        draft  = float(body.get("draft",   10.0))
        saf    = float(body.get("safety",   2.0))
        beam   = float(body.get("beam",    32.0))
        loa    = float(body.get("loa",    200.0))

        # Land
        lc    = any_land(coords)
        lsegs = []
        if lc:
            for i in range(len(coords)-1):
                if crosses_land(coords[i], coords[i+1]):
                    lsegs.append({
                        "from": {"lon": coords[i][0],   "lat": coords[i][1]},
                        "to":   {"lon": coords[i+1][0], "lat": coords[i+1][1]},
                        "seg":  i,
                    })

        tss = check_tss(coords)
        dep = check_depth(coords, draft, saf)
        dng = check_dangers(coords)

        total, ml, legs = 0.0, 0.0, []
        for i in range(len(coords)-1):
            c1, c2 = coords[i], coords[i+1]
            nm = hav(c1[1], c1[0], c2[1], c2[0])
            total += nm; ml = max(ml, nm)
            legs.append({
                "from":    {"lon": c1[0], "lat": c1[1]},
                "to":      {"lon": c2[0], "lat": c2[1]},
                "nm":      round(nm, 1),
                "bearing": round(brg(c1[0], c1[1], c2[0], c2[1]), 1),
            })

        warns = []
        if lc:    warns.append(f"🚨 LAND CROSSING in {len(lsegs)} segment(s)")
        for z in tss: warns.append(f"🚢 TSS: {z}")
        for sp in dep.get("shallow", []):
            warns.append(f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})")
        for d in dng.get("dangers", []):
            warns.append(f"🪨 {d['type']} '{d['name']}' {d['nearest_nm']}NM")

        eta = lambda nm, kn: round(nm/kn, 2) if kn > 0 else None

        return jsonify({
            "overall_safe":   not lc and dep["safe"] and dng["safe"],
            "total_warnings": len(warns),
            "warnings":       warns,
            "route_stats": {
                "total_nm":       round(total, 1),
                "waypoint_count": len(coords),
                "max_leg_nm":     round(ml, 1),
                "eta": {
                    "10kn": eta(total, 10), "12kn": eta(total, 12),
                    "14kn": eta(total, 14), "15kn": eta(total, 15),
                    "18kn": eta(total, 18),
                },
            },
            "land_check": {
                "safe":             not lc,
                "problem_segments": lsegs,
            },
            "tss_check": {
                "zones_found": len(tss),
                "zones":       tss,
            },
            "depth_check": {
                "safe":       dep["safe"],
                "min_depth_m": dep.get("min_depth"),
                "required":   dep.get("required"),
                "shallow":    dep.get("shallow", []),
            },
            "danger_check": {
                "safe":    dng["safe"],
                "dangers": dng.get("dangers", []),
            },
            "vessel_params": {
                "draft_m":  draft,
                "safety_m": saf,
                "beam_m":   beam,
                "loa_m":    loa,
            },
            "legs": legs,
        })

    except Exception as ex:
        print(f"[NavisphereX safety] {ex}", file=sys.stderr)
        return jsonify({"error": str(ex)}), 500

# ══════════════════════════════════════════════════════════════
# GET /health
# ══════════════════════════════════════════════════════════════
@app.route("/")
@app.route("/health")
def health():
    return jsonify({
        "status":       "ok" if READY else "initializing",
        "service":      "NavisphereX Maritime Router",
        "data_source":  "NavisphereX proprietary route database",
        "graph": {
            "nodes":    len(_N),
            "loaded":   _GRAPH_LOADED,
            "file":     "world_graph.json",
        },
        "land_check":   LAND is not None,
        "searoute":     SR is not None,
        "ready":        READY,
    })

# ══════════════════════════════════════════════════════════════
# GET /graph/stats
# ══════════════════════════════════════════════════════════════
@app.route("/graph/stats")
def graph_stats():
    named = [
        {"id": i, "name": n["name"], "lat": n["lat"], "lon": n["lon"]}
        for i, n in _N.items() if n["name"]
    ]
    return jsonify({
        "service":      "NavisphereX Maritime Router",
        "data_source":  "NavisphereX proprietary route database",
        "total_nodes":  len(_N),
        "named_nodes":  len(named),
        "named":        named,
    })

# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# gunicorn: gunicorn main_FINAL:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"[NavisphereX] Starting on :{port} — {len(_N):,} graph nodes", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
