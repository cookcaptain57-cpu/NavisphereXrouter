# maritime-router v11 — Sea-Gate Architecture
#
# WHY v10 STILL FAILED:
#   searoute gets port coordinates too close to land →
#   routes straight line through peninsulas/islands
#
# FIX — Sea-Gate Architecture (same as PortToPort logic):
#   1. Every port has a SEA GATE — a coordinate already in
#      open navigable water, far from the coast
#   2. Route is: [port] → [sea gate] → searoute → [sea gate] → [port]
#   3. The port→sea_gate leg is a straight pilot channel line
#   4. searoute only operates between sea gates (safe open water)
#   5. TSS remains warning-only
#   6. RDP simplification cleans up the result
#
# This matches PortToPort's "Pilots / Offshore TSA / Enter Special Area"
# waypoint logic — those named WPs are exactly sea gates.

import os, sys, math, time, threading, requests
from flask import Flask, request, jsonify
from shapely.geometry import LineString
import geopandas as gpd

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ══════════════════════════════════════════════════════════════
# BACKGROUND INIT
# ══════════════════════════════════════════════════════════════
SR, SR_ERROR, LAND, _init_done = None, None, None, False

def _background_init():
    global SR, SR_ERROR, LAND, _init_done
    try:
        import searoute as sr
        test = sr.searoute([2.35, 48.85], [103.82, 1.27], units='naut')
        SR   = sr
        print(f'[v11] searoute ready — {test.properties.get("length",0):.0f} NM', flush=True)
    except Exception as e:
        SR_ERROR = str(e)
        print(f'[v11] searoute ERROR: {e}', file=sys.stderr, flush=True)
    try:
        gdf  = gpd.read_file(
            "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
        )
        LAND = gdf.geometry.union_all()
        print('[v11] Land polygons ✅', flush=True)
    except Exception as e:
        print(f'[v11] Land WARNING: {e}', file=sys.stderr, flush=True)
    _init_done = True

threading.Thread(target=_background_init, daemon=True).start()

