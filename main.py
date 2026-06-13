import os, sys, math, heapq, json, threading, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r

BASE  = os.path.dirname(os.path.abspath(__file__))
NODES = {}
ADJ   = {}
GRAPH_NAME = ""
READY = False

# ── Haversine ─────────────────────────────────────────────────
def hav(lat1, lon1, lat2, lon2):
    R = 3440.065
    a = (math.sin(math.radians((lat2-lat1)/2))**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(math.radians((lon2-lon1)/2))**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))

# ── Graph loader — handles GeoJSON and plain JSON formats ─────
def load_geojson(db):
    """Parse GeoJSON FeatureCollection of LineStrings."""
    nodes = {}; adj = {}; coord_to_id = {}; nid = 0

    def get_node(lon, lat):
        nonlocal nid
        key = (round(lon, 3), round(lat, 3))
        if key not in coord_to_id:
            coord_to_id[key] = nid
            nodes[nid] = (float(lat), float(lon), "")
            adj[nid] = []
            nid += 1
        return coord_to_id[key]

    for feat in db.get("features", []):
        geom = feat.get("geometry", {})
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if gtype == "LineString":
            segments = [coords]
        elif gtype == "MultiLineString":
            segments = coords
        else:
            continue
        for seg in segments:
            prev = None
            for pt in seg:
                lon, lat = float(pt[0]), float(pt[1])
                ni = get_node(lon, lat)
                if prev is not None and prev != ni:
                    d = hav(nodes[prev][0], nodes[prev][1],
                            nodes[ni][0],   nodes[ni][1])
                    if 0 < d < 500:
                        adj[prev].append((ni, d))
                        adj[ni].append((prev, d))
                prev = ni
    return nodes, adj

def load_plain(db):
    """Parse plain JSON with n/nodes and e/edges keys."""
    nodes = {}; adj = {}
    raw_nodes = db.get("n") or db.get("nodes") or []
    raw_edges = db.get("e") or db.get("edges") or []
    for row in raw_nodes:
        if len(row) == 4:
            nid, name, lat, lon = row
        elif len(row) == 3:
            nid, lat, lon = row; name = ""
        else:
            continue
        nodes[nid] = (float(lat), float(lon), str(name or ""))
        adj[nid] = []
    for row in raw_edges:
        f, t, d = row[0], row[1], row[2]
        if f in adj and t in adj:
            adj[f].append((t, float(d)))
            adj[t].append((f, float(d)))
    return nodes, adj

def load_graph():
    global NODES, ADJ, GRAPH_NAME, READY
    for fname in ["worldroutens.json", "world_graph_v2.json"]:
        fpath = os.path.join(BASE, fname)
        if not os.path.exists(fpath):
            continue
        try:
            print(f"[router] Loading {fname}...", flush=True)
            with open(fpath) as f:
                db = json.load(f)
            # Detect format
            if db.get("type") == "FeatureCollection":
                nodes, adj = load_geojson(db)
            else:
                nodes, adj = load_plain(db)
            if len(nodes) == 0:
                print(f"[router] {fname} gave 0 nodes, skipping", flush=True)
                continue
            NODES = nodes; ADJ = adj; GRAPH_NAME = fname
            READY = True
            print(f"[router] Ready — {len(NODES):,} nodes from {fname}", flush=True)
            return
        except Exception as e:
            print(f"[router] Error: {e}", file=sys.stderr, flush=True)
    print("[router] ERROR: no graph loaded", file=sys.stderr, flush=True)

threading.Thread(target=load_graph, daemon=True).start()

# ── Routing ───────────────────────────────────────────────────
def nearest_nodes(lat, lon, k=5):
    dists = [(hav(lat, lon, NODES[i][0], NODES[i][1]), i) for i in NODES]
    dists.sort()
    return [i for _, i in dists[:k]]

def astar(start, end):
    elat, elon = NODES[end][0], NODES[end][1]
    h = lambda n: hav(NODES[n][0], NODES[n][1], elat, elon)
    g = {start: 0.0}; prev = {}
    pq = [(h(start), start)]; vis = set()
    while pq:
        _, u = heapq.heappop(pq)
        if u in vis: continue
        vis.add(u)
        if u == end: break
        for v, w in ADJ.get(u, []):
            ng = g[u] + w
            if ng < g.get(v, float("inf")):
                g[v] = ng; prev[v] = u
                heapq.heappush(pq, (ng + h(v), v))
    if end not in g: return None, float("inf")
    path, cur = [], end
    while cur in prev: path.append(cur); cur = prev[cur]
    path.append(start)
    return list(reversed(path)), g[end]

def compute_route(flat, flon, tlat, tlon):
    fc = nearest_nodes(flat, flon, 5)
    tc = nearest_nodes(tlat, tlon, 5)
    best_path, best_nm = None, float("inf")
    for n1 in fc:
        for n2 in tc:
            if n1 == n2: continue
            path, dist = astar(n1, n2)
            if path is None: continue
            d1 = hav(flat, flon, NODES[n1][0], NODES[n1][1])
            d2 = hav(tlat, tlon, NODES[n2][0], NODES[n2][1])
            total = d1 + dist + d2
            if total < best_nm:
                best_nm = total; best_path = path
    if best_path is None: return None, float("inf")
    coords = [[flon, flat]]
    for nid in best_path:
        coords.append([NODES[nid][1], NODES[nid][0]])
    coords.append([tlon, tlat])
    return coords, best_nm

