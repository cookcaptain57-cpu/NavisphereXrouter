# maritime-router v8 — Complete Single File
# Fixes: 1=Land crossing, 2=TSS lanes, 3=Port approach, 4=Depth+Dangers
# Endpoints: GET /route, POST /safety-check, GET /health

import os, sys, math, time, requests
from flask import Flask, request, jsonify
from shapely.geometry import LineString
import geopandas as gpd

app = Flask(__name__)

# ── CORS ───────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ══════════════════════════════════════════════════════════════
# INIT: Searoute + Land Polygons
# ══════════════════════════════════════════════════════════════
SR       = None
SR_ERROR = None
try:
    import searoute as sr
    test     = sr.searoute([2.35, 48.85], [103.82, 1.27], units='naut')
    dist     = test.properties.get('length', 0)
    SR       = sr
    print(f'[maritime-router] v8 ready — test: {dist:.0f} NM', flush=True)
except Exception as e:
    SR_ERROR = str(e)
    print(f'[maritime-router] searoute ERROR: {e}', file=sys.stderr, flush=True)

LAND = None
try:
    LAND = gpd.read_file(
        "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
    ).geometry.unary_union
    print('[maritime-router] Land polygons loaded ✅', flush=True)
except Exception as e:
    print(f'[maritime-router] Land polygon WARNING: {e}', file=sys.stderr, flush=True)

# ══════════════════════════════════════════════════════════════
# CONSTANTS: Chokepoints
# ══════════════════════════════════════════════════════════════
CHOKEPOINTS = {
    'suez_s':       (32.55,  29.92),
    'suez_n':       (32.33,  31.27),
    'bab_mandeb':   (43.42,  12.58),
    'ras_muhammad': (32.60,  27.73),
    'hormuz':       (56.50,  26.57),
    'malacca_s':    (103.58,  1.16),
    'malacca_n':    (98.10,   5.35),
    'gibraltar':    (-5.35,  35.98),
    'dover':        (1.33,   51.10),
    'sunda':        (105.87, -6.05),
    'lombok':       (115.75, -8.78),
}

# ══════════════════════════════════════════════════════════════
# CONSTANTS: TSS Database (Fix 2)
# ══════════════════════════════════════════════════════════════
TSS_DATABASE = {
    'dover_strait': {
        'bbox': (-1.5, 50.5, 2.5, 52.0),
        'northbound': [(1.25,50.87),(1.50,51.10),(1.75,51.30),(2.00,51.50)],
        'southbound': [(1.60,51.45),(1.35,51.20),(1.10,51.00),(0.85,50.80)],
    },
    'english_channel_west': {
        'bbox': (-5.5, 49.0, -1.5, 51.0),
        'eastbound': [(-5.20,49.45),(-4.00,49.60),(-2.50,49.80),(-1.60,50.20)],
        'westbound': [(-1.80,50.40),(-3.00,50.10),(-4.50,49.80),(-5.40,49.60)],
    },
    'gibraltar': {
        'bbox': (-6.0, 35.7, -5.2, 36.2),
        'eastbound': [(-5.90,35.98),(-5.60,35.97),(-5.35,35.96)],
        'westbound': [(-5.35,36.02),(-5.65,36.03),(-5.90,36.04)],
    },
    'malacca_strait': {
        'bbox': (98.0, 1.0, 104.5, 6.5),
        'northbound': [(103.50,1.20),(102.50,2.00),(101.50,3.00),
                       (100.50,4.00),(99.50,5.00),(98.50,5.60)],
        'southbound': [(103.65,1.30),(102.65,2.10),(101.65,3.10),
                       (100.65,4.10),(99.65,5.10),(98.65,5.70)],
    },
    'suez_canal': {
        'bbox': (32.2, 29.8, 33.0, 31.5),
        'northbound': [(32.55,29.92),(32.50,30.25),(32.40,30.60),
                       (32.35,31.00),(32.30,31.27)],
        'southbound': [(32.33,31.27),(32.38,31.00),(32.43,30.60),
                       (32.48,30.25),(32.55,29.92)],
    },
    'bab_el_mandeb': {
        'bbox': (42.5, 11.5, 44.5, 13.5),
        'northbound': [(43.42,11.60),(43.35,12.00),(43.30,12.50)],
        'southbound': [(43.50,12.55),(43.55,12.05),(43.60,11.65)],
    },
    'hormuz': {
        'bbox': (55.5, 25.5, 57.5, 27.0),
        'inbound':  [(56.30,26.00),(56.50,26.30),(56.70,26.55)],
        'outbound': [(56.80,26.60),(56.60,26.35),(56.40,26.05)],
    },
    'singapore_strait': {
        'bbox': (103.5, 1.1, 104.5, 1.5),
        'eastbound': [(103.55,1.18),(103.75,1.20),(103.95,1.22),(104.20,1.25)],
        'westbound': [(104.22,1.28),(103.97,1.26),(103.77,1.24),(103.57,1.22)],
    },
    'cape_good_hope': {
        'bbox': (17.5, -35.5, 19.5, -33.5),
        'northbound': [(18.40,-35.20),(18.30,-34.50),(18.20,-33.80)],
        'southbound': [(18.50,-33.85),(18.60,-34.55),(18.70,-35.25)],
    },
    'north_sea_german_bight': {
        'bbox': (6.0, 53.5, 9.5, 56.0),
        'northbound': [(7.80,53.80),(7.60,54.50),(7.40,55.20)],
        'southbound': [(8.00,55.25),(8.20,54.55),(8.40,53.85)],
    },
}