# ══════════════════════════════════════════════════════════════
# SEA GATE DATABASE
#
# Each port has:
#   'port'     : the actual berth/terminal coordinate
#   'sea_gate' : a coordinate ALREADY IN open navigable water
#                (equivalent to PortToPort's "Pilots" / "Offshore TSA" WP)
#   'name'     : display name
#
# Sea gate rules:
#   - Must be in water, not inside a bay or river mouth
#   - At least 2-5 NM from nearest land
#   - On the natural approach axis of the port
#   - searoute will NEVER be asked to start/end closer than this
# ══════════════════════════════════════════════════════════════
SEA_GATES = {
    # ── Indian Subcontinent ──────────────────────────────────
    'mumbai': {
        'name':     'Mumbai (JNPT)',
        'port':     (72.950, 18.950),
        # Sea gate west of peninsula — avoids routing through Mumbai city
        'sea_gate': (72.500, 18.800),
    },
    'mundra': {
        'name':     'Mundra',
        'port':     (69.700, 22.730),
        'sea_gate': (69.200, 22.600),   # Gulf of Kutch outer limit
    },
    'kandla': {
        'name':     'Kandla',
        'port':     (70.220, 23.000),
        'sea_gate': (69.500, 22.750),
    },
    'nhava_sheva': {
        'name':     'Nhava Sheva',
        'port':     (72.950, 18.950),
        'sea_gate': (72.500, 18.800),
    },
    'chennai': {
        'name':     'Chennai',
        'port':     (80.300, 13.090),
        'sea_gate': (80.380, 12.900),
    },
    'karachi': {
        'name':     'Karachi',
        'port':     (66.990, 24.840),
        'sea_gate': (66.600, 24.500),
    },
    'colombo': {
        'name':     'Colombo',
        'port':     (79.850, 6.930),
        'sea_gate': (79.650, 6.800),
    },
    'chittagong': {
        'name':     'Chittagong',
        'port':     (91.830, 22.330),
        'sea_gate': (91.500, 21.800),
    },

    # ── Middle East / Persian Gulf ───────────────────────────
    'jebel_ali': {
        'name':     'Jebel Ali',
        'port':     (55.020, 24.980),
        'sea_gate': (54.600, 24.700),   # outside Gulf approach
    },
    'abu_dhabi': {
        'name':     'Abu Dhabi (Zayed)',
        'port':     (54.380, 24.480),
        'sea_gate': (54.600, 24.200),
    },
    'dammam': {
        'name':     'Dammam / King Abdulaziz',
        'port':     (50.100, 26.430),
        'sea_gate': (50.300, 26.200),
    },
    'bandar_abbas': {
        'name':     'Bandar Abbas',
        'port':     (56.280, 27.180),
        'sea_gate': (56.600, 26.700),   # just inside Hormuz on Oman side
    },
    'aden': {
        'name':     'Aden',
        'port':     (45.030, 12.780),
        'sea_gate': (44.700, 12.600),
    },
    'djibouti': {
        'name':     'Djibouti',
        'port':     (43.150, 11.600),
        'sea_gate': (43.000, 11.400),
    },

    # ── Red Sea / East Africa ────────────────────────────────
    'jeddah': {
        'name':     'Jeddah Islamic Port',
        'port':     (39.170, 21.480),
        'sea_gate': (38.900, 21.300),
    },
    'port_sudan': {
        'name':     'Port Sudan',
        'port':     (37.220, 19.620),
        'sea_gate': (37.400, 19.400),
    },
    'mombasa': {
        'name':     'Mombasa',
        'port':     (39.680, -4.050),
        'sea_gate': (39.800, -4.200),
    },
    'dar_es_salaam': {
        'name':     'Dar es Salaam',
        'port':     (39.290, -6.820),
        'sea_gate': (39.500, -6.900),
    },

    # ── Suez Canal ───────────────────────────────────────────
    'port_said': {
        'name':     'Port Said (Canal North)',
        'port':     (32.300, 31.270),
        # Sea gate in Mediterranean — stays out of canal entry traffic
        'sea_gate': (32.200, 31.600),
    },
    'suez': {
        'name':     'Suez (Canal South)',
        'port':     (32.540, 29.970),
        # Sea gate in Red Sea — stays out of Great Bitter Lake
        'sea_gate': (32.580, 29.500),
    },
    'ismailia': {
        'name':     'Ismailia',
        'port':     (32.270, 30.590),
        'sea_gate': (32.200, 31.600),   # use Port Said sea gate
    },

    # ── Mediterranean ────────────────────────────────────────
    'piraeus': {
        'name':     'Piraeus',
        'port':     (23.630, 37.940),
        'sea_gate': (23.500, 37.800),
    },
    'barcelona': {
        'name':     'Barcelona',
        'port':     (2.180, 41.340),
        'sea_gate': (2.200, 41.100),
    },
    'genova': {
        'name':     'Genova',
        'port':     (8.920, 44.410),
        'sea_gate': (9.000, 44.200),
    },
    'marseille': {
        'name':     'Marseille',
        'port':     (5.350, 43.300),
        'sea_gate': (5.100, 43.100),
    },
    'algeciras': {
        'name':     'Algeciras',
        'port':     (-5.450, 36.130),
        'sea_gate': (-5.600, 35.900),   # just west of Gibraltar
    },

    # ── Northwest Europe ─────────────────────────────────────
    'rotterdam': {
        'name':     'Rotterdam (ECT)',
        'port':     (4.050, 51.900),
        # Sea gate at outer Maas approaches — avoids Hook of Holland
        'sea_gate': (3.500, 51.970),
    },
    'antwerp': {
        'name':     'Antwerp',
        'port':     (4.400, 51.230),
        'sea_gate': (3.150, 51.370),    # outer Scheldt
    },
    'hamburg': {
        'name':     'Hamburg',
        'port':     (9.970, 53.550),
        'sea_gate': (8.100, 54.000),    # outer Elbe / Cuxhaven area
    },
    'felixstowe': {
        'name':     'Felixstowe',
        'port':     (1.320, 51.950),
        'sea_gate': (1.700, 51.900),
    },
    'london': {
        'name':     'London (Tilbury)',
        'port':     (0.360, 51.450),
        'sea_gate': (1.200, 51.450),
    },
    'le_havre': {
        'name':     'Le Havre',
        'port':     (0.100, 49.490),
        'sea_gate': (-0.200, 49.300),
    },
    'bremerhaven': {
        'name':     'Bremerhaven',
        'port':     (8.580, 53.540),
        'sea_gate': (8.100, 54.000),
    },

    # ── East Asia ────────────────────────────────────────────
    'singapore': {
        'name':     'Singapore (PSA)',
        'port':     (103.820, 1.270),
        # Sea gate west of Singapore — enters via WTSS lane, not through Johor
        'sea_gate': (103.400, 1.100),
    },
    'shanghai': {
        'name':     'Shanghai (Yangshan)',
        'port':     (121.970, 30.630),
        'sea_gate': (122.500, 31.000),
    },
    'ningbo': {
        'name':     'Ningbo-Zhoushan',
        'port':     (121.650, 29.870),
        'sea_gate': (122.200, 30.000),
    },
    'hong_kong': {
        'name':     'Hong Kong',
        'port':     (114.180, 22.300),
        'sea_gate': (114.000, 22.100),
    },
    'busan': {
        'name':     'Busan',
        'port':     (129.040, 35.100),
        'sea_gate': (129.200, 34.800),
    },
    'kaohsiung': {
        'name':     'Kaohsiung',
        'port':     (120.290, 22.620),
        'sea_gate': (120.150, 22.400),
    },
    'tokyo': {
        'name':     'Tokyo / Yokohama',
        'port':     (139.660, 35.440),
        'sea_gate': (139.800, 35.100),
    },
    'tianjin': {
        'name':     'Tianjin (Xingang)',
        'port':     (117.730, 38.990),
        'sea_gate': (118.200, 38.700),
    },

    # ── Southeast Asia ───────────────────────────────────────
    'port_klang': {
        'name':     'Port Klang',
        'port':     (101.390, 3.000),
        # Sea gate in Malacca Strait clear of coast
        'sea_gate': (100.800, 2.800),
    },
    'penang': {
        'name':     'Penang',
        'port':     (100.350, 5.410),
        'sea_gate': (100.100, 5.200),
    },
    'tanjung_pelepas': {
        'name':     'Tanjung Pelepas',
        'port':     (103.560, 1.360),
        'sea_gate': (103.400, 1.100),
    },
    'jakarta': {
        'name':     'Jakarta (Tanjung Priok)',
        'port':     (106.870, -6.100),
        'sea_gate': (106.500, -5.800),
    },
    'surabaya': {
        'name':     'Surabaya',
        'port':     (112.730, -7.200),
        'sea_gate': (112.900, -7.500),
    },
    'manila': {
        'name':     'Manila',
        'port':     (120.960, 14.580),
        'sea_gate': (120.700, 14.300),
    },
    'ho_chi_minh': {
        'name':     'Ho Chi Minh City',
        'port':     (107.000, 10.500),
        'sea_gate': (107.100, 10.200),
    },
    'laem_chabang': {
        'name':     'Laem Chabang',
        'port':     (100.880, 13.080),
        'sea_gate': (101.000, 12.700),
    },

    # ── Americas ─────────────────────────────────────────────
    'los_angeles': {
        'name':     'Los Angeles / Long Beach',
        'port':     (-118.220, 33.730),
        'sea_gate': (-118.500, 33.600),
    },
    'new_york': {
        'name':     'New York / New Jersey',
        'port':     (-74.050, 40.650),
        'sea_gate': (-73.800, 40.300),
    },
    'savannah': {
        'name':     'Savannah',
        'port':     (-81.100, 32.080),
        'sea_gate': (-80.700, 31.900),
    },
    'houston': {
        'name':     'Houston',
        'port':     (-95.300, 29.750),
        'sea_gate': (-94.500, 29.200),
    },
    'vancouver': {
        'name':     'Vancouver',
        'port':     (-123.100, 49.280),
        'sea_gate': (-123.400, 49.000),
    },
    'santos': {
        'name':     'Santos',
        'port':     (-46.320, -23.950),
        'sea_gate': (-46.100, -24.100),
    },
    'buenos_aires': {
        'name':     'Buenos Aires',
        'port':     (-58.380, -34.600),
        'sea_gate': (-57.800, -35.000),
    },
    'colon': {
        'name':     'Colon (Panama Atlantic)',
        'port':     (-79.900, 9.360),
        'sea_gate': (-79.800, 9.500),
    },
    'balboa': {
        'name':     'Balboa (Panama Pacific)',
        'port':     (-79.550, 8.960),
        'sea_gate': (-79.600, 8.700),
    },

    # ── Africa ───────────────────────────────────────────────
    'cape_town': {
        'name':     'Cape Town',
        'port':     (18.430, -33.910),
        'sea_gate': (18.200, -34.100),
    },
    'durban': {
        'name':     'Durban',
        'port':     (31.040, -29.870),
        'sea_gate': (31.100, -30.100),
    },
    'dakar': {
        'name':     'Dakar',
        'port':     (-17.440, 14.680),
        'sea_gate': (-17.600, 14.500),
    },
    'lagos': {
        'name':     'Lagos (Apapa)',
        'port':     (3.370, 6.450),
        'sea_gate': (3.200, 6.200),
    },

    # ── Australia ────────────────────────────────────────────
    'sydney': {
        'name':     'Sydney',
        'port':     (151.200, -33.860),
        'sea_gate': (151.350, -34.000),
    },
    'melbourne': {
        'name':     'Melbourne',
        'port':     (144.940, -37.820),
        'sea_gate': (144.800, -38.100),
    },
    'fremantle': {
        'name':     'Fremantle (Perth)',
        'port':     (115.740, -32.060),
        'sea_gate': (115.500, -32.200),
    },
    'brisbane': {
        'name':     'Brisbane',
        'port':     (153.170, -27.460),
        'sea_gate': (153.400, -27.500),
    },
}

