"""
TSS Lane Logic — Fix 2
Hardcoded centerline waypoints for world's major TSS zones.
Route snaps to correct lane direction based on origin→destination bearing.
"""
import math

# ── TSS Database ───────────────────────────────────────────────
# Each TSS has:
#   'northbound' / 'eastbound' / 'inbound'  → lane going that direction
#   'southbound' / 'westbound' / 'outbound' → opposite lane
#   Each lane = list of (lon, lat) centerline waypoints IN ORDER

TSS_DATABASE = {

    'dover_strait': {
        'bbox': (-1.5, 50.5, 2.5, 52.0),  # lon_min, lat_min, lon_max, lat_max
        'northbound': [   # NE direction — towards North Sea
            (1.25, 50.87),
            (1.50, 51.10),
            (1.75, 51.30),
            (2.00, 51.50),
        ],
        'southbound': [   # SW direction — towards Atlantic
            (1.60, 51.45),
            (1.35, 51.20),
            (1.10, 51.00),
            (0.85, 50.80),
        ],
        'separation_zone': (1.42, 51.10),  # center of separation zone
    },

    'english_channel_west': {
        'bbox': (-5.5, 49.0, -1.5, 51.0),
        'eastbound': [
            (-5.20, 49.45),
            (-4.00, 49.60),
            (-2.50, 49.80),
            (-1.60, 50.20),
        ],
        'westbound': [
            (-1.80, 50.40),
            (-3.00, 50.10),
            (-4.50, 49.80),
            (-5.40, 49.60),
        ],
    },

    'gibraltar': {
        'bbox': (-6.0, 35.7, -5.2, 36.2),
        'eastbound': [    # entering Mediterranean
            (-5.90, 35.98),
            (-5.60, 35.97),
            (-5.35, 35.96),
        ],
        'westbound': [    # exiting to Atlantic
            (-5.35, 36.02),
            (-5.65, 36.03),
            (-5.90, 36.04),
        ],
    },

    'malacca_strait': {
        'bbox': (98.0, 1.0, 104.5, 6.5),
        'northbound': [   # NW bound — towards Indian Ocean
            (103.50,  1.20),
            (102.50,  2.00),
            (101.50,  3.00),
            (100.50,  4.00),
            (99.50,   5.00),
            (98.50,   5.60),
        ],
        'southbound': [   # SE bound — towards South China Sea
            (103.65,  1.30),
            (102.65,  2.10),
            (101.65,  3.10),
            (100.65,  4.10),
            (99.65,   5.10),
            (98.65,   5.70),
        ],
    },

    'suez_canal': {
        'bbox': (32.2, 29.8, 33.0, 31.5),
        'northbound': [   # heading to Mediterranean
            (32.55, 29.92),
            (32.50, 30.25),
            (32.40, 30.60),
            (32.35, 31.00),
            (32.30, 31.27),
        ],
        'southbound': [   # heading to Red Sea
            (32.33, 31.27),
            (32.38, 31.00),
            (32.43, 30.60),
            (32.48, 30.25),
            (32.55, 29.92),
        ],
    },

    'bab_el_mandeb': {
        'bbox': (42.5, 11.5, 44.5, 13.5),
        'northbound': [   # heading to Red Sea
            (43.42, 11.60),
            (43.35, 12.00),
            (43.30, 12.50),
        ],
        'southbound': [   # heading to Gulf of Aden
            (43.50, 12.55),
            (43.55, 12.05),
            (43.60, 11.65),
        ],
    },

    'hormuz': {
        'bbox': (55.5, 25.5, 57.5, 27.0),
        'inbound': [      # entering Persian Gulf
            (56.30, 26.00),
            (56.50, 26.30),
            (56.70, 26.55),
        ],
        'outbound': [     # exiting Persian Gulf
            (56.80, 26.60),
            (56.60, 26.35),
            (56.40, 26.05),
        ],
    },

    'singapore_strait': {
        'bbox': (103.5, 1.1, 104.5, 1.5),
        'eastbound': [
            (103.55, 1.18),
            (103.75, 1.20),
            (103.95, 1.22),
            (104.20, 1.25),
        ],
        'westbound': [
            (104.22, 1.28),
            (103.97, 1.26),
            (103.77, 1.24),
            (103.57, 1.22),
        ],
    },

    'cape_of_good_hope': {
        'bbox': (17.5, -35.5, 19.5, -33.5),
        'northbound': [
            (18.40, -35.20),
            (18.30, -34.50),
            (18.20, -33.80),
        ],
        'southbound': [
            (18.50, -33.85),
            (18.60, -34.55),
            (18.70, -35.25),
        ],
    },

    'north_sea_german_bight': {
        'bbox': (6.0, 53.5, 9.5, 56.0),
        'northbound': [
            (7.80, 53.80),
            (7.60, 54.50),
            (7.40, 55.20),
        ],
        'southbound': [
            (8.00, 55.25),
            (8.20, 54.55),
            (8.40, 53.85),
        ],
    },
}


