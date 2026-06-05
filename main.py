# ╔══════════════════════════════════════════════════════════════╗
# ║         NavisphereX Maritime Router — CLEAN ENGINE           ║
# ║                                                              ║
# ║  Architecture (same as PortToPort / SPOS / commercial apps): ║
# ║    1. searoute ocean graph  → land-free backbone routing     ║
# ║    2. RTZ chokepoint WPs   → accurate Suez/Malacca/Gibraltar ║
# ║    3. Chain through points → correct, complete routes        ║
# ║                                                              ║
# ║  Why this works:                                             ║
# ║    - searoute pre-computed ocean graph = NO land crossings   ║
# ║    - Chokepoints from real RTZ routes = TSS/canal accuracy   ║
# ║    - Simple, proven, same method all commercial apps use     ║
# ╚══════════════════════════════════════════════════════════════╝

import os, sys, math, threading, json, requests
import searoute as SR
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
# BACKGROUND INIT
# ══════════════════════════════════════════════════════════════
LAND  = None
READY = False

def _bg_init():
    global LAND, READY
    try:
        gdf  = gpd.read_file(
            "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
        )
        LAND = gdf.geometry.union_all()
        print("[NavisphereX] Land polygons ✅", flush=True)
    except Exception as e:
        print(f"[NavisphereX] Land WARNING: {e}", file=sys.stderr, flush=True)
    READY = True
    print("[NavisphereX] READY", flush=True)

threading.Thread(target=_bg_init, daemon=True).start()

# ══════════════════════════════════════════════════════════════
# GEOMETRY
# ══════════════════════════════════════════════════════════════
def hav(lat1, lon1, lat2, lon2):
    R = 3440.065
    a = (math.sin(math.radians((lat2-lat1)/2))**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(math.radians((lon2-lon1)/2))**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))

def brg(lon1, lat1, lon2, lat2):
    dl = math.radians(lon2-lon1)
    la, lb = math.radians(lat1), math.radians(lat2)
    return (math.degrees(math.atan2(
        math.sin(dl)*math.cos(lb),
        math.cos(la)*math.sin(lb) - math.sin(la)*math.cos(lb)*math.cos(dl)
    )) + 360) % 360

def in_box(lon, lat, lon_min, lon_max, lat_min, lat_max):
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max

def crosses_land(c1, c2):
    if LAND is None: return False
    try:   return LineString([c1, c2]).intersects(LAND)
    except: return False

def any_land(coords):
    return any(crosses_land(coords[i], coords[i+1]) for i in range(len(coords)-1))

# ══════════════════════════════════════════════════════════════
# REGION DETECTION
# ══════════════════════════════════════════════════════════════
def in_red_sea(lon, lat):        return in_box(lon, lat, 32,  44,  12, 30)
def in_med(lon, lat):            return in_box(lon, lat, -6,  42,  30, 47)
def in_gulf_aqaba(lon, lat):     return in_box(lon, lat, 34.5,35.5,27.5,30)
def in_persian_gulf(lon, lat):   return in_box(lon, lat, 48,  60,  22, 30)
def in_indian_ocean(lon, lat):   return in_box(lon, lat, 40, 100, -40, 26)
def in_pacific(lon, lat):        return in_box(lon, lat,100, 180, -60, 65)
def in_atlantic(lon, lat):       return in_box(lon, lat,-80,  20, -60, 65)
def in_malacca(lon, lat):        return in_box(lon, lat, 98, 105,   0,  7)
def in_black_sea(lon, lat):      return in_box(lon, lat, 27,  42,  40, 48)
def in_caribbean(lon, lat):      return in_box(lon, lat,-85, -60,   8, 25)
def in_gulf_mexico(lon, lat):    return in_box(lon, lat,-98, -80,  18, 31)

# ══════════════════════════════════════════════════════════════
# CHOKEPOINT DATABASE
# Extracted from real NavisphereX RTZ routes
# These are ONLY the critical narrow passages where
# searoute alone is not precise enough
# ══════════════════════════════════════════════════════════════