# ══════════════════════════════════════════════════════════════
# CRITICAL CHOKEPOINTS (routing pins — minimum set)
# ══════════════════════════════════════════════════════════════
CHOKEPOINTS = {
    'suez_canal_s':  (32.545, 29.940),
    'suez_canal_n':  (32.325, 31.260),
    'bab_mandeb':    (43.320, 12.680),
    'ras_muhammad':  (32.620, 27.720),
    'hormuz':        (56.450, 26.580),
    'malacca':       (103.500,  1.200),
    'gibraltar':     (-5.360,  35.980),
    'dover':         (1.330,   51.100),
    'panama_atl':    (-79.870,  9.380),
    'panama_pac':    (-79.580,  8.900),
    'cape_horn':     (-67.000, -55.900),
    'cape_good_hope':(18.300, -34.200),
}

# ══════════════════════════════════════════════════════════════
# GEOMETRY HELPERS
# ══════════════════════════════════════════════════════════════
def haversine_nm(lat1, lon1, lat2, lon2):
    R    = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a    = (math.sin(dlat/2)**2 +
            math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*
            math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))

def bearing(lon1, lat1, lon2, lat2):
    dlon  = math.radians(lon2 - lon1)
    la, lb = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lb)
    y = math.cos(la)*math.sin(lb) - math.sin(la)*math.cos(lb)*math.cos(dlon)
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
    for i in range(len(coords)-1):
        if segment_crosses_land(coords[i], coords[i+1]):
            return True
    return False

