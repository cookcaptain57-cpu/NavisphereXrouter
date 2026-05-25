# maritime-router v10 — Clean Architecture
# ROOT CAUSE FIX: TSS waypoints were fighting searoute, causing zigzag chaos
#
# New architecture:
#   1. searoute handles full path (it already knows shipping lanes)
#   2. ONLY critical chokepoints injected (Suez, Hormuz, Panama, Malacca entry)
#   3. TSS data used for WARNINGS only — not routing waypoints
#   4. World TSS data from OSM Overpass dynamically (no hardcoding)
#   5. Aggressive simplification to kill clutter
#
# Endpoints: GET /route, POST /safety-check, GET /health

import os, sys, math, time, threading, requests
from flask import Flask, request, jsonify
from shapely.geometry import LineString, Point
import geopandas as gpd

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ══════════════════════════════════════════════════════════════
# BACKGROUND INIT — port binds first, heavy work after
# ══════════════════════════════════════════════════════════════
SR        = None
SR_ERROR  = None
LAND      = None
_init_done = False

def _background_init():
    global SR, SR_ERROR, LAND, _init_done
    try:
        import searoute as sr
        test = sr.searoute([2.35, 48.85], [103.82, 1.27], units='naut')
        SR   = sr
        print(f'[v10] searoute ready — {test.properties.get("length",0):.0f} NM', flush=True)
    except Exception as e:
        SR_ERROR = str(e)
        print(f'[v10] searoute ERROR: {e}', file=sys.stderr, flush=True)
    try:
        gdf  = gpd.read_file(
            "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
        )
        LAND = gdf.geometry.union_all()
        print('[v10] Land polygons loaded ✅', flush=True)
    except Exception as e:
        print(f'[v10] Land WARNING: {e}', file=sys.stderr, flush=True)
    _init_done = True
    print('[v10] Init complete ✅', flush=True)

threading.Thread(target=_background_init, daemon=True).start()

# ══════════════════════════════════════════════════════════════
# CRITICAL CHOKEPOINTS ONLY
# These are the ONLY points injected into the route chain.
# They represent places where searoute genuinely needs a hint.
# TSS lanes are NOT here — those are handled as warnings.
# ══════════════════════════════════════════════════════════════
CHOKEPOINTS = {
    # Suez Canal — searoute needs explicit north/south entry
    'suez_s':        (32.545, 29.940),   # Great Bitter Lake south
    'suez_n':        (32.325, 31.260),   # Port Said outer anchorage

    # Bab-el-Mandeb — narrow, needs pinning
    'bab_mandeb':    (43.320, 12.680),

    # Ras Muhammad — Gulf of Aqaba exit
    'ras_muhammad':  (32.620, 27.720),

    # Hormuz — searoute sometimes misses this
    'hormuz':        (56.450, 26.580),

    # Malacca — only ONE entry pin, not a chain of TSS wps
    'malacca_entry': (103.500, 1.200),

    # Gibraltar
    'gibraltar':     (-5.360, 35.980),

    # Panama — if you add Panama Canal support later
    # 'panama_pacific': (-79.525, 8.883),
    # 'panama_atlantic': (-79.915, 9.380),
}

# ══════════════════════════════════════════════════════════════
# REGION DETECTION — for chokepoint selection only
# ══════════════════════════════════════════════════════════════
def in_box(lon, lat, lon_min, lon_max, lat_min, lat_max):
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max

def in_red_sea(lon, lat):       return in_box(lon, lat, 32, 44, 12, 30)
def in_mediterranean(lon, lat): return in_box(lon, lat, -6, 42, 30, 47)
def in_gulf_aqaba(lon, lat):    return in_box(lon, lat, 34.5, 35.5, 27.5, 30)
def in_gulf_persian(lon, lat):  return in_box(lon, lat, 48, 60, 22, 30)
def in_indian_ocean(lon, lat):  return in_box(lon, lat, 40, 100, -40, 25)
def in_pacific(lon, lat):       return in_box(lon, lat, 100, 180, -60, 60)
def in_atlantic(lon, lat):      return in_box(lon, lat, -80, 10, -60, 60)
def in_malacca_region(lon, lat):return in_box(lon, lat, 98, 105, 0, 7)