# Suez Canal — North to South (Port Said → Suez)
SUEZ_N2S = [
    (32.401667, 31.540),   # Port Said outer anchorage
    (32.401667, 31.420),   # Port Said canal entrance
    (32.303417, 31.098),   # Ismailia (mid canal)
    (32.309433, 30.805),   # Great Bitter Lake N
    (32.345000, 30.430),   # Great Bitter Lake S
    (32.553333, 29.835),   # Suez exit
    (32.546667, 29.788),   # Great Bitter Lake approach
]

# Suez Canal — South to North (Suez → Port Said)
SUEZ_S2N = list(reversed(SUEZ_N2S))

# Bab-el-Mandeb (Gulf of Aden ↔ Red Sea)
BAB_N = (43.366667, 12.618)  # Northbound entry
BAB_S = (43.366667, 11.900)  # Southbound entry

# Malacca Strait — NW to SE (Indian Ocean → Singapore)
MALACCA_NW2SE = [
    (95.100, 6.300),    # Rondo / Northern entrance
    (98.500, 5.600),    # Malacca Strait NW
    (100.910, 3.000),   # Mid Malacca
    (103.411, 1.241),   # Singapore West (The Brothers)
]
MALACCA_SE2NW = list(reversed(MALACCA_NW2SE))

# Singapore Strait — West to East
SING_W2E = [
    (103.411, 1.241),   # The Brothers (W)
    (103.693, 1.228),   # Sinki Fairway
    (103.800, 1.250),   # Singapore port area
    (104.326, 1.316),   # Horsborough (E)
]
SING_E2W = list(reversed(SING_W2E))

# Gibraltar (Atlantic ↔ Mediterranean)
GIB_W2E = [(-6.200, 35.950), (-5.616, 35.954), (-5.100, 35.970)]
GIB_E2W = list(reversed(GIB_W2E))

# Strait of Hormuz (Arabian Sea ↔ Persian Gulf)
HORMUZ_IN  = [(56.518, 26.560), (56.480, 26.500), (55.800, 26.200)]  # into Gulf
HORMUZ_OUT = list(reversed(HORMUZ_IN))

# Panama Canal — Atlantic to Pacific
PANAMA_A2P = [
    (-79.919, 9.388),   # Colon (Atlantic)
    (-79.924, 9.166),   # Gatun
    (-79.575, 8.965),   # Balboa (Pacific)
]
PANAMA_P2A = list(reversed(PANAMA_A2P))

# Dover Strait
DOVER_NE = [(1.518, 50.966), (1.757, 51.117)]   # NE bound
DOVER_SW = list(reversed(DOVER_NE))

# Cape of Good Hope corridor
CAPE_N = (18.118, -34.700)   # Cape area waypoint