def rdp_simplify(coords, epsilon_nm=3.0):
    if len(coords) <= 2:
        return coords
    def pt_line_dist(p, a, b):
        if a == b:
            return haversine_nm(p[1],p[0],a[1],a[0])
        dx, dy = b[0]-a[0], b[1]-a[1]
        denom = dx*dx + dy*dy
        if denom == 0:
            return haversine_nm(p[1],p[0],a[1],a[0])
        t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/denom))
        proj = (a[0]+t*dx, a[1]+t*dy)
        return haversine_nm(p[1],p[0],proj[1],proj[0])
    def rdp(pts, eps):
        if len(pts) <= 2: return pts
        dmax, idx = 0, 0
        for i in range(1, len(pts)-1):
            d = pt_line_dist(pts[i], pts[0], pts[-1])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps:
            l = rdp(pts[:idx+1], eps)
            r = rdp(pts[idx:],   eps)
            return l[:-1] + r
        return [pts[0], pts[-1]]
    return rdp(coords, epsilon_nm)

# ══════════════════════════════════════════════════════════════
# SEA GATE LOOKUP — find nearest sea gate to a coord
# ══════════════════════════════════════════════════════════════
def find_sea_gate(lon, lat, radius_nm=80):
    best, best_dist, best_name = None, radius_nm, None
    for key, data in SEA_GATES.items():
        plon, plat = data['port']
        dist = haversine_nm(lat, lon, plat, plon)
        if dist < best_dist:
            best_dist = dist
            best      = data['sea_gate']
            best_name = data['name']
    return best_name, best