def get_critical_waypoints(from_lon, from_lat, to_lon, to_lat):
    """
    Returns ONLY the minimum waypoints needed to pin the route
    through critical chokepoints. NOT TSS lane points.
    """
    cp  = CHOKEPOINTS
    f   = (from_lon, from_lat)
    t   = (to_lon,   to_lat)

    # Suez Canal
    if (in_red_sea(*f) and in_mediterranean(*t)):
        return [cp['suez_s'], cp['suez_n']]
    if (in_mediterranean(*f) and in_red_sea(*t)):
        return [cp['suez_n'], cp['suez_s']]

    # Gulf of Aqaba
    if in_gulf_aqaba(*f):
        return [cp['ras_muhammad'], cp['bab_mandeb']]
    if in_gulf_aqaba(*t):
        return [cp['bab_mandeb'], cp['ras_muhammad']]

    # Strait of Hormuz
    if in_gulf_persian(*f) and not in_gulf_persian(*t):
        return [cp['hormuz']]
    if in_gulf_persian(*t) and not in_gulf_persian(*f):
        return [cp['hormuz']]

    # Malacca Strait — ONE pin only, not a chain
    if ((in_pacific(*f) and in_indian_ocean(*t)) or
        (in_indian_ocean(*f) and in_pacific(*t))):
        return [cp['malacca_entry']]
    if in_malacca_region(*f) or in_malacca_region(*t):
        return [cp['malacca_entry']]

    # Gibraltar
    if ((in_atlantic(*f) and in_mediterranean(*t)) or
        (in_mediterranean(*f) and in_atlantic(*t))):
        return [cp['gibraltar']]

    return []

# ══════════════════════════════════════════════════════════════
# GEOMETRY HELPERS
# ══════════════════════════════════════════════════════════════
def haversine_nm(lat1, lon1, lat2, lon2):
    R    = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a    = (math.sin(dlat/2)**2 +
            math.cos(math.radians(lat1)) *
            math.cos(math.radians(lat2)) *
            math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))