# ══════════════════════════════════════════════════════════════
# CONSTANTS: Port Approach Database (Fix 3)
# ══════════════════════════════════════════════════════════════
PORT_APPROACHES = {
    'singapore': {
        'coord': (103.82, 1.27),
        'approach': [(103.57,1.14),(103.65,1.18),(103.72,1.22),(103.80,1.26)],
    },
    'rotterdam': {
        'coord': (4.50, 51.92),
        'approach': [(3.50,51.97),(3.80,51.97),(4.00,51.95),
                     (4.20,51.93),(4.40,51.92),(4.50,51.92)],
    },
    'shanghai': {
        'coord': (121.47, 31.23),
        'approach': [(122.20,31.10),(122.00,31.12),(121.80,31.15),
                     (121.60,31.18),(121.47,31.23)],
    },
    'port_said': {
        'coord': (32.30, 31.27),
        'approach': [(32.20,31.40),(32.22,31.35),(32.25,31.32),(32.30,31.27)],
    },
    'suez_south': {
        'coord': (32.55, 29.92),
        'approach': [(32.62,29.72),(32.60,29.80),(32.58,29.86),(32.55,29.92)],
    },
    'jebel_ali': {
        'coord': (55.02, 24.98),
        'approach': [(54.75,24.80),(54.85,24.85),(54.90,24.90),
                     (54.96,24.94),(55.02,24.98)],
    },
    'hong_kong': {
        'coord': (114.18, 22.30),
        'approach': [(114.05,22.10),(114.10,22.18),(114.14,22.24),(114.18,22.30)],
    },
    'hamburg': {
        'coord': (9.97, 53.55),
        'approach': [(8.10,53.99),(8.50,53.90),(8.80,53.80),
                     (9.20,53.72),(9.60,53.63),(9.97,53.55)],
    },
    'antwerp': {
        'coord': (4.40, 51.23),
        'approach': [(3.18,51.37),(3.50,51.30),(3.80,51.27),
                     (4.10,51.25),(4.40,51.23)],
    },
    'busan': {
        'coord': (129.04, 35.10),
        'approach': [(129.15,34.85),(129.10,34.95),(129.07,35.02),(129.04,35.10)],
    },
    'los_angeles': {
        'coord': (-118.27, 33.73),
        'approach': [(-118.55,33.55),(-118.45,33.60),(-118.40,33.65),
                     (-118.35,33.69),(-118.27,33.73)],
    },
    'new_york': {
        'coord': (-74.02, 40.65),
        'approach': [(-73.80,40.30),(-73.82,40.45),(-73.90,40.55),(-74.02,40.65)],
    },
    'colombo': {
        'coord': (79.85, 6.93),
        'approach': [(79.75,6.82),(79.80,6.88),(79.83,6.91),(79.85,6.93)],
    },
    'mumbai': {
        'coord': (72.85, 18.92),
        'approach': [(72.65,18.70),(72.75,18.80),(72.80,18.86),(72.85,18.92)],
    },
    'karachi': {
        'coord': (66.99, 24.84),
        'approach': [(66.75,24.72),(66.85,24.78),(66.92,24.81),(66.99,24.84)],
    },
    'colombo': {
        'coord': (79.85, 6.93),
        'approach': [(79.75,6.82),(79.80,6.88),(79.83,6.91),(79.85,6.93)],
    },
    'aden': {
        'coord': (45.03, 12.78),
        'approach': [(44.85,12.60),(44.92,12.68),(44.98,12.74),(45.03,12.78)],
    },
    'djibouti': {
        'coord': (43.15, 11.60),
        'approach': [(43.00,11.45),(43.07,11.52),(43.11,11.56),(43.15,11.60)],
    },
}

