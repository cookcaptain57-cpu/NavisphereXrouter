"""
Fix 4: Depth Check — Avoid Shallow Waters & Danger Marks
=========================================================
Two layers of protection:
  Layer 1 → GEBCO free REST API  — checks water depth along route
  Layer 2 → OpenSeaMap Overpass  — checks for rocks/wrecks/shoals near route

Data Sources (all FREE):
  GEBCO:     https://api.odb.ntu.edu.tw/gebco  (free, no key needed)
  OpenSeaMap via Overpass API: https://overpass-api.de
"""

import math
import requests
import json
import time

# ── Constants ─────────────────────────────────────────────────
GEBCO_API     = "https://api.odb.ntu.edu.tw/gebco"
OVERPASS_API  = "https://overpass-api.de/api/interpreter"
CHECK_INTERVAL_NM = 10   # check depth every 10 NM along route
DANGER_BUFFER_NM  = 2.0  # flag danger marks within 2 NM of route

# Danger seamark types from OpenSeaMap / OSM
DANGER_SEAMARK_TYPES = [
    'rock',           # rocks
    'wreck',          # wrecks
    'obstruction',    # obstructions
    'shoal',          # shoals
    'reef',           # reefs
    'underwater_rock',# underwater rocks
    'foul_ground',    # foul ground
    'snag',           # snags
    'sandwave',       # sandwaves
]

# cache to avoid duplicate API calls
_depth_cache = {}
_danger_cache = {}


def _haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))


def _interpolate_points(coords, interval_nm=10.0):
    """
    Generate check points every interval_nm along route.
    coords = list of [lon, lat]
    Returns list of (lon, lat) tuples to check.
    """
    check_points = []
    accumulated = 0.0

    for i in range(len(coords) - 1):
        c1 = coords[i]
        c2 = coords[i + 1]
        seg_nm = _haversine_nm(c1[1], c1[0], c2[1], c2[0])

        steps = max(1, int(seg_nm / interval_nm))
        for s in range(steps):
            t = s / steps
            lon = c1[0] + t * (c2[0] - c1[0])
            lat = c1[1] + t * (c2[1] - c1[1])
            check_points.append((lon, lat))

    # always include final point
    if coords:
        check_points.append((coords[-1][0], coords[-1][1]))

    return check_points


# ── LAYER 1: GEBCO Depth Check ─────────────────────────────────
def get_depth_gebco(lon, lat):
    """
    Query GEBCO free API for water depth at (lon, lat).
    Returns depth in meters (negative = below sea level).
    Returns None on error.
    """
    key = (round(lon, 2), round(lat, 2))
    if key in _depth_cache:
        return _depth_cache[key]

    try:
        url = f"{GEBCO_API}?lon={lon}&lat={lat}&mode=zonly"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Response format: {"z": [-1234.5]}
            depth = None
            if isinstance(data, dict) and 'z' in data:
                depth = data['z'][0] if isinstance(data['z'], list) else data['z']
            elif isinstance(data, list) and len(data) > 0:
                depth = data[0]
            _depth_cache[key] = depth
            return depth
    except Exception as e:
        print(f'[DepthCheck] GEBCO API error at ({lon},{lat}): {e}')

    return None