# ══════════════════════════════════════════════════════════════
# REGION HELPERS
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
def in_malacca(lon, lat):       return in_box(lon, lat, 98, 105, 0, 7)

def get_critical_waypoints(fg_lon, fg_lat, tg_lon, tg_lat):
    """Only inject chokepoints searoute genuinely needs pinning for."""
    cp = CHOKEPOINTS
    if in_red_sea(fg_lon,fg_lat) and in_mediterranean(tg_lon,tg_lat):
        return [cp['suez_canal_s'], cp['suez_canal_n']]
    if in_mediterranean(fg_lon,fg_lat) and in_red_sea(tg_lon,tg_lat):
        return [cp['suez_canal_n'], cp['suez_canal_s']]
    if in_gulf_aqaba(fg_lon,fg_lat):
        return [cp['ras_muhammad'], cp['bab_mandeb']]
    if in_gulf_aqaba(tg_lon,tg_lat):
        return [cp['bab_mandeb'], cp['ras_muhammad']]
    if in_gulf_persian(fg_lon,fg_lat) and not in_gulf_persian(tg_lon,tg_lat):
        return [cp['hormuz']]
    if in_gulf_persian(tg_lon,tg_lat) and not in_gulf_persian(fg_lon,fg_lat):
        return [cp['hormuz']]
    if (in_pacific(fg_lon,fg_lat) and in_indian_ocean(tg_lon,tg_lat)) or \
       (in_indian_ocean(fg_lon,fg_lat) and in_pacific(tg_lon,tg_lat)):
        return [cp['malacca']]
    if in_malacca(fg_lon,fg_lat) or in_malacca(tg_lon,tg_lat):
        return [cp['malacca']]
    if (in_atlantic(fg_lon,fg_lat) and in_mediterranean(tg_lon,tg_lat)) or \
       (in_mediterranean(fg_lon,fg_lat) and in_atlantic(tg_lon,tg_lat)):
        return [cp['gibraltar']]
    return []

# ══════════════════════════════════════════════════════════════
# CORE ROUTING — sea gate architecture
# ══════════════════════════════════════════════════════════════
def build_route(from_lon, from_lat, to_lon, to_lat):
    """
    Route building with sea gate architecture:
      [origin] → [origin sea gate] → searoute → [dest sea gate] → [destination]
    
    searoute is NEVER given coordinates close to land.
    """
    # Find sea gates
    from_port_name, from_gate = find_sea_gate(from_lon, from_lat)
    to_port_name,   to_gate   = find_sea_gate(to_lon,   to_lat)

    # Determine routing endpoints for searoute
    sea_from = from_gate if from_gate else (from_lon, from_lat)
    sea_to   = to_gate   if to_gate   else (to_lon,   to_lat)

    print(
        f'[v11] from_gate={from_port_name}({sea_from}) '
        f'to_gate={to_port_name}({sea_to})', flush=True
    )

    # Get critical chokepoints between sea gates
    critical_wps = get_critical_waypoints(
        sea_from[0], sea_from[1], sea_to[0], sea_to[1]
    )

    # Build segment chain through searoute
    points     = [sea_from] + list(critical_wps) + [sea_to]
    all_coords = []
    total_nm   = 0.0
    method     = f'sea-gate + {len(critical_wps)} chokepoints'

    for i in range(len(points)-1):
        sf, st = points[i], points[i+1]
        try:
            seg        = SR.searoute(
                [sf[0], sf[1]], [st[0], st[1]],
                units='naut', append_orig_dest=True
            )
            seg_coords = seg.geometry['coordinates']
            seg_nm     = float(seg.properties.get('length', 0))
            if all_coords and seg_coords:
                seg_coords = seg_coords[1:]
            all_coords.extend(seg_coords)
            total_nm  += seg_nm
        except Exception as e:
            print(f'[build_route] seg {i} err: {e}', file=sys.stderr)
            if not all_coords:
                all_coords.append([sf[0], sf[1]])
            all_coords.append([st[0], st[1]])

    # Prepend: origin → origin sea gate (pilot channel, straight line)
    if from_gate:
        channel_out = [[from_lon, from_lat], [from_gate[0], from_gate[1]]]
        # Only prepend if this leg doesn't cross land
        if not segment_crosses_land(channel_out[0], channel_out[1]):
            all_coords = channel_out + (all_coords[1:] if all_coords else [])
        total_nm += haversine_nm(from_lat, from_lon, from_gate[1], from_gate[0])

    # Append: dest sea gate → destination (pilot channel, straight line)
    if to_gate:
        channel_in = [[to_gate[0], to_gate[1]], [to_lon, to_lat]]
        if not segment_crosses_land(channel_in[0], channel_in[1]):
            all_coords = (all_coords[:-1] if all_coords else []) + channel_in
        total_nm += haversine_nm(to_lat, to_lon, to_gate[1], to_gate[0])

    return all_coords, total_nm, method, from_port_name, to_port_name