# ══════════════════════════════════════════════════════════════
# CONSTANTS: Depth + Danger (Fix 4)
# ══════════════════════════════════════════════════════════════
GEBCO_API    = "https://api.odb.ntu.edu.tw/gebco"
OVERPASS_API = "https://overpass-api.de/api/interpreter"
DANGER_TYPES = [
    'rock','wreck','obstruction','shoal',
    'reef','underwater_rock','foul_ground','snag',
]
_depth_cache  = {}
_danger_cache = {}

# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
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
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r) -
         math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def bearing_from_coords(coords):
    if len(coords) < 2: return 0
    return bearing(coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])

def bearing_two_points(c1, c2):
    return bearing(c1[0], c1[1], c2[0], c2[1])

def in_box(lon, lat, lon_min, lon_max, lat_min, lat_max):
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max

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

def safe_simplify(coords, min_nm=2.0):
    if len(coords) <= 3: return coords
    out = [coords[0]]
    i   = 1
    while i < len(coords) - 1:
        prev = out[-1]
        curr = coords[i]
        d    = haversine_nm(prev[1], prev[0], curr[1], curr[0])
        if d < min_nm:
            nxt     = coords[min(i+1, len(coords)-1)]
            mid_lon = (prev[0] + nxt[0]) / 2
            mid_lat = (prev[1] + nxt[1]) / 2
            dev     = haversine_nm(curr[1], curr[0], mid_lat, mid_lon)
            if dev > 1.0 or segment_crosses_land(prev, nxt):
                out.append(curr)
        else:
            out.append(curr)
        i += 1
    out.append(coords[-1])
    return out

# ══════════════════════════════════════════════════════════════
# FIX 1: Region checks + mandatory waypoints
# ══════════════════════════════════════════════════════════════
def in_red_sea(lon, lat):      return in_box(lon, lat, 32, 44, 12, 30)
def in_mediterranean(lon, lat):return in_box(lon, lat, -6, 42, 30, 47)
def in_gulf_aqaba(lon, lat):   return in_box(lon, lat, 34.5, 35.5, 27.5, 30)
def in_gulf_persian(lon, lat): return in_box(lon, lat, 48, 60, 22, 30)
def in_indian_ocean(lon, lat): return in_box(lon, lat, 40, 100, -40, 25)
def in_pacific(lon, lat):      return in_box(lon, lat, 100, 180, -60, 60)
def in_atlantic(lon, lat):     return in_box(lon, lat, -80, 10, -60, 60)

def get_mandatory_waypoints(from_lon, from_lat, to_lon, to_lat):
    wps = []
    cp  = CHOKEPOINTS
    if ((in_red_sea(from_lon,from_lat) and in_mediterranean(to_lon,to_lat)) or
        (in_mediterranean(from_lon,from_lat) and in_red_sea(to_lon,to_lat))):
        wps = [cp['suez_s'], cp['suez_n']] if in_red_sea(from_lon,from_lat) \
              else [cp['suez_n'], cp['suez_s']]
    elif in_gulf_aqaba(from_lon, from_lat):
        wps = [cp['ras_muhammad'], cp['bab_mandeb']]
    elif in_gulf_aqaba(to_lon, to_lat):
        wps = [cp['bab_mandeb'], cp['ras_muhammad']]
    elif (in_gulf_persian(from_lon,from_lat) and not in_gulf_persian(to_lon,to_lat)):
        wps = [cp['hormuz']]
    elif (in_gulf_persian(to_lon,to_lat) and not in_gulf_persian(from_lon,from_lat)):
        wps = [cp['hormuz']]
    elif ((in_pacific(from_lon,from_lat) and in_indian_ocean(to_lon,to_lat)) or
          (in_indian_ocean(from_lon,from_lat) and in_pacific(to_lon,to_lat))):
        wps = [cp['malacca_s']]
    elif ((in_atlantic(from_lon,from_lat) and in_mediterranean(to_lon,to_lat)) or
          (in_mediterranean(from_lon,from_lat) and in_atlantic(to_lon,to_lat))):
        wps = [cp['gibraltar']]
    return wps