def check_route_depth_batch(coords, vessel_draft_m=10.0, safety_margin_m=2.0):
    """
    Check depth at sample points along route.
    vessel_draft_m   = vessel draft in meters (from vessel params)
    safety_margin_m  = safety margin added to draft

    Returns:
        {
          'safe': True/False,
          'min_depth': float,         # shallowest point found (meters)
          'shallow_points': [         # list of problem points
              {'lon', 'lat', 'depth', 'required'}
          ],
          'checked': int              # how many points checked
        }
    """
    min_required = vessel_draft_m + safety_margin_m  # e.g. 10+2 = 12m minimum
    check_pts    = _interpolate_points(coords, CHECK_INTERVAL_NM)

    shallow_points = []
    depths_found   = []

    # Batch query — GEBCO supports multiple lon/lat
    lons = [str(round(p[0], 4)) for p in check_pts]
    lats = [str(round(p[1], 4)) for p in check_pts]

    try:
        url  = f"{GEBCO_API}?lon={','.join(lons)}&lat={','.join(lats)}&mode=zonly"
        resp = requests.get(url, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            depths = data.get('z', []) if isinstance(data, dict) else data

            for i, pt in enumerate(check_pts):
                if i < len(depths):
                    depth = depths[i]
                    if depth is not None:
                        depths_found.append(abs(depth))
                        # GEBCO: negative = sea, positive = land
                        # We want the absolute depth below surface
                        water_depth = abs(depth) if depth < 0 else 0

                        if water_depth < min_required and water_depth > 0:
                            shallow_points.append({
                                'lon':      pt[0],
                                'lat':      pt[1],
                                'depth':    round(water_depth, 1),
                                'required': min_required,
                            })

    except Exception as e:
        print(f'[DepthCheck] Batch GEBCO error: {e}')
        # Fallback: individual point checks
        for pt in check_pts[:20]:  # limit to 20 to avoid timeout
            depth = get_depth_gebco(pt[0], pt[1])
            if depth is not None:
                water_depth = abs(depth) if depth < 0 else 0
                depths_found.append(water_depth)
                if water_depth < min_required and water_depth > 0:
                    shallow_points.append({
                        'lon':      pt[0],
                        'lat':      pt[1],
                        'depth':    round(water_depth, 1),
                        'required': min_required,
                    })
            time.sleep(0.05)  # small delay for individual calls

    return {
        'safe':          len(shallow_points) == 0,
        'min_depth':     round(min(depths_found), 1) if depths_found else None,
        'shallow_points': shallow_points,
        'checked':       len(check_pts),
        'required_depth': min_required,
    }


# ── LAYER 2: OpenSeaMap Danger Marks Check ─────────────────────
def _get_route_bbox(coords, buffer_deg=0.1):
    """Get bounding box around route with buffer."""
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return {
        'south': min(lats) - buffer_deg,
        'north': max(lats) + buffer_deg,
        'west':  min(lons) - buffer_deg,
        'east':  max(lons) + buffer_deg,
    }


def fetch_danger_marks(coords):
    """
    Query OpenSeaMap via Overpass API for danger marks near route.
    Returns list of danger features with type, position, name.
    """
    bbox  = _get_route_bbox(coords, buffer_deg=0.05)
    # Overpass QL: bbox format is (south, west, north, east)
    bbox_str = f"{bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"

    # Build query for all danger seamark types
    type_filters = '\n'.join([
        f'  node["seamark:type"="{t}"]({bbox_str});'
        for t in DANGER_SEAMARK_TYPES
    ])

    query = f"""
[out:json][timeout:25];
(
{type_filters}
);
out body;
"""
    cache_key = f"{round(bbox['south'],2)}_{round(bbox['west'],2)}_{round(bbox['north'],2)}_{round(bbox['east'],2)}"
    if cache_key in _danger_cache:
        return _danger_cache[cache_key]

    dangers = []
    try:
        resp = requests.post(
            OVERPASS_API,
            data={'data': query},
            timeout=20
        )
        if resp.status_code == 200:
            data = resp.json()
            for element in data.get('elements', []):
                tags = element.get('tags', {})
                dangers.append({
                    'type':  tags.get('seamark:type', 'unknown'),
                    'name':  tags.get('name', tags.get('seamark:name', '')),
                    'lon':   element.get('lon'),
                    'lat':   element.get('lat'),
                    'tags':  {k: v for k, v in tags.items()
                              if 'seamark' in k or k == 'name'},
                })
    except Exception as e:
        print(f'[DangerCheck] Overpass error: {e}')

    _danger_cache[cache_key] = dangers
    return dangers


def check_route_dangers(coords, buffer_nm=DANGER_BUFFER_NM):
    """
    Check if any danger marks are within buffer_nm of route.

    Returns:
        {
          'safe': True/False,
          'dangers_near_route': [
              {'type', 'name', 'lon', 'lat', 'nearest_route_nm'}
          ]
        }
    """
    danger_marks   = fetch_danger_marks(coords)
    dangers_nearby = []

    for danger in danger_marks:
        dlon = danger.get('lon')
        dlat = danger.get('lat')
        if dlon is None or dlat is None:
            continue

        # Find minimum distance from danger to any route segment
        min_dist = float('inf')
        for coord in coords:
            dist = _haversine_nm(dlat, dlon, coord[1], coord[0])
            if dist < min_dist:
                min_dist = dist

        if min_dist < buffer_nm:
            dangers_nearby.append({
                'type':              danger['type'],
                'name':              danger['name'],
                'lon':               dlon,
                'lat':               dlat,
                'nearest_route_nm':  round(min_dist, 2),
            })

    return {
        'safe':               len(dangers_nearby) == 0,
        'dangers_near_route': dangers_nearby,
        'total_dangers_in_area': len(danger_marks),
    }


# ── COMBINED: Full Fix 4 check ─────────────────────────────────
def run_depth_and_danger_check(coords, vessel_draft_m=10.0, safety_margin_m=2.0):
    """
    Master function — runs both depth + danger checks.
    Call this from app.py after route is built.

    Returns full safety report.
    """
    print(f'[Fix4] Running depth + danger check | draft={vessel_draft_m}m | '
          f'{len(coords)} waypoints', flush=True)

    depth_result  = check_route_depth_batch(coords, vessel_draft_m, safety_margin_m)
    danger_result = check_route_dangers(coords)

    overall_safe = depth_result['safe'] and danger_result['safe']

    report = {
        'overall_safe':    overall_safe,
        'depth_check':     depth_result,
        'danger_check':    danger_result,
        'vessel_draft_m':  vessel_draft_m,
        'safety_margin_m': safety_margin_m,
        'warnings':        [],
    }

    # Build human-readable warnings
    if not depth_result['safe']:
        for sp in depth_result['shallow_points']:
            report['warnings'].append(
                f"⚠️ Shallow water {sp['depth']}m at "
                f"({sp['lat']:.3f},{sp['lon']:.3f}) — need {sp['required']}m"
            )

    if not danger_result['safe']:
        for d in danger_result['dangers_near_route']:
            report['warnings'].append(
                f"🪨 {d['type'].upper()} '{d['name']}' at "
                f"({d['lat']:.3f},{d['lon']:.3f}) — {d['nearest_route_nm']}NM from route"
            )

    return report