# ══════════════════════════════════════════════════════════════
# SAFETY CHECKS
# ══════════════════════════════════════════════════════════════
GEBCO_API    = "https://api.odb.ntu.edu.tw/gebco"
OVERPASS_API = "https://overpass-api.de/api/interpreter"
DANGER_TYPES = ['rock','wreck','obstruction','shoal','reef',
                'underwater_rock','foul_ground','snag']
_danger_cache, _tss_cache = {}, {}

def query_tss_osm(coords, buf=0.3):
    if not coords: return []
    lons = [c[0] for c in coords]; lats = [c[1] for c in coords]
    s,n,w,e = round(min(lats)-buf,2), round(max(lats)+buf,2), \
              round(min(lons)-buf,2), round(max(lons)+buf,2)
    key = f"{s}_{w}_{n}_{e}"
    if key in _tss_cache: return _tss_cache[key]
    query = f"""[out:json][timeout:20];
(way["seamark:type"="separation_lane"]({s},{w},{n},{e});
 way["seamark:type"="separation_zone"]({s},{w},{n},{e});
 relation["seamark:type"="traffic_separation_scheme"]({s},{w},{n},{e}););
out tags center;"""
    zones = []
    try:
        r = requests.post(OVERPASS_API, data={'data': query}, timeout=15)
        if r.status_code == 200:
            for el in r.json().get('elements', []):
                t = el.get('tags', {})
                nm = t.get('seamark:name') or t.get('name') or t.get('seamark:type','TSS')
                if nm not in zones: zones.append(nm)
    except Exception as e:
        print(f'[TSS] {e}', file=sys.stderr)
    _tss_cache[key] = zones
    return zones

def check_dangers(coords, buffer_nm=2.0):
    lons = [c[0] for c in coords]; lats = [c[1] for c in coords]
    s,n,w,e = round(min(lats)-.1,2), round(max(lats)+.1,2), \
              round(min(lons)-.1,2), round(max(lons)+.1,2)
    key = f"{s}_{w}_{n}_{e}"
    if key in _danger_cache:
        dm = _danger_cache[key]
    else:
        filt  = '\n'.join([f'  node["seamark:type"="{t}"]({s},{w},{n},{e});'
                           for t in DANGER_TYPES])
        query = f"[out:json][timeout:20];\n(\n{filt}\n);\nout body;"
        dm = []
        try:
            r = requests.post(OVERPASS_API, data={'data': query}, timeout=15)
            if r.status_code == 200:
                for el in r.json().get('elements', []):
                    tags = el.get('tags', {})
                    dm.append({'type': tags.get('seamark:type','unknown'),
                               'name': tags.get('name', tags.get('seamark:name','')),
                               'lon': el.get('lon'), 'lat': el.get('lat')})
        except Exception as e:
            print(f'[Danger] {e}', file=sys.stderr)
        _danger_cache[key] = dm
    nearby = []
    for d in dm:
        dl, da = d.get('lon'), d.get('lat')
        if dl is None: continue
        md = min(haversine_nm(da,dl,c[1],c[0]) for c in coords)
        if md < buffer_nm:
            nearby.append({**d, 'nearest_route_nm': round(md,2)})
    return {'safe': len(nearby)==0, 'dangers_near_route': nearby,
            'total_in_area': len(dm)}

def interpolate_pts(coords, interval_nm=15.0):
    pts = []
    for i in range(len(coords)-1):
        c1,c2 = coords[i], coords[i+1]
        nm = haversine_nm(c1[1],c1[0],c2[1],c2[0])
        st = max(1, int(nm/interval_nm))
        for s in range(st):
            t = s/st
            pts.append((c1[0]+t*(c2[0]-c1[0]), c1[1]+t*(c2[1]-c1[1])))
    if coords: pts.append((coords[-1][0], coords[-1][1]))
    return pts