def _bearing(lon1, lat1, lon2, lat2):
    """Calculate bearing in degrees from point 1 to point 2."""
    dlon = math.radians(lon2 - lon1)
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r) -
         math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _in_bbox(lon, lat, bbox):
    lon_min, lat_min, lon_max, lat_max = bbox
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _route_crosses_tss(from_lon, from_lat, to_lon, to_lat, bbox):
    """Check if the route line crosses a TSS bounding box."""
    # Simple check: does origin→destination path pass through TSS bbox?
    lon_min, lat_min, lon_max, lat_max = bbox
    steps = 20
    for i in range(steps + 1):
        t = i / steps
        lon = from_lon + t * (to_lon - from_lon)
        lat = from_lat + t * (to_lat - from_lat)
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            return True
    return False


def _pick_lane(tss_data, bearing):
    """Pick correct TSS lane based on vessel bearing."""
    lanes = {}
    if 'northbound' in tss_data:
        lanes['northbound'] = (0, 45, 315)    # N±45°
    if 'southbound' in tss_data:
        lanes['southbound'] = (180, 135, 225)  # S±45°
    if 'eastbound' in tss_data:
        lanes['eastbound'] = (90, 45, 135)    # E±45°
    if 'westbound' in tss_data:
        lanes['westbound'] = (270, 225, 315)  # W±45°
    if 'inbound' in tss_data:
        lanes['inbound'] = (315, 270, 360)    # NW (Persian Gulf inbound)
    if 'outbound' in tss_data:
        lanes['outbound'] = (135, 90, 180)    # SE (Persian Gulf outbound)

    best_lane = None
    best_diff = 999

    for lane_name, (center, lo, hi) in lanes.items():
        diff = abs(((bearing - center) + 180) % 360 - 180)
        if diff < best_diff:
            best_diff = diff
            best_lane = lane_name

    return best_lane


def inject_tss_waypoints(from_lon, from_lat, to_lon, to_lat):
    """
    Main function: returns TSS waypoints to inject into route.
    Call this BEFORE routing to get mandatory TSS waypoints.
    """
    bearing = _bearing(from_lon, from_lat, to_lon, to_lat)
    tss_waypoints = []

    for tss_name, tss_data in TSS_DATABASE.items():
        bbox = tss_data['bbox']

        # Check if route passes through this TSS
        if not _route_crosses_tss(from_lon, from_lat, to_lon, to_lat, bbox):
            continue

        # Pick correct directional lane
        lane_key = _pick_lane(tss_data, bearing)
        if lane_key and lane_key in tss_data:
            lane_wps = tss_data[lane_key]
            tss_waypoints.append({
                'tss': tss_name,
                'lane': lane_key,
                'waypoints': lane_wps,
            })
            print(f'[TSS] Injecting {tss_name} {lane_key} lane ({len(lane_wps)} wps)')

    return tss_waypoints