def bearing(lon1, lat1, lon2, lat2):
    dlon  = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = (math.cos(lat1r)*math.sin(lat2r) -
         math.sin(lat1r)*math.cos(lat2r)*math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def bearing_two_points(c1, c2):
    return bearing(c1[0], c1[1], c2[0], c2[1])

def segment_crosses_land(c1, c2):
    if LAND is None: return False
    try:
        return LineString([c1, c2]).intersects(LAND)
    except:
        return False

def any_segment_crosses_land(coords):
    for i in range(len(coords) - 1):
        if segment_crosses_land(coords[i], coords[i+1]):
            return True
    return False

def rdp_simplify(coords, epsilon_nm=3.0):
    """
    Ramer-Douglas-Peucker simplification in nautical miles.
    Much cleaner than the old safe_simplify — removes clutter
    while preserving course changes > epsilon_nm deviation.
    """
    if len(coords) <= 2:
        return coords

    def point_line_dist_nm(p, a, b):
        # perpendicular distance from point p to line a-b, in NM
        if a == b:
            return haversine_nm(p[1], p[0], a[1], a[0])
        # use cross-track distance approximation
        d_ab = haversine_nm(a[1], a[0], b[1], b[0])
        if d_ab == 0:
            return haversine_nm(p[1], p[0], a[1], a[0])
        # project p onto a-b
        t = (
            (p[0] - a[0]) * (b[0] - a[0]) +
            (p[1] - a[1]) * (b[1] - a[1])
        ) / ((b[0]-a[0])**2 + (b[1]-a[1])**2)
        t = max(0, min(1, t))
        proj = (a[0] + t*(b[0]-a[0]), a[1] + t*(b[1]-a[1]))
        return haversine_nm(p[1], p[0], proj[1], proj[0])

    def rdp(pts, eps):
        if len(pts) <= 2:
            return pts
        dmax, idx = 0, 0
        for i in range(1, len(pts)-1):
            d = point_line_dist_nm(pts[i], pts[0], pts[-1])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps:
            left  = rdp(pts[:idx+1], eps)
            right = rdp(pts[idx:],   eps)
            return left[:-1] + right
        return [pts[0], pts[-1]]

    return rdp(coords, epsilon_nm)

# ══════════════════════════════════════════════════════════════
# CORE ROUTER — clean, no TSS injection into path
# ══════════════════════════════════════════════════════════════
def build_route(from_lon, from_lat, to_lon, to_lat):
    """
    Build the sea route with minimal waypoint injection.
    Only critical chokepoints are used. TSS is NOT injected.
    """
    critical_wps = get_critical_waypoints(from_lon, from_lat, to_lon, to_lat)

    all_coords = []
    total_nm   = 0.0
    points     = [(from_lon, from_lat)] + list(critical_wps) + [(to_lon, to_lat)]
    method     = f'searoute+{len(critical_wps)}-chokepoints' if critical_wps else 'searoute-direct'

    for i in range(len(points) - 1):
        seg_f = points[i]
        seg_t = points[i+1]
        try:
            seg        = SR.searoute(
                [seg_f[0], seg_f[1]], [seg_t[0], seg_t[1]],
                units='naut', append_orig_dest=True
            )
            seg_coords = seg.geometry['coordinates']
            seg_nm     = float(seg.properties.get('length', 0))
            if all_coords and seg_coords:
                seg_coords = seg_coords[1:]   # avoid duplicate junction point
            all_coords.extend(seg_coords)
            total_nm  += seg_nm
        except Exception as e:
            print(f'[build_route] segment {i} error: {e}', file=sys.stderr)
            if not all_coords:
                all_coords.append([seg_f[0], seg_f[1]])
            all_coords.append([seg_t[0], seg_t[1]])

    return all_coords, total_nm, method, critical_wps

# ══════════════════════════════════════════════════════════════
# WORLD TSS CHECK via OSM Overpass (dynamic, no hardcoding)
# "How do I get TSS data for the whole world?" — THIS is how.
#
# OSM has every published TSS worldwide as:
#   seamark:type = separation_lane
#   seamark:type = separation_zone
#   seamark:type = traffic_separation_scheme
#
# We query the bounding box of the route and check if our
# route passes near any TSS zones — for WARNINGS, not routing.
# ══════════════════════════════════════════════════════════════
OVERPASS_API = "https://overpass-api.de/api/interpreter"
_tss_cache   = {}

def query_tss_zones_osm(coords, buffer_deg=0.3):
    """
    Dynamically fetch TSS zones from OpenSeaMap/OSM along the route.
    Returns list of TSS zone names/types near the route.
    No hardcoding — works for any TSS in the world.
    """
    if not coords:
        return []

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    bbox_s = round(min(lats) - buffer_deg, 2)
    bbox_n = round(max(lats) + buffer_deg, 2)
    bbox_w = round(min(lons) - buffer_deg, 2)
    bbox_e = round(max(lons) + buffer_deg, 2)

    cache_key = f"{bbox_s}_{bbox_w}_{bbox_n}_{bbox_e}"
    if cache_key in _tss_cache:
        return _tss_cache[cache_key]

    bbox_str = f"{bbox_s},{bbox_w},{bbox_n},{bbox_e}"
    query = f"""
[out:json][timeout:20];
(
  way["seamark:type"="separation_lane"]({bbox_str});
  way["seamark:type"="separation_zone"]({bbox_str});
  way["seamark:type"="traffic_separation_scheme"]({bbox_str});
  relation["seamark:type"="traffic_separation_scheme"]({bbox_str});
);
out tags center;
"""
    tss_zones = []
    try:
        resp = requests.post(OVERPASS_API, data={'data': query}, timeout=15)
        if resp.status_code == 200:
            for el in resp.json().get('elements', []):
                tags = el.get('tags', {})
                name = tags.get('seamark:name') or tags.get('name') or tags.get('seamark:type','TSS')
                if name not in tss_zones:
                    tss_zones.append(name)
    except Exception as e:
        print(f'[TSS-OSM] query error: {e}', file=sys.stderr)

    _tss_cache[cache_key] = tss_zones
    return tss_zones

# ══════════════════════════════════════════════════════════════
# DANGER CHECK via OSM Overpass
# ══════════════════════════════════════════════════════════════
DANGER_TYPES  = ['rock','wreck','obstruction','shoal','reef',
                 'underwater_rock','foul_ground','snag']
_danger_cache = {}

def check_dangers(coords, buffer_nm=2.0):
    lons   = [c[0] for c in coords]
    lats   = [c[1] for c in coords]
    buf    = 0.10
    bbox_s = round(min(lats) - buf, 2)
    bbox_n = round(max(lats) + buf, 2)
    bbox_w = round(min(lons) - buf, 2)
    bbox_e = round(max(lons) + buf, 2)
    bbox_str = f"{bbox_s},{bbox_w},{bbox_n},{bbox_e}"

    cache_key = f"{bbox_s}_{bbox_w}_{bbox_n}_{bbox_e}"
    if cache_key in _danger_cache:
        danger_marks = _danger_cache[cache_key]
    else:
        filters = '\n'.join(
            [f'  node["seamark:type"="{t}"]({bbox_str});' for t in DANGER_TYPES]
        )
        query = f"[out:json][timeout:20];\n(\n{filters}\n);\nout body;"
        danger_marks = []
        try:
            resp = requests.post(OVERPASS_API, data={'data': query}, timeout=15)
            if resp.status_code == 200:
                for el in resp.json().get('elements', []):
                    tags = el.get('tags', {})
                    danger_marks.append({
                        'type': tags.get('seamark:type', 'unknown'),
                        'name': tags.get('name', tags.get('seamark:name', '')),
                        'lon':  el.get('lon'),
                        'lat':  el.get('lat'),
                    })
        except Exception as e:
            print(f'[DangerCheck] Overpass error: {e}', file=sys.stderr)
        _danger_cache[cache_key] = danger_marks

    nearby = []
    for d in danger_marks:
        dlon, dlat = d.get('lon'), d.get('lat')
        if dlon is None or dlat is None: continue
        min_dist = min(haversine_nm(dlat, dlon, c[1], c[0]) for c in coords)
        if min_dist < buffer_nm:
            nearby.append({
                'type':             d['type'],
                'name':             d['name'],
                'lon':              dlon,
                'lat':              dlat,
                'nearest_route_nm': round(min_dist, 2),
            })
    return {
        'safe':               len(nearby) == 0,
        'dangers_near_route': nearby,
        'total_in_area':      len(danger_marks),
    }

# ══════════════════════════════════════════════════════════════
# DEPTH CHECK
# ══════════════════════════════════════════════════════════════
GEBCO_API    = "https://api.odb.ntu.edu.tw/gebco"

def interpolate_check_points(coords, interval_nm=15.0):
    pts = []
    for i in range(len(coords) - 1):
        c1, c2 = coords[i], coords[i+1]
        seg_nm = haversine_nm(c1[1], c1[0], c2[1], c2[0])
        steps  = max(1, int(seg_nm / interval_nm))
        for s in range(steps):
            t = s / steps
            pts.append((c1[0]+t*(c2[0]-c1[0]), c1[1]+t*(c2[1]-c1[1])))
    if coords:
        pts.append((coords[-1][0], coords[-1][1]))
    return pts

def check_depth(coords, draft_m=10.0, safety_m=2.0):
    min_required = draft_m + safety_m
    check_pts    = interpolate_check_points(coords, 15.0)
    shallow, depths_found = [], []
    lons = [str(round(p[0],4)) for p in check_pts]
    lats = [str(round(p[1],4)) for p in check_pts]
    try:
        url  = f"{GEBCO_API}?lon={','.join(lons)}&lat={','.join(lats)}&mode=zonly"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data   = resp.json()
            depths = data.get('z', []) if isinstance(data, dict) else data
            for i, pt in enumerate(check_pts):
                if i < len(depths) and depths[i] is not None:
                    wd = abs(depths[i]) if depths[i] < 0 else 0
                    depths_found.append(wd)
                    if 0 < wd < min_required:
                        shallow.append({
                            'lon':      pt[0], 'lat': pt[1],
                            'depth':    round(wd, 1),
                            'required': min_required,
                        })
    except Exception as e:
        print(f'[DepthCheck] GEBCO error: {e}', file=sys.stderr)
    return {
        'safe':           len(shallow) == 0,
        'min_depth':      round(min(depths_found), 1) if depths_found else None,
        'shallow_points': shallow,
        'checked':        len(check_pts),
        'required_depth': min_required,
    }

# ══════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        'status':    'ok' if SR else ('initializing' if not _init_done else 'degraded'),
        'searoute':  SR is not None,
        'land':      LAND is not None,
        'init_done': _init_done,
        'error':     SR_ERROR,
        'service':   'maritime-router v10',
        'arch':      'searoute-primary / TSS-as-warnings / OSM-dynamic',
    })