def route_via_waypoints(from_lon, from_lat, to_lon, to_lat, mandatory_wps):
    all_coords = []
    total_nm   = 0.0
    points     = [(from_lon, from_lat)] + mandatory_wps + [(to_lon, to_lat)]
    for i in range(len(points) - 1):
        seg_from = points[i]
        seg_to   = points[i+1]
        try:
            seg        = SR.searoute([seg_from[0],seg_from[1]],
                                     [seg_to[0],  seg_to[1]],
                                     units='naut', append_orig_dest=True)
            seg_coords = seg.geometry['coordinates']
            seg_nm     = float(seg.properties.get('length', 0))
            if all_coords and seg_coords:
                seg_coords = seg_coords[1:]
            all_coords.extend(seg_coords)
            total_nm  += seg_nm
        except Exception as e:
            print(f'[route_via_waypoints] segment {i} error: {e}', file=sys.stderr)
            if not all_coords:
                all_coords.append([seg_from[0], seg_from[1]])
            all_coords.append([seg_to[0], seg_to[1]])
    return all_coords, total_nm

# ══════════════════════════════════════════════════════════════
# FIX 2: TSS Lane Logic
# ══════════════════════════════════════════════════════════════
def tss_route_crosses(from_lon, from_lat, to_lon, to_lat, bbox):
    lon_min, lat_min, lon_max, lat_max = bbox
    for i in range(21):
        t   = i / 20
        lon = from_lon + t * (to_lon - from_lon)
        lat = from_lat + t * (to_lat - from_lat)
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            return True
    return False

def tss_pick_lane(tss_data, brng):
    lane_map = {
        'northbound': 0,
        'southbound': 180,
        'eastbound':  90,
        'westbound':  270,
        'inbound':    315,
        'outbound':   135,
    }
    best, best_diff = None, 999
    for lane_name, center in lane_map.items():
        if lane_name not in tss_data: continue
        diff = abs(((brng - center) + 180) % 360 - 180)
        if diff < best_diff:
            best_diff = diff
            best      = lane_name
    return best

def inject_tss_waypoints(from_lon, from_lat, to_lon, to_lat):
    brng   = bearing(from_lon, from_lat, to_lon, to_lat)
    result = []
    for tss_name, tss_data in TSS_DATABASE.items():
        bbox = tss_data['bbox']
        if not tss_route_crosses(from_lon, from_lat, to_lon, to_lat, bbox):
            continue
        lane_key = tss_pick_lane(tss_data, brng)
        if lane_key and lane_key in tss_data:
            result.append({
                'tss':       tss_name,
                'lane':      lane_key,
                'waypoints': tss_data[lane_key],
            })
            print(f'[TSS] {tss_name} → {lane_key} lane', flush=True)
    return result

# ══════════════════════════════════════════════════════════════
# FIX 3: Port Approach Logic
# ══════════════════════════════════════════════════════════════
def find_nearest_port(lon, lat, radius_nm=50):
    best, best_dist = None, radius_nm
    for port_name, port_data in PORT_APPROACHES.items():
        plon, plat = port_data['coord']
        dist = haversine_nm(lat, lon, plat, plon)
        if dist < best_dist:
            best_dist = dist
            best      = (port_name, port_data, dist)
    return best

def get_approach_waypoints(lon, lat, is_destination=True):
    result = find_nearest_port(lon, lat)
    if not result: return None, None
    port_name, port_data, _ = result
    wps = port_data['approach']
    if not is_destination:
        wps = list(reversed(wps))
    return port_name, wps

def inject_port_approaches(from_lon, from_lat, to_lon, to_lat):
    result = {}
    origin_port, origin_wps = get_approach_waypoints(from_lon, from_lat, is_destination=False)
    if origin_port:
        result['origin'] = {'port': origin_port, 'waypoints': origin_wps}
        print(f'[PortApproach] Origin: {origin_port}', flush=True)
    dest_port, dest_wps = get_approach_waypoints(to_lon, to_lat, is_destination=True)
    if dest_port:
        result['destination'] = {'port': dest_port, 'waypoints': dest_wps}
        print(f'[PortApproach] Destination: {dest_port}', flush=True)
    return result