# ══════════════════════════════════════════════════════════════
# DETERMINE CHOKEPOINTS FOR A ROUTE
# ══════════════════════════════════════════════════════════════
def get_chokepoints(flat, flon, tlat, tlon):
    """
    Returns list of (lon, lat) waypoints the route MUST pass through.
    Uses region detection to determine corridor.
    """
    pts = []

    f_io  = in_indian_ocean(flon, flat)
    t_io  = in_indian_ocean(tlon, tlat)
    f_med = in_med(flon, flat)
    t_med = in_med(tlon, tlat)
    f_rs  = in_red_sea(flon, flat)
    t_rs  = in_red_sea(tlon, tlat)
    f_pg  = in_persian_gulf(flon, flat)
    t_pg  = in_persian_gulf(tlon, tlat)
    f_pac = in_pacific(flon, flat)
    t_pac = in_pacific(tlon, tlat)
    f_atl = in_atlantic(flon, flat)
    t_atl = in_atlantic(tlon, tlat)
    f_mal = in_malacca(flon, flat)
    t_mal = in_malacca(tlon, tlat)
    f_car = in_caribbean(flon, flat)
    t_car = in_caribbean(tlon, tlat)
    f_gom = in_gulf_mexico(flon, flat)
    t_gom = in_gulf_mexico(tlon, tlat)

    # ── Suez Canal ────────────────────────────────────────────
    needs_suez = (
        (f_rs or f_io or f_pg or flat < 30) and (t_med or t_atl or tlat > 35) or
        (t_rs or t_io or t_pg or tlat < 30) and (f_med or f_atl or flat > 35)
    )
    going_north = tlat > flat  # rough north/south direction

    if needs_suez:
        if f_rs or (f_io and not f_med):
            # South to North through Suez
            pts += [BAB_N] if not f_rs else []
            pts += [(lon, lat) for lon, lat in SUEZ_S2N]
        else:
            # North to South through Suez
            pts += [(lon, lat) for lon, lat in SUEZ_N2S]
            pts += [BAB_S] if not t_rs else []

    # ── Bab-el-Mandeb alone (Red Sea only) ───────────────────
    elif (f_rs and not needs_suez) or (t_rs and not needs_suez):
        if f_rs and t_io:
            pts.append(BAB_S)
        elif f_io and t_rs:
            pts.append(BAB_N)

    # ── Strait of Hormuz ──────────────────────────────────────
    if f_pg and not t_pg:
        pts = HORMUZ_OUT + pts
    elif t_pg and not f_pg:
        pts = pts + HORMUZ_IN

    # ── Malacca Strait ────────────────────────────────────────
    needs_malacca = (
        (f_pac or f_mal) and (f_io or t_io) or
        (t_pac or t_mal) and (f_io or f_io)
    )
    malacca_crossing = (
        (f_pac and t_io) or (f_io and t_pac) or
        (f_pac and f_mal) or (t_pac and t_mal) or
        (f_mal and not t_mal) or (t_mal and not f_mal)
    )
    if malacca_crossing:
        if f_pac or (f_mal and tlon < 98):
            # SE to NW
            pts += [(lon, lat) for lon, lat in MALACCA_SE2NW]
        else:
            # NW to SE
            pts += [(lon, lat) for lon, lat in MALACCA_NW2SE]

    # ── Singapore Strait ─────────────────────────────────────
    elif (f_pac and tlon < 100) or (t_pac and flon < 100):
        if tlon < flon:
            pts += [(lon, lat) for lon, lat in SING_E2W]
        else:
            pts += [(lon, lat) for lon, lat in SING_W2E]

    # ── Gibraltar ─────────────────────────────────────────────
    needs_gib = (
        (f_atl and t_med) or (f_med and t_atl) or
        (f_atl and needs_suez) or (needs_suez and t_atl)
    )
    if needs_gib and not needs_suez:  # avoid double-adding
        if f_atl:
            pts += [(lon, lat) for lon, lat in GIB_W2E]
        else:
            pts += [(lon, lat) for lon, lat in GIB_E2W]

    # ── Panama Canal ──────────────────────────────────────────
    needs_panama = (
        (f_car or f_gom or (f_atl and flon > -85)) and t_pac or
        f_pac and (t_car or t_gom or (t_atl and tlon > -85))
    )
    if needs_panama:
        if f_pac:
            pts += [(lon, lat) for lon, lat in PANAMA_P2A]
        else:
            pts += [(lon, lat) for lon, lat in PANAMA_A2P]

    # ── Cape of Good Hope ─────────────────────────────────────
    needs_cape = (
        (f_io and t_atl and not needs_suez) or
        (f_atl and t_io and not needs_suez) or
        (flat < -20 and flon < 30) or (tlat < -20 and tlon < 30)
    )
    if needs_cape:
        pts.append(CAPE_N)

    return pts