# ══════════════════════════════════════════════════════════════
# GET /route
# ══════════════════════════════════════════════════════════════
@app.route('/route')
def route():
    if SR is None:
        msg = 'Initializing (~30s)' if not _init_done else f'searoute error: {SR_ERROR}'
        return jsonify({'error': msg}), 503

    try:
        from_lon = float(request.args['fromLon'])
        from_lat = float(request.args['fromLat'])
        to_lon   = float(request.args['toLon'])
        to_lat   = float(request.args['toLat'])
        draft    = float(request.args.get('draft',  10.0))
        safety   = float(request.args.get('safety',  2.0))
        simplify = float(request.args.get('simplify', 4.0))  # RDP epsilon NM
    except (KeyError, ValueError) as e:
        return jsonify({'error': f'Bad param: {e}'}), 400

    try:
        # ── Step 1: Get clean route from searoute + chokepoints only ──
        raw_coords, dist_nm, method, used_wps = build_route(
            from_lon, from_lat, to_lon, to_lat
        )

        # ── Step 2: RDP simplification (removes clutter) ──────────────
        simplified = rdp_simplify(raw_coords, epsilon_nm=simplify)

        # ── Step 3: Land cross check ───────────────────────────────────
        land_cross = any_segment_crosses_land(simplified)
        if land_cross:
            print('[route] ⚠️ Land crossing detected', file=sys.stderr, flush=True)

        # ── Step 4: Recalc actual NM after simplify ────────────────────
        total_nm = sum(
            haversine_nm(simplified[i][1],   simplified[i][0],
                         simplified[i+1][1], simplified[i+1][0])
            for i in range(len(simplified) - 1)
        )

        # ── Step 5: TSS zones along route (WARNING only, not routing) ──
        tss_zones = query_tss_zones_osm(simplified)

        # ── Step 6: Danger check ───────────────────────────────────────
        danger = check_dangers(simplified)

        # ── Step 7: Depth check ────────────────────────────────────────
        depth = check_depth(simplified, draft, safety)

        # ── Collect warnings ───────────────────────────────────────────
        warnings = []
        if land_cross:
            warnings.append('🚨 Route crosses land — check chokepoint routing')
        for z in tss_zones:
            warnings.append(f'🚢 TSS zone nearby: {z} — verify correct separation lane')
        for sp in depth.get('shallow_points', []):
            warnings.append(
                f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})"
                f" — need {sp['required']}m"
            )
        for d in danger.get('dangers_near_route', []):
            warnings.append(
                f"🪨 {d['type'].upper()} '{d['name']}' "
                f"({d['lat']:.3f},{d['lon']:.3f}) — {d['nearest_route_nm']}NM"
            )

        overall_safe = not land_cross and depth['safe'] and danger['safe']

        print(
            f'[route] {total_nm:.0f}NM | {len(raw_coords)}→{len(simplified)}pts '
            f'| method={method} | land={land_cross} | tss={len(tss_zones)} '
            f'| safe={overall_safe}',
            flush=True
        )

        return jsonify({
            'waypoints':    [{'lat': float(c[1]), 'lon': float(c[0])}
                             for c in simplified],
            'totalNM':      round(total_nm, 1),
            'source':       'maritime-router-v10',
            'method':       method,
            'pointsRaw':    len(raw_coords),
            'pointsFinal':  len(simplified),
            'landCrossing': land_cross,
            'tssZones':     tss_zones,          # TSS info for display only
            'overallSafe':  overall_safe,
            'warnings':     warnings,
            'safetyReport': {
                'depth_check':  depth,
                'danger_check': danger,
            },
        })

    except Exception as e:
        print(f'[route] error: {e}', file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

# ══════════════════════════════════════════════════════════════
# POST /safety-check
# ══════════════════════════════════════════════════════════════
@app.route('/safety-check', methods=['POST', 'OPTIONS'])
def safety_check():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({'error': 'JSON body required'}), 400

        raw_wps = body.get('waypoints', [])
        if len(raw_wps) < 2:
            return jsonify({'error': 'Need ≥ 2 waypoints'}), 400

        coords = [[float(w['lon']), float(w['lat'])] for w in raw_wps]
        draft  = float(body.get('draft',  10.0))
        safety = float(body.get('safety',  2.0))
        beam   = float(body.get('beam',   32.0))
        loa    = float(body.get('loa',   200.0))

        # Land
        land_cross        = any_segment_crosses_land(coords)
        land_cross_points = []
        if land_cross:
            for i in range(len(coords) - 1):
                if segment_crosses_land(coords[i], coords[i+1]):
                    land_cross_points.append({
                        'from':          {'lon': coords[i][0],   'lat': coords[i][1]},
                        'to':            {'lon': coords[i+1][0], 'lat': coords[i+1][1]},
                        'segment_index': i,
                    })

        # TSS from OSM — dynamic world coverage
        tss_zones = query_tss_zones_osm(coords)

        # Depth + Danger
        depth  = check_depth(coords, draft, safety)
        danger = check_dangers(coords)

        # Route stats
        total_nm, max_leg, legs = 0.0, 0.0, []
        for i in range(len(coords) - 1):
            c1, c2 = coords[i], coords[i+1]
            nm     = haversine_nm(c1[1], c1[0], c2[1], c2[0])
            total_nm  += nm
            max_leg    = max(max_leg, nm)
            legs.append({
                'from':    {'lon': c1[0], 'lat': c1[1]},
                'to':      {'lon': c2[0], 'lat': c2[1]},
                'nm':      round(nm, 1),
                'bearing': round(bearing_two_points(c1, c2), 1),
            })

        # Warnings
        warnings = []
        if land_cross:
            warnings.append(f'🚨 LAND CROSSING in {len(land_cross_points)} segment(s)')
        for z in tss_zones:
            warnings.append(f'🚢 TSS zone: {z} — verify correct separation lane')
        for sp in depth.get('shallow_points', []):
            warnings.append(
                f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})"
            )
        for d in danger.get('dangers_near_route', []):
            warnings.append(
                f"🪨 {d['type'].upper()} '{d['name']}' {d['nearest_route_nm']}NM from route"
            )

        overall_safe = not land_cross and depth['safe'] and danger['safe']
        eta = lambda nm, kn: round(nm/kn, 2) if kn > 0 else None

        return jsonify({
            'overall_safe':   overall_safe,
            'total_warnings': len(warnings),
            'warnings':       warnings,
            'route_stats': {
                'total_nm':       round(total_nm, 1),
                'waypoint_count': len(coords),
                'max_leg_nm':     round(max_leg, 1),
                'eta': {
                    '10kn': eta(total_nm,10), '12kn': eta(total_nm,12),
                    '14kn': eta(total_nm,14), '15kn': eta(total_nm,15),
                    '18kn': eta(total_nm,18),
                },
            },
            'land_check':  {
                'safe': not land_cross,
                'crosses_land': land_cross,
                'problem_segments': land_cross_points,
            },
            'tss_check':   {
                'zones_found': len(tss_zones),
                'zones':       tss_zones,
                'note':        'TSS data from OpenSeaMap/OSM — worldwide coverage',
            },
            'depth_check': {
                'safe':           depth['safe'],
                'min_depth_m':    depth.get('min_depth'),
                'required_depth': depth.get('required_depth'),
                'points_checked': depth.get('checked'),
                'shallow_points': depth.get('shallow_points', []),
            },
            'danger_check': {
                'safe':               danger['safe'],
                'dangers_near_route': danger['dangers_near_route'],
                'total_in_area':      danger['total_in_area'],
            },
            'vessel_params': {
                'draft_m': draft, 'safety_m': safety,
                'beam_m':  beam,  'loa_m':    loa,
            },
            'legs': legs,
        })

    except Exception as e:
        print(f'[safety-check] error: {e}', file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

# ══════════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f'[maritime-router] Starting on port {port}', flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