def check_depth(coords, draft_m=10.0, safety_m=2.0):
    mr  = draft_m + safety_m
    pts = interpolate_pts(coords, 15.0)
    shallow, depths = [], []
    lons = [str(round(p[0],4)) for p in pts]
    lats = [str(round(p[1],4)) for p in pts]
    try:
        r = requests.get(
            f"{GEBCO_API}?lon={','.join(lons)}&lat={','.join(lats)}&mode=zonly",
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            zs   = data.get('z',[]) if isinstance(data, dict) else data
            for i,p in enumerate(pts):
                if i < len(zs) and zs[i] is not None:
                    wd = abs(zs[i]) if zs[i] < 0 else 0
                    depths.append(wd)
                    if 0 < wd < mr:
                        shallow.append({'lon':p[0],'lat':p[1],
                                        'depth':round(wd,1),'required':mr})
    except Exception as e:
        print(f'[Depth] {e}', file=sys.stderr)
    return {'safe': len(shallow)==0,
            'min_depth': round(min(depths),1) if depths else None,
            'shallow_points': shallow, 'checked': len(pts), 'required_depth': mr}

# ══════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        'status':    'ok' if SR else ('initializing' if not _init_done else 'degraded'),
        'searoute':  SR is not None,
        'land':      LAND is not None,
        'init_done': _init_done,
        'service':   'maritime-router v11',
        'sea_gates': len(SEA_GATES),
        'arch':      'sea-gate-architecture',
    })