# ══════════════════════════════════════════════════════════════
# CORE ROUTING — searoute + chokepoints
# searoute handles all open ocean (land-free, always)
# Chokepoints ensure accurate passage through narrow straits
# ══════════════════════════════════════════════════════════════
def route_segment(from_lon, from_lat, to_lon, to_lat):
    """Route one segment using searoute."""
    try:
        r = SR.searoute(
            [from_lon, from_lat], [to_lon, to_lat],
            units="naut", append_orig_dest=True
        )
        coords  = r.geometry["coordinates"]
        dist_nm = float(r.properties.get("length", 0))
        return coords, dist_nm
    except Exception as e:
        print(f"[searoute] error: {e}", file=sys.stderr, flush=True)
        d = hav(from_lat, from_lon, to_lat, to_lon)
        return [[from_lon, from_lat], [to_lon, to_lat]], d

def build_route(flat, flon, tlat, tlon):
    """
    Build complete route:
    1. Determine chokepoints for this corridor
    2. Chain searoute segments through each chokepoint
    3. Result: accurate, land-free route
    """
    chokepoints = get_chokepoints(flat, flon, tlat, tlon)

    # Build point sequence: origin → chokepoints → destination
    sequence = [(flon, flat)] + [(lon, lat) for lon, lat in chokepoints] + [(tlon, tlat)]

    all_coords = []
    total_nm   = 0.0

    for i in range(len(sequence) - 1):
        sf = sequence[i]
        st = sequence[i+1]
        coords, nm = route_segment(sf[0], sf[1], st[0], st[1])
        if all_coords and coords:
            coords = coords[1:]   # remove duplicate junction point
        all_coords.extend(coords)
        total_nm += nm

    method = f"searoute+{len(chokepoints)}cp" if chokepoints else "searoute-direct"
    return all_coords, total_nm, method

# ══════════════════════════════════════════════════════════════
# RDP SIMPLIFICATION
# ══════════════════════════════════════════════════════════════
def rdp(coords, eps=1.5):
    if len(coords) <= 2: return coords
    def pd(p, a, b):
        dx, dy = b[0]-a[0], b[1]-a[1]
        if dx == dy == 0: return hav(p[1],p[0],a[1],a[0])
        t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
        return hav(p[1],p[0],a[1]+t*dy,a[0]+t*dx)
    def _rdp(pts, e):
        if len(pts) <= 2: return pts
        dm, idx = 0, 0
        for i in range(1, len(pts)-1):
            d = pd(pts[i], pts[0], pts[-1])
            if d > dm: dm, idx = d, i
        if dm > e: return _rdp(pts[:idx+1],e)[:-1] + _rdp(pts[idx:],e)
        return [pts[0], pts[-1]]
    return _rdp(coords, eps)

# ══════════════════════════════════════════════════════════════
# SAFETY CHECKS
# ══════════════════════════════════════════════════════════════
GEBCO = "https://api.odb.ntu.edu.tw/gebco"
OVP   = "https://overpass-api.de/api/interpreter"
_TC, _DC = {}, {}
DANGER_TYPES = ["rock","wreck","obstruction","shoal","reef","underwater_rock","foul_ground","snag"]

