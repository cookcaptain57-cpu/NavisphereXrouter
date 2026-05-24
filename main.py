import os, sys, math
from flask import Flask, request, jsonify
from shapely.geometry import LineString, Point
import geopandas as gpd
from tss_lanes import inject_tss_waypoints
from port_approach import inject_port_approaches
from depth_checker import run_depth_and_danger_check
app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ── Load searoute ──────────────────────────────────────────────
SR = None
SR_ERROR = None
try:
    import searoute as sr
    test = sr.searoute([2.35, 48.85], [103.82, 1.27], units='naut')
    print(f'[maritime-router] v7 ready — test: {test.properties["length"]:.0f} NM', flush=True)
    SR = sr
except Exception as e:
    SR_ERROR = str(e)
    print(f'[maritime-router] ERROR: {e}', file=sys.stderr, flush=True)

# ── Load Natural Earth land polygons for land-crossing check ──
LAND = None
try:
    LAND = gpd.read_file(
        "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
    ).geometry.unary_union
    print('[maritime-router] Land polygons loaded ✅', flush=True)
except Exception as e:
    print(f'[maritime-router] Land polygon load failed: {e}', file=sys.stderr, flush=True)

# ── Hardcoded critical maritime chokepoints ────────────────────
# These fix the Sinai/strait problems that MARNET misses
CHOKEPOINTS = {
    'suez_s':        (32.55,  29.92),   # Suez Canal south
    'suez_n':        (32.33,  31.27),   # Suez Canal north / Port Said
    'bab_mandeb':    (43.42,  12.58),   # Bab-el-Mandeb strait
    'ras_muhammad':  (32.60,  27.73),   # Tip of Sinai
    'hormuz':        (56.50,  26.57),   # Strait of Hormuz
    'malacca_s':     (103.58,  1.16),   # Malacca Strait south
    'malacca_n':     (98.10,   5.35),   # Malacca Strait north
    'gibraltar':     (-5.35,  35.98),   # Gibraltar
    'dover':         (1.33,   51.10),   # Dover Strait
    'sunda':         (105.87, -6.05),   # Sunda Strait
    'lombok':        (115.75, -8.78),   # Lombok Strait
}

def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))

# ── Regional box checks ────────────────────────────────────────
def in_box(lon, lat, lon_min, lon_max, lat_min, lat_max):
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max

def in_red_sea(lon, lat):
    return in_box(lon, lat, 32, 44, 12, 30)

def in_mediterranean(lon, lat):
    return in_box(lon, lat, -6, 42, 30, 47)

def in_gulf_aqaba(lon, lat):
    return in_box(lon, lat, 34.5, 35.5, 27.5, 30)

def in_gulf_persian(lon, lat):
    return in_box(lon, lat, 48, 60, 22, 30)

def in_indian_ocean(lon, lat):
    return in_box(lon, lat, 40, 100, -40, 25)

def in_pacific(lon, lat):
    return in_box(lon, lat, 100, 180, -60, 60)

def in_atlantic(lon, lat):
    return in_box(lon, lat, -80, 10, -60, 60)

# ── Mandatory waypoint injection ───────────────────────────────
def get_mandatory_waypoints(from_lon, from_lat, to_lon, to_lat):
    """
    Inject mandatory chokepoint waypoints based on origin/destination regions.
    Prevents MARNET from routing through Sinai, or missing canals/straits.
    """
    wps = []
    cp = CHOKEPOINTS

    # RED SEA ↔ MEDITERRANEAN → must go through Suez Canal
    if ((in_red_sea(from_lon, from_lat) and in_mediterranean(to_lon, to_lat)) or
        (in_mediterranean(from_lon, from_lat) and in_red_sea(to_lon, to_lat))):
        if in_red_sea(from_lon, from_lat):
            wps = [cp['suez_s'], cp['suez_n']]
        else:
            wps = [cp['suez_n'], cp['suez_s']]

    # GULF OF AQABA ↔ anywhere → go around Ras Muhammad (tip of Sinai)
    elif in_gulf_aqaba(from_lon, from_lat):
        wps = [cp['ras_muhammad'], cp['bab_mandeb']]
    elif in_gulf_aqaba(to_lon, to_lat):
        wps = [cp['bab_mandeb'], cp['ras_muhammad']]

    # PERSIAN GULF ↔ anywhere → Strait of Hormuz
    elif ((in_gulf_persian(from_lon, from_lat) and not in_gulf_persian(to_lon, to_lat))):
        wps = [cp['hormuz']]
    elif ((in_gulf_persian(to_lon, to_lat) and not in_gulf_persian(from_lon, from_lat))):
        wps = [cp['hormuz']]

    # PACIFIC ↔ INDIAN OCEAN → Malacca or Lombok/Sunda
    elif ((in_pacific(from_lon, from_lat) and in_indian_ocean(to_lon, to_lat)) or
          (in_indian_ocean(from_lon, from_lat) and in_pacific(to_lon, to_lat))):
        wps = [cp['malacca_s']]  # default via Malacca

    # ATLANTIC ↔ MEDITERRANEAN → Gibraltar
    elif ((in_atlantic(from_lon, from_lat) and in_mediterranean(to_lon, to_lat)) or
          (in_mediterranean(from_lon, from_lat) and in_atlantic(to_lon, to_lat))):
        wps = [cp['gibraltar']]

    return wps