# ══════════════════════════════════════════════════════════════
# FIX 4: Depth + Danger Check
# ══════════════════════════════════════════════════════════════
def interpolate_check_points(coords, interval_nm=10.0):
    pts = []
    for i in range(len(coords) - 1):
        c1, c2   = coords[i], coords[i+1]
        seg_nm   = haversine_nm(c1[1], c1[0], c2[1], c2[0])
        steps    = max(1, int(seg_nm / interval_nm))
        for s in range(steps):
            t = s / steps
            pts.append((c1[0] + t*(c2[0]-c1[0]),
                        c1[1] + t*(c2[1]-c1[1])))
    if coords: pts.append((coords[-1][0], coords[-1][1]))
    return pts

def check_depth(coords, draft_m=10.0, safety_m=2.0):
    min_required = draft_m + safety_m
    check_pts    = interpolate_check_points(coords, 10.0)
    shallow      = []
    depths_found = []
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
                    water_depth = abs(depths[i]) if depths[i] < 0 else 0
                    depths_found.append(water_depth)
                    if 0 < water_depth < min_required:
                        shallow.append({
                            'lon':      pt[0],
                            'lat':      pt[1],
                            'depth':    round(water_depth, 1),
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

def check_dangers(coords, buffer_nm=2.0):
    lons    = [c[0] for c in coords]
    lats    = [c[1] for c in coords]
    buf     = 0.05
    bbox_s  = min(lats) - buf
    bbox_n  = max(lats) + buf
    bbox_w  = min(lons) - buf
    bbox_e  = max(lons) + buf
    bbox_str = f"{bbox_s},{bbox_w},{bbox_n},{bbox_e}"

    cache_key = f"{round(bbox_s,2)}_{round(bbox_w,2)}_{round(bbox_n,2)}_{round(bbox_e,2)}"
    if cache_key in _danger_cache:
        danger_marks = _danger_cache[cache_key]
    else:
        type_filters = '\n'.join([
            f'  node["seamark:type"="{t}"]({bbox_str});'
            for t in DANGER_TYPES
        ])
        query = f"[out:json][timeout:25];\n(\n{type_filters}\n);\nout body;"
        danger_marks = []
        try:
            resp = requests.post(OVERPASS_API,
                                 data={'data': query}, timeout=20)
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

def run_safety_checks(coords, draft_m=10.0, safety_m=2.0):
    depth_result  = check_depth(coords, draft_m, safety_m)
    danger_result = check_dangers(coords)
    warnings = []
    for sp in depth_result.get('shallow_points', []):
        warnings.append(
            f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})"
            f" — need {sp['required']}m"
        )
    for d in danger_result.get('dangers_near_route', []):
        warnings.append(
            f"🪨 {d['type'].upper()} '{d['name']}' at "
            f"({d['lat']:.3f},{d['lon']:.3f}) — {d['nearest_route_nm']}NM from route"
        )
    return {
        'overall_safe':  depth_result['safe'] and danger_result['safe'],
        'depth_check':   depth_result,
        'danger_check':  danger_result,
        'warnings':      warnings,
    }

# ══════════════════════════════════════════════════════════════
# ROUTE ENDPOINT: GET /route
# ══════════════════════════════════════════════════════════════
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        'status':     'ok' if SR else 'degraded',
        'searoute':   SR is not None,
        'land_check': LAND is not None,
        'error':      SR_ERROR,
        'service':    'maritime-router v8',
        'fixes':      ['land-crossing','TSS-lanes','port-approach','depth-dangers'],
    })