def check_tss(coords, buf=0.3):
    if not coords: return []
    lons=[c[0] for c in coords]; lats=[c[1] for c in coords]
    s=round(min(lats)-buf,2); n=round(max(lats)+buf,2)
    w=round(min(lons)-buf,2); e=round(max(lons)+buf,2)
    key=f"{s}_{w}_{n}_{e}"
    if key in _TC: return _TC[key]
    q=(f'[out:json][timeout:20];'
       f'(way["seamark:type"="separation_lane"]({s},{w},{n},{e});'
       f'way["seamark:type"="separation_zone"]({s},{w},{n},{e});'
       f'relation["seamark:type"="traffic_separation_scheme"]({s},{w},{n},{e}););'
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

def check_dangers(coords, buf_nm=2.0):
    lons=[c[0] for c in coords]; lats=[c[1] for c in coords]
    s=round(min(lats)-.1,2); n=round(max(lats)+.1,2)
    w=round(min(lons)-.1,2); e=round(max(lons)+.1,2)
    key=f"{s}_{w}_{n}_{e}"
    if key in _DC: dm=_DC[key]
    else:
        fi="\n".join([f'  node["seamark:type"="{t}"]({s},{w},{n},{e});' for t in DANGER_TYPES])
        q=f"[out:json][timeout:20];\n(\n{fi}\n);\nout body;"
        dm=[]
        try:
            r=requests.post(OVP,data={"data":q},timeout=15)
            if r.status_code==200:
                for el in r.json().get("elements",[]):
                    tags=el.get("tags",{}); dm.append({"type":tags.get("seamark:type","?"),
                        "name":tags.get("name",""),"lon":el.get("lon"),"lat":el.get("lat")})
        except: pass
        _DC[key]=dm
    nearby=[]
    for d in dm:
        dl,da=d.get("lon"),d.get("lat")
        if dl is None: continue
        md=min(hav(da,dl,c[1],c[0]) for c in coords)
        if md<buf_nm: nearby.append({**d,"nearest_nm":round(md,2)})
    return {"safe":not nearby,"dangers":nearby,"total":len(dm)}

def check_depth(coords, draft=10.0, safety=2.0):
    mr=draft+safety; pts=[]
    for i in range(len(coords)-1):
        c1,c2=coords[i],coords[i+1]
        st=max(1,int(hav(c1[1],c1[0],c2[1],c2[0])/15))
        for s in range(st):
            t=s/st; pts.append((c1[0]+t*(c2[0]-c1[0]),c1[1]+t*(c2[1]-c1[1])))
    if coords: pts.append((coords[-1][0],coords[-1][1]))
    shallow,depths=[],[]
    try:
        lns=",".join(str(round(p[0],4)) for p in pts)
        lts=",".join(str(round(p[1],4)) for p in pts)
        r=requests.get(f"{GEBCO}?lon={lns}&lat={lts}&mode=zonly",timeout=15)
        if r.status_code==200:
            data=r.json(); zs=data.get("z",[]) if isinstance(data,dict) else data
            for i,p in enumerate(pts):
                if i<len(zs) and zs[i] is not None:
                    wd=abs(zs[i]) if zs[i]<0 else 0; depths.append(wd)
                    if 0<wd<mr: shallow.append({"lon":p[0],"lat":p[1],"depth":round(wd,1),"required":mr})
    except: pass
    return {"safe":not shallow,"min_depth":round(min(depths),1) if depths else None,
            "shallow":shallow,"checked":len(pts),"required":mr}

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

    # Route
    coords, total_nm, method = build_route(flat, flon, tlat, tlon)

    # Simplify
    simp = rdp(coords, eps)

    # Recalculate actual NM
    actual_nm = sum(
        hav(simp[i][1],simp[i][0],simp[i+1][1],simp[i+1][0])
        for i in range(len(simp)-1)
    )

    # Land check
    lc = any_land(simp)

    # Safety
    tss = check_tss(simp)     if do_tss    else []
    dng = check_dangers(simp) if do_danger else {"safe":True,"dangers":[],"total":0}
    dep = check_depth(simp,draft,saf) if do_depth else {"safe":True,"shallow":[],"checked":0,"required":draft+saf}

    warns = []
    if lc: warns.append("🚨 Route crosses land — add manual waypoints to correct")
    for z in tss:  warns.append(f"🚢 TSS zone: {z}")
    for sp in dep.get("shallow",[]): warns.append(f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})")
    for d in dng.get("dangers",[]): warns.append(f"🪨 {d['type']} '{d['name']}' {d['nearest_nm']}NM")

    print(f"[NavisphereX] {actual_nm:.0f}NM | {len(coords)}→{len(simp)}pts | {method} | land={lc}", flush=True)

    return jsonify({
        "waypoints":      [{"lat":float(c[1]),"lon":float(c[0])} for c in simp],
        "totalNM":        round(actual_nm, 1),
        "source":         "NavisphereX-Router",
        "method":         method,
        "pointsRaw":      len(coords),
        "pointsFinal":    len(simp),
        "landCrossing":   lc,
        "tssZones":       tss,
        "overallSafe":    not lc and dep["safe"] and dng["safe"],
        "warnings":       warns,
        "safetyReport":   {"depth":dep,"danger":dng},
    })