# ── Land-crossing segment check ────────────────────────────────
def segment_crosses_land(c1, c2):
    """Returns True if the straight line between c1 and c2 crosses land."""
    if LAND is None:
        return False
    try:
        line = LineString([c1, c2])
        return line.intersects(LAND)
    except:
        return False

def any_segment_crosses_land(coords):
    """Check if ANY segment in a route crosses land."""
    for i in range(len(coords) - 1):
        if segment_crosses_land(coords[i], coords[i+1]):
            return True
    return False

# ── Route via mandatory waypoints ─────────────────────────────
def route_via_waypoints(from_lon, from_lat, to_lon, to_lat, mandatory_wps):
    """
    Build route by chaining searoute calls through mandatory waypoints.
    Example: Port A → Suez South → Suez North → Port B
    """
    all_coords = []
    total_nm = 0.0

    # Build chain: origin → wp1 → wp2 → ... → destination
    points = [(from_lon, from_lat)] + mandatory_wps + [(to_lon, to_lat)]

    for i in range(len(points) - 1):
        seg_from = points[i]
        seg_to   = points[i+1]
        try:
            seg = SR.searoute(
                [seg_from[0], seg_from[1]],
                [seg_to[0],   seg_to[1]],
                units='naut',
                append_orig_dest=True,
            )
            seg_coords = seg.geometry['coordinates']
            seg_nm     = float(seg.properties.get('length', 0))

            # Skip duplicate start point (except first segment)
            if all_coords and seg_coords:
                seg_coords = seg_coords[1:]

            all_coords.extend(seg_coords)
            total_nm += seg_nm

        except Exception as e:
            print(f'[maritime-router] segment {i} failed: {e}', file=sys.stderr)
            # Fallback: straight line between waypoints
            if not all_coords:
                all_coords.append([seg_from[0], seg_from[1]])
            all_coords.append([seg_to[0], seg_to[1]])

    return all_coords, total_nm

# ── Safe simplification ────────────────────────────────────────
def safe_simplify(coords, min_nm=2.0):
    if len(coords) <= 3:
        return coords
    out = [coords[0]]
    i = 1
    while i < len(coords) - 1:
        prev = out[-1]
        curr = coords[i]
        d = haversine_nm(prev[1], prev[0], curr[1], curr[0])
        if d < min_nm:
            nxt = coords[min(i+1, len(coords)-1)]
            mid_lon = (prev[0] + nxt[0]) / 2
            mid_lat = (prev[1] + nxt[1]) / 2
            dev = haversine_nm(curr[1], curr[0], mid_lat, mid_lon)
            if dev > 1.0:  # keep — prevents land crossing
                out.append(curr)
            # Also keep if segment crosses land
            elif segment_crosses_land(prev, nxt):
                out.append(curr)
        else:
            out.append(curr)
        i += 1
    out.append(coords[-1])
    return out

# ── Health check ───────────────────────────────────────────────
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        'status':   'ok' if SR else 'degraded',
        'searoute': SR is not None,
        'land_check': LAND is not None,
        'error':    SR_ERROR,
        'service':  'maritime-router v7',
    })