@app.route('/route')
def route():
    if SR is None:
        return jsonify({'error': f'searoute not available: {SR_ERROR}'}), 503
    try:
        from_lon = float(request.args['fromLon'])
        from_lat = float(request.args['fromLat'])
        to_lon   = float(request.args['toLon'])
        to_lat   = float(request.args['toLat'])
        draft    = float(request.args.get('draft',  10.0))
        safety   = float(request.args.get('safety',  2.0))
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': f'Missing/invalid param: {e}'}), 400

    try:
        # ── Step 1: Port approach waypoints (Fix 3) ───────────
        port_data  = inject_port_approaches(from_lon, from_lat, to_lon, to_lat)
        origin_wps = port_data.get('origin', {}).get('waypoints', [])
        dest_wps   = port_data.get('destination', {}).get('waypoints', [])
        sea_from   = origin_wps[-1] if origin_wps else (from_lon, from_lat)
        sea_to     = dest_wps[0]   if dest_wps   else (to_lon,   to_lat)

        # ── Step 2: TSS waypoints (Fix 2) ─────────────────────
        tss_data = inject_tss_waypoints(sea_from[0], sea_from[1],
                                        sea_to[0],   sea_to[1])
        tss_wps  = []
        for tss in tss_data:
            tss_wps.extend(tss['waypoints'])

        # ── Step 3: Mandatory chokepoints (Fix 1) ─────────────
        mandatory_wps = get_mandatory_waypoints(
            sea_from[0], sea_from[1], sea_to[0], sea_to[1]
        )

        # ── Step 4: Merge + sort interim waypoints ─────────────
        all_interim = list({tuple(w) for w in tss_wps + mandatory_wps})
        all_interim.sort(key=lambda w: haversine_nm(
            sea_from[1], sea_from[0], w[1], w[0]
        ))

        # ── Step 5: Build chained sea route ───────────────────
        if all_interim:
            coords, dist_nm = route_via_waypoints(
                sea_from[0], sea_from[1],
                sea_to[0],   sea_to[1],
                all_interim
            )
            method = f'chained-{len(all_interim)}-waypoints'
        else:
            result  = SR.searoute([sea_from[0], sea_from[1]],
                                  [sea_to[0],   sea_to[1]],
                                  units='naut', append_orig_dest=True)
            coords  = result.geometry['coordinates']
            dist_nm = float(result.properties.get('length', 0))
            method  = 'direct-searoute'

        # ── Step 6: Attach port approach coords ───────────────
        origin_coords = [[w[0], w[1]] for w in origin_wps]
        dest_coords   = [[w[0], w[1]] for w in dest_wps]
        full_coords   = origin_coords + coords + dest_coords

        # ── Step 7: Land check (Fix 1) ────────────────────────
        land_cross = any_segment_crosses_land(full_coords)
        if land_cross:
            print('[route] ⚠️ Land crossing detected!', file=sys.stderr, flush=True)

        # ── Step 8: Simplify ──────────────────────────────────
        simplified = safe_simplify(full_coords, min_nm=2.0)

        # ── Step 9: Recalculate total NM ──────────────────────
        total_nm = sum(
            haversine_nm(simplified[i][1], simplified[i][0],
                         simplified[i+1][1], simplified[i+1][0])
            for i in range(len(simplified) - 1)
        )

        # ── Step 10: Depth + Danger check (Fix 4) ─────────────
        safety_report = run_safety_checks(simplified, draft, safety)

        print(
            f'[route] {total_nm:.0f} NM | {len(full_coords)}→{len(simplified)} pts | '
            f'method={method} | land={land_cross} | safe={safety_report["overall_safe"]}',
            flush=True
        )

        return jsonify({
            'waypoints':    [{'lat': float(c[1]), 'lon': float(c[0])}
                             for c in simplified],
            'totalNM':      round(total_nm, 1),
            'source':       'maritime-router-v8',
            'method':       method,
            'landCrossing': land_cross,
            'tssZones':     [t['tss'] for t in tss_data],
            'portApproach': {
                'origin':      port_data.get('origin', {}).get('port'),
                'destination': port_data.get('destination', {}).get('port'),
            },
            'overallSafe':  safety_report['overall_safe'],
            'warnings':     safety_report['warnings'],
            'safetyReport': safety_report,
        })

    except Exception as e:
        print(f'[route] error: {e}', file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

# ══════════════════════════════════════════════════════════════
# SAFETY-CHECK ENDPOINT: POST /safety-check
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
            return jsonify({'error': 'Need at least 2 waypoints'}), 400

        coords = [[float(w['lon']), float(w['lat'])] for w in raw_wps]
        draft  = float(body.get('draft',  10.0))
        safety = float(body.get('safety',  2.0))
        beam   = float(body.get('beam',   32.0))
        loa    = float(body.get('loa',   200.0))

        print(
            f'[safety-check] {len(coords)} waypoints | '
            f'draft={draft}m beam={beam}m loa={loa}m',
            flush=True
        )

        # ── Check 1: Land ──────────────────────────────────────
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

        # ── Check 2: TSS ───────────────────────────────────────
        tss_hits   = inject_tss_waypoints(
            coords[0][0], coords[0][1], coords[-1][0], coords[-1][1]
        )
        tss_issues = [{
            'tss':          t['tss'],
            'correct_lane': t['lane'],
            'note':         f"Route crosses {t['tss']} — verify {t['lane']} lane",
        } for t in tss_hits]

        # ── Check 3: Port approach ─────────────────────────────
        port_data  = inject_port_approaches(
            coords[0][0], coords[0][1], coords[-1][0], coords[-1][1]
        )
        port_issues = []
        for role in ['origin', 'destination']:
            pd = port_data.get(role, {})
            if pd:
                port_issues.append({
                    'port':   pd.get('port'),
                    'type':   role,
                    'note':   f"Verify {role} via {pd.get('port')} pilot/fairway",
                })

        # ── Check 4: Depth + Dangers ───────────────────────────
        safety_report = run_safety_checks(coords, draft, safety)

        # ── Route stats ────────────────────────────────────────
        total_nm   = 0.0
        max_leg_nm = 0.0
        legs       = []
        for i in range(len(coords) - 1):
            c1, c2  = coords[i], coords[i+1]
            leg_nm  = haversine_nm(c1[1], c1[0], c2[1], c2[0])
            total_nm   += leg_nm
            max_leg_nm  = max(max_leg_nm, leg_nm)
            legs.append({
                'from':    {'lon': c1[0], 'lat': c1[1]},
                'to':      {'lon': c2[0], 'lat': c2[1]},
                'nm':      round(leg_nm, 1),
                'bearing': round(bearing_two_points(c1, c2), 1),
            })

        # ── All warnings ───────────────────────────────────────
        all_warnings = []
        if land_cross:
            all_warnings.append(
                f"🚨 LAND CROSSING in {len(land_cross_points)} segment(s)"
            )
        for ti in tss_issues:
            all_warnings.append(f"🚢 TSS: {ti['note']}")
        for pi in port_issues:
            all_warnings.append(f"⚓ PORT: {pi['note']}")
        all_warnings.extend(safety_report.get('warnings', []))

        overall_safe = not land_cross and safety_report['overall_safe']

        def eta(nm, kn): return round(nm / kn, 2) if kn > 0 else None

        print(
            f'[safety-check] {total_nm:.0f} NM | '
            f'safe={overall_safe} | warnings={len(all_warnings)}',
            flush=True
        )

        return jsonify({
            'overall_safe':   overall_safe,
            'total_warnings': len(all_warnings),
            'warnings':       all_warnings,
            'route_stats': {
                'total_nm':       round(total_nm, 1),
                'waypoint_count': len(coords),
                'leg_count':      len(legs),
                'max_leg_nm':     round(max_leg_nm, 1),
                'eta': {
                    '10kn': eta(total_nm, 10),
                    '12kn': eta(total_nm, 12),
                    '14kn': eta(total_nm, 14),
                    '15kn': eta(total_nm, 15),
                    '18kn': eta(total_nm, 18),
                },
            },
            'land_check': {
                'safe':             not land_cross,
                'crosses_land':     land_cross,
                'problem_segments': land_cross_points,
            },
            'tss_check': {
                'zones_crossed': len(tss_issues),
                'issues':        tss_issues,
            },
            'port_check': {
                'origin_port':      port_data.get('origin', {}).get('port'),
                'destination_port': port_data.get('destination', {}).get('port'),
                'issues':           port_issues,
            },
            'depth_check': {
                'safe':           safety_report['depth_check']['safe'],
                'min_depth_m':    safety_report['depth_check'].get('min_depth'),
                'required_depth': safety_report['depth_check'].get('required_depth'),
                'points_checked': safety_report['depth_check'].get('checked'),
                'shallow_points': safety_report['depth_check'].get('shallow_points', []),
            },
            'danger_check': {
                'safe':               safety_report['danger_check']['safe'],
                'dangers_near_route': safety_report['danger_check']['dangers_near_route'],
                'total_in_area':      safety_report['danger_check']['total_in_area'],
            },
            'vessel_params': {
                'draft_m':  draft,
                'safety_m': safety,
                'beam_m':   beam,
                'loa_m':    loa,
            },
            'legs': legs,
        })

    except Exception as e:
        print(f'[safety-check] error: {e}', file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

# ══════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f'[maritime-router] Starting on port {port}', flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