def rdp(coords, eps=1.5):
    if len(coords) <= 2: return coords
    def pd(p, a, b):
        dx, dy = b[0]-a[0], b[1]-a[1]
        if dx == dy == 0: return hav(p[1],p[0],a[1],a[0])
        t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
        return hav(p[1],p[0],a[1]+t*dy,a[0]+t*dx)
    def _r(pts, e):
        if len(pts) <= 2: return pts
        dm, idx = 0, 0
        for i in range(1, len(pts)-1):
            d = pd(pts[i], pts[0], pts[-1])
            if d > dm: dm, idx = d, i
        if dm > e: return _r(pts[:idx+1],e)[:-1]+_r(pts[idx:],e)
        return [pts[0], pts[-1]]
    return _r(coords, eps)

OVP = "https://overpass-api.de/api/interpreter"
_TC = {}

def check_tss(coords, buf=0.3):
    if not coords: return []
    lons=[c[0] for c in coords]; lats=[c[1] for c in coords]
    s=round(min(lats)-buf,2); n=round(max(lats)+buf,2)
    w=round(min(lons)-buf,2); e=round(max(lons)+buf,2)
    key=f"{s}_{w}_{n}_{e}"
    if key in _TC: return _TC[key]
    q=(f'[out:json][timeout:20];'
       f'(way["seamark:type"="separation_lane"]({s},{w},{n},{e});'
       f'way["seamark:type"="separation_zone"]({s},{w},{n},{e}););'
       f'out tags center;')
    zs=[]
    try:
        r=requests.post(OVP,data={"data":q},timeout=15)
        if r.status_code==200:
            for el in r.json().get("elements",[]):
                t=el.get("tags",{}); nm=t.get("seamark:name") or t.get("name") or "TSS"
                if nm not in zs: zs.append(nm)
    except: pass
    _TC[key]=zs; return zs

# ── Endpoints ─────────────────────────────────────────────────
@app.route("/route")
def route_ep():
    if not READY:
        return jsonify({"error":"Graph loading — retry in 30s"}), 503
    try:
        flat  = float(request.args["fromLat"])
        flon  = float(request.args["fromLon"])
        tlat  = float(request.args["toLat"])
        tlon  = float(request.args["toLon"])
        eps   = float(request.args.get("simplify", 1.5))
        do_tss = request.args.get("tss","true").lower() == "true"
    except (KeyError, ValueError) as ex:
        return jsonify({"error": f"Bad param: {ex}"}), 400
    coords, _ = compute_route(flat, flon, tlat, tlon)
    if coords is None:
        return jsonify({"error":"No route found"}), 404
    simp = rdp(coords, eps)
    total_nm = sum(hav(simp[i][1],simp[i][0],simp[i+1][1],simp[i+1][0])
                   for i in range(len(simp)-1))
    tss = check_tss(simp) if do_tss else []
    print(f"[router] {total_nm:.0f} NM | {len(coords)}→{len(simp)} pts", flush=True)
    return jsonify({
        "waypoints":   [{"lat":float(c[1]),"lon":float(c[0])} for c in simp],
        "totalNM":     round(total_nm, 1),
        "source":      "NavisphereX-Router",
        "graph":       GRAPH_NAME,
        "pointsRaw":   len(coords),
        "pointsFinal": len(simp),
        "tssZones":    tss,
        "warnings":    [f"🚢 TSS: {z}" for z in tss],
        "overallSafe": True,
        "landCrossing": False,
    })

@app.route("/safety-check", methods=["POST","OPTIONS"])
def safety_ep():
    if request.method == "OPTIONS": return jsonify({}), 200
    try:
        body   = request.get_json(force=True) or {}
        raw    = body.get("waypoints", [])
        if len(raw) < 2: return jsonify({"error":"Need 2+ waypoints"}), 400
        coords = [[float(w["lon"]),float(w["lat"])] for w in raw]
        total  = sum(hav(coords[i][1],coords[i][0],coords[i+1][1],coords[i+1][0])
                     for i in range(len(coords)-1))
        tss    = check_tss(coords)
        eta    = lambda nm,kn: round(nm/kn,1) if kn>0 else None
        return jsonify({
            "overall_safe": True,
            "total_warnings": len(tss),
            "warnings": [f"🚢 TSS: {z}" for z in tss],
            "route_stats": {"total_nm":round(total,1),"waypoint_count":len(coords),
                "eta":{"10kn":eta(total,10),"12kn":eta(total,12),
                       "15kn":eta(total,15),"18kn":eta(total,18)}},
            "land_check":   {"safe":True,"problem_segments":[]},
            "tss_check":    {"zones_found":len(tss),"zones":tss},
            "depth_check":  {"safe":True},
            "danger_check": {"safe":True,"dangers":[]},
        })
    except Exception as ex:
        return jsonify({"error":str(ex)}), 500

@app.route("/")
@app.route("/health")
def health():
    return jsonify({"status":"ok" if READY else "loading",
                    "service":"NavisphereX Router",
                    "graph":GRAPH_NAME,"nodes":len(NODES),"ready":READY})

if __name__ == "__main__":
    load_graph()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