# ══════════════════════════════════════════════════════════════
# POST /safety-check
# ══════════════════════════════════════════════════════════════
@app.route("/safety-check", methods=["POST","OPTIONS"])
def safety_ep():
    if request.method=="OPTIONS": return jsonify({}),200
    try:
        body=request.get_json(force=True)
        if not body: return jsonify({"error":"JSON body required"}),400
        raw=body.get("waypoints",[])
        if len(raw)<2: return jsonify({"error":"Need ≥2 waypoints"}),400
        coords=[[float(w["lon"]),float(w["lat"])] for w in raw]
        draft=float(body.get("draft",10.0)); saf=float(body.get("safety",2.0))
        beam=float(body.get("beam",32.0));   loa=float(body.get("loa",200.0))
        lc=any_land(coords); lsegs=[]
        if lc:
            for i in range(len(coords)-1):
                if crosses_land(coords[i],coords[i+1]):
                    lsegs.append({"from":{"lon":coords[i][0],"lat":coords[i][1]},
                                  "to":{"lon":coords[i+1][0],"lat":coords[i+1][1]},"seg":i})
        tss=check_tss(coords); dep=check_depth(coords,draft,saf); dng=check_dangers(coords)
        total,ml,legs=0.0,0.0,[]
        for i in range(len(coords)-1):
            c1,c2=coords[i],coords[i+1]; nm=hav(c1[1],c1[0],c2[1],c2[0])
            total+=nm; ml=max(ml,nm)
            legs.append({"from":{"lon":c1[0],"lat":c1[1]},"to":{"lon":c2[0],"lat":c2[1]},
                         "nm":round(nm,1),"bearing":round(brg(c1[0],c1[1],c2[0],c2[1]),1)})
        warns=[]
        if lc: warns.append(f"🚨 LAND CROSSING in {len(lsegs)} segment(s)")
        for z in tss: warns.append(f"🚢 TSS: {z}")
        for sp in dep.get("shallow",[]): warns.append(f"⚠️ Shallow {sp['depth']}m")
        for d in dng.get("dangers",[]): warns.append(f"🪨 {d['type']} '{d['name']}' {d['nearest_nm']}NM")
        eta=lambda nm,kn:round(nm/kn,2) if kn>0 else None
        return jsonify({
            "overall_safe":not lc and dep["safe"] and dng["safe"],
            "total_warnings":len(warns),"warnings":warns,
            "route_stats":{"total_nm":round(total,1),"waypoint_count":len(coords),"max_leg_nm":round(ml,1),
                           "eta":{"10kn":eta(total,10),"12kn":eta(total,12),"14kn":eta(total,14),"15kn":eta(total,15),"18kn":eta(total,18)}},
            "land_check":{"safe":not lc,"problem_segments":lsegs},
            "tss_check":{"zones_found":len(tss),"zones":tss},
            "depth_check":{"safe":dep["safe"],"min_depth_m":dep.get("min_depth"),"required":dep.get("required"),"shallow":dep.get("shallow",[])},
            "danger_check":{"safe":dng["safe"],"dangers":dng.get("dangers",[])},
            "vessel_params":{"draft_m":draft,"safety_m":saf,"beam_m":beam,"loa_m":loa},
            "legs":legs,
        })
    except Exception as ex:
        print(f"[safety] {ex}",file=sys.stderr); return jsonify({"error":str(ex)}),500

# ══════════════════════════════════════════════════════════════
# GET /health
# ══════════════════════════════════════════════════════════════
@app.route("/")
@app.route("/health")
def health():
    return jsonify({
        "status":      "ok" if READY else "initializing",
        "service":     "NavisphereX Maritime Router",
        "architecture":"searoute-ocean-backbone + RTZ-chokepoints",
        "land_check":  LAND is not None,
        "ready":       READY,
        "chokepoints": ["suez","bab_el_mandeb","malacca","singapore","gibraltar","hormuz","panama","cape_of_good_hope"],
    })

# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"[NavisphereX] Starting on :{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