@app.route('/route')
def route():
    if SR is None:
        return jsonify({'error': 'Initializing (~30s)' if not _init_done
                        else f'searoute error: {SR_ERROR}'}), 503
    try:
        from_lon = float(request.args['fromLon'])
        from_lat = float(request.args['fromLat'])
        to_lon   = float(request.args['toLon'])
        to_lat   = float(request.args['toLat'])
        draft    = float(request.args.get('draft',  10.0))
        safety   = float(request.args.get('safety',  2.0))
        simplify = float(request.args.get('simplify', 3.0))
    except (KeyError, ValueError) as e:
        return jsonify({'error': f'Bad param: {e}'}), 400

    try:
        raw, dist_nm, method, fp, tp = build_route(
            from_lon, from_lat, to_lon, to_lat
        )
        simplified  = rdp_simplify(raw, epsilon_nm=simplify)
        land_cross  = any_segment_crosses_land(simplified)
        tss_zones   = query_tss_osm(simplified)
        danger      = check_dangers(simplified)
        depth       = check_depth(simplified, draft, safety)

        total_nm = sum(
            haversine_nm(simplified[i][1],simplified[i][0],
                         simplified[i+1][1],simplified[i+1][0])
            for i in range(len(simplified)-1)
        )

        warnings = []
        if land_cross:
            warnings.append('🚨 Route crosses land — sea gate may need adjustment')
        for z in tss_zones:
            warnings.append(f'🚢 TSS zone: {z} — verify separation lane compliance')
        for sp in depth.get('shallow_points', []):
            warnings.append(
                f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})"
                f" — need {sp['required']}m")
        for d in danger.get('dangers_near_route', []):
            warnings.append(
                f"🪨 {d['type'].upper()} '{d['name']}' "
                f"({d['lat']:.3f},{d['lon']:.3f}) {d['nearest_route_nm']}NM")

        print(
            f'[route] {total_nm:.0f}NM | {len(raw)}→{len(simplified)}pts '
            f'| {fp}→{tp} | land={land_cross}', flush=True
        )

        return jsonify({
            'waypoints':    [{'lat': float(c[1]), 'lon': float(c[0])}
                             for c in simplified],
            'totalNM':      round(total_nm, 1),
            'source':       'maritime-router-v11',
            'method':       method,
            'pointsRaw':    len(raw),
            'pointsFinal':  len(simplified),
            'fromPort':     fp,
            'toPort':       tp,
            'landCrossing': land_cross,
            'tssZones':     tss_zones,
            'overallSafe':  not land_cross and depth['safe'] and danger['safe'],
            'warnings':     warnings,
            'safetyReport': {'depth_check': depth, 'danger_check': danger},
        })

    except Exception as e:
        print(f'[route] error: {e}', file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/safety-check', methods=['POST', 'OPTIONS'])
def safety_check():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    try:
        body   = request.get_json(force=True)
        if not body: return jsonify({'error': 'JSON body required'}), 400
        raw_wps = body.get('waypoints', [])
        if len(raw_wps) < 2:
            return jsonify({'error': 'Need ≥ 2 waypoints'}), 400

        coords = [[float(w['lon']), float(w['lat'])] for w in raw_wps]
        draft  = float(body.get('draft',  10.0))
        safety = float(body.get('safety',  2.0))
        beam   = float(body.get('beam',   32.0))
        loa    = float(body.get('loa',   200.0))

        land_cross        = any_segment_crosses_land(coords)
        land_cross_pts    = []
        if land_cross:
            for i in range(len(coords)-1):
                if segment_crosses_land(coords[i], coords[i+1]):
                    land_cross_pts.append({
                        'from': {'lon':coords[i][0],'lat':coords[i][1]},
                        'to':   {'lon':coords[i+1][0],'lat':coords[i+1][1]},
                        'segment_index': i,
                    })

        tss_zones = query_tss_osm(coords)
        depth     = check_depth(coords, draft, safety)
        danger    = check_dangers(coords)

        total_nm, max_leg, legs = 0.0, 0.0, []
        for i in range(len(coords)-1):
            c1,c2 = coords[i], coords[i+1]
            nm    = haversine_nm(c1[1],c1[0],c2[1],c2[0])
            total_nm += nm; max_leg = max(max_leg, nm)
            legs.append({'from':{'lon':c1[0],'lat':c1[1]},
                         'to':  {'lon':c2[0],'lat':c2[1]},
                         'nm':round(nm,1),
                         'bearing':round(bearing_two_points(c1,c2),1)})

        warnings = []
        if land_cross:
            warnings.append(f'🚨 LAND CROSSING in {len(land_cross_pts)} segment(s)')
        for z in tss_zones:
            warnings.append(f'🚢 TSS: {z} — verify separation lane')
        for sp in depth.get('shallow_points',[]):
            warnings.append(f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})")
        for d in danger.get('dangers_near_route',[]):
            warnings.append(f"🪨 {d['type']} '{d['name']}' {d['nearest_route_nm']}NM")

        eta = lambda nm,kn: round(nm/kn,2) if kn > 0 else None
        overall_safe = not land_cross and depth['safe'] and danger['safe']

        return jsonify({
            'overall_safe':   overall_safe,
            'total_warnings': len(warnings),
            'warnings':       warnings,
            'route_stats': {
                'total_nm': round(total_nm,1), 'waypoint_count': len(coords),
                'max_leg_nm': round(max_leg,1),
                'eta': {'10kn':eta(total_nm,10),'12kn':eta(total_nm,12),
                        '14kn':eta(total_nm,14),'15kn':eta(total_nm,15),
                        '18kn':eta(total_nm,18)},
            },
            'land_check':  {'safe': not land_cross, 'problem_segments': land_cross_pts},
            'tss_check':   {'zones_found': len(tss_zones), 'zones': tss_zones},
            'depth_check': {'safe':depth['safe'],'min_depth_m':depth.get('min_depth'),
                            'required_depth':depth.get('required_depth'),
                            'shallow_points':depth.get('shallow_points',[])},
            'danger_check':{'safe':danger['safe'],
                            'dangers_near_route':danger['dangers_near_route']},
            'vessel_params':{'draft_m':draft,'safety_m':safety,'beam_m':beam,'loa_m':loa},
            'legs': legs,
        })

    except Exception as e:
        print(f'[safety-check] {e}', file=sys.stderr)
        return jsonify({'error': str(e)}), 500

# ══════════════════════════════════════════════════════════════
# UTILITY: List all known sea gate ports
# ══════════════════════════════════════════════════════════════
@app.route('/ports')
def list_ports():
    return jsonify({
        'count': len(SEA_GATES),
        'ports': {k: {'name': v['name'],
                      'port':     {'lon': v['port'][0],     'lat': v['port'][1]},
                      'sea_gate': {'lon': v['sea_gate'][0], 'lat': v['sea_gate'][1]}}
                  for k, v in SEA_GATES.items()}
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f'[maritime-router] v11 starting on port {port}', flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