# ── Main route endpoint ────────────────────────────────────────
@app.route('/route')
def route():
    if SR is None:
        return jsonify({'error': f'searoute not available: {SR_ERROR}'}), 503
    try:
        from_lon = float(request.args['fromLon'])
        from_lat = float(request.args['fromLat'])
        to_lon   = float(request.args['toLon'])
        to_lat   = float(request.args['toLat'])
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': f'Missing param: {e}'}), 400

    try:
        # ── STEP 1: Port approach waypoints (Fix 3) ──────────
        port_data = inject_port_approaches(from_lon, from_lat, to_lon, to_lat)
        origin_wps = port_data.get('origin', {}).get('waypoints', [])
        dest_wps   = port_data.get('destination', {}).get('waypoints', [])

        # Sea routing start/end = last origin WP / first dest WP
        sea_from = origin_wps[-1] if origin_wps else (from_lon, from_lat)
        sea_to   = dest_wps[0]   if dest_wps   else (to_lon,   to_lat)

        # ── STEP 2: TSS waypoints (Fix 2) ────────────────────
        tss_data = inject_tss_waypoints(sea_from[0], sea_from[1], sea_to[0], sea_to[1])
        tss_wps = []
        for tss in tss_data:
            tss_wps.extend(tss['waypoints'])

        # ── STEP 3: Mandatory chokepoints (Fix 1) ────────────
        mandatory_wps = get_mandatory_waypoints(sea_from[0], sea_from[1], sea_to[0], sea_to[1])

        # ── STEP 4: Merge all waypoints ───────────────────────
        # Order: origin_approach → TSS → chokepoints → dest_approach
        all_interim = list(set(tss_wps + mandatory_wps))  # dedupe
        # Sort by distance from sea_from
        all_interim.sort(key=lambda w: haversine_nm(
            sea_from[1], sea_from[0], w[1], w[0]
        ))

        # ── STEP 5: Build chained route ───────────────────────
        coords, dist_nm = route_via_waypoints(
            sea_from[0], sea_from[1],
            sea_to[0],   sea_to[1],
            all_interim
        )

        # ── STEP 6: Prepend/append port approach coords ───────
        origin_coords = [[w[0], w[1]] for w in origin_wps]
        dest_coords   = [[w[0], w[1]] for w in dest_wps]
        full_coords   = origin_coords + coords + dest_coords

        # ── STEP 7: Land crossing check ───────────────────────
        land_cross = any_segment_crosses_land(full_coords)

        # ── STEP 8: Simplify ──────────────────────────────────
        simplified = safe_simplify(full_coords, min_nm=2.0)

        # ── STEP 9: Recalculate total distance ────────────────
        total_nm = 0
        for i in range(len(simplified) - 1):
            c1, c2 = simplified[i], simplified[i+1]
            total_nm += haversine_nm(c1[1], c1[0], c2[1], c2[0])
        vessel_draft  = float(request.args.get('draft', 10.0))   # meters
        safety_margin = float(request.args.get('safety', 2.0))   # meters

        safety_report = run_depth_and_danger_check(
            simplified,
            vessel_draft_m   = vessel_draft,
            safety_margin_m  = safety_margin,
        )

        # Add to response JSON:
        return jsonify({
            'waypoints':     [...],   # your existing
            'totalNM':       ...,     # your existing
            # ── NEW Fix 4 fields ──
            'safetyReport':  safety_report,
            'overallSafe':   safety_report['overall_safe'],
            'warnings':      safety_report['warnings'],
        })
        print(
            f'[v8] {total_nm:.0f} NM | {len(full_coords)}→{len(simplified)} pts | '
            f'TSS:{len(tss_data)} | ports:{len(port_data)} | land:{land_cross}',
            flush=True
        )

        return jsonify({
            'waypoints':    [{'lat': float(c[1]), 'lon': float(c[0])} for c in simplified],
            'totalNM':      round(total_nm, 1),
            'source':       'searoute-python',
            'version':      'v8',
            'landCrossing': land_cross,
            'tssZones':     [t['tss'] for t in tss_data],
            'portApproach': {
                'origin':      port_data.get('origin', {}).get('port'),
                'destination': port_data.get('destination', {}).get('port'),
            },
        })

    except Exception as e:
        print(f'[maritime-router] error: {e}', file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500
