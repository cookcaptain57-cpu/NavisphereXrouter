"""
Port Approach Waypoints — Fix 3
Pre-defined approach sequences for major world ports.
Activated within 50NM of port — switches from open-sea routing
to buoyed channel / pilot boarding waypoints.
"""
import math

APPROACH_TRIGGER_NM = 50  # activate within 50NM of port

# ── Port Approach Database ─────────────────────────────────────
# Format per port:
#   'coord': (lon, lat)          ← port center
#   'pilot':  (lon, lat)         ← pilot boarding position
#   'approach': [(lon,lat), ...]  ← waypoints FROM sea TO port, in order
#   'fairway_heading': degrees    ← official approach bearing

PORT_APPROACHES = {

    'singapore': {
        'coord': (103.82, 1.27),
        'pilot': (103.57, 1.14),
        'approach': [
            (103.57, 1.14),   # pilot boarding
            (103.65, 1.18),   # fairway buoy
            (103.72, 1.22),   # western anchorage
            (103.80, 1.26),   # port entrance
        ],
        'fairway_heading': 80,
    },

    'rotterdam': {
        'coord': (4.50, 51.92),
        'pilot': (3.50, 51.97),
        'approach': [
            (3.50, 51.97),   # pilot boarding / Maas approach
            (3.80, 51.97),   # Maas Center
            (4.00, 51.95),
            (4.20, 51.93),
            (4.40, 51.92),
            (4.50, 51.92),   # port entrance
        ],
        'fairway_heading': 90,
    },

    'shanghai': {
        'coord': (121.47, 31.23),
        'pilot': (122.20, 31.10),
        'approach': [
            (122.20, 31.10),  # pilot boarding
            (122.00, 31.12),
            (121.80, 31.15),
            (121.60, 31.18),
            (121.47, 31.23),  # port
        ],
        'fairway_heading': 270,
    },

    'suez_port_said': {
        'coord': (32.30, 31.27),
        'pilot': (32.20, 31.35),
        'approach': [
            (32.20, 31.40),   # outer anchorage
            (32.22, 31.35),   # pilot boarding
            (32.25, 31.32),   # breakwater entrance
            (32.30, 31.27),   # canal entrance
        ],
        'fairway_heading': 180,
    },

    'suez_south': {
        'coord': (32.55, 29.92),
        'pilot': (32.60, 29.80),
        'approach': [
            (32.62, 29.72),   # outer anchorage
            (32.60, 29.80),   # pilot boarding
            (32.58, 29.86),
            (32.55, 29.92),   # canal south entrance
        ],
        'fairway_heading': 0,
    },

    'dubai_jebel_ali': {
        'coord': (55.02, 24.98),
        'pilot': (54.90, 24.90),
        'approach': [
            (54.75, 24.80),   # outer
            (54.85, 24.85),
            (54.90, 24.90),   # pilot boarding
            (54.96, 24.94),
            (55.02, 24.98),   # port
        ],
        'fairway_heading': 45,
    },

    'hong_kong': {
        'coord': (114.18, 22.30),
        'pilot': (114.10, 22.18),
        'approach': [
            (114.05, 22.10),  # outer
            (114.10, 22.18),  # pilot boarding
            (114.14, 22.24),
            (114.18, 22.30),  # port
        ],
        'fairway_heading': 10,
    },

    'hamburg': {
        'coord': (9.97, 53.55),
        'pilot': (8.10, 53.99),
        'approach': [
            (8.10, 53.99),    # Cuxhaven pilot boarding
            (8.50, 53.90),
            (8.80, 53.80),
            (9.20, 53.72),
            (9.60, 53.63),
            (9.97, 53.55),    # Hamburg
        ],
        'fairway_heading': 95,
    },

    'antwerp': {
        'coord': (4.40, 51.23),
        'pilot': (3.18, 51.37),
        'approach': [
            (3.18, 51.37),    # pilot boarding Flushing
            (3.50, 51.30),
            (3.80, 51.27),
            (4.10, 51.25),
            (4.40, 51.23),    # Antwerp
        ],
        'fairway_heading': 100,
    },

    'busan': {
        'coord': (129.04, 35.10),
        'pilot': (129.10, 34.95),
        'approach': [
            (129.15, 34.85),  # outer
            (129.10, 34.95),  # pilot boarding
            (129.07, 35.02),
            (129.04, 35.10),  # port
        ],
        'fairway_heading': 355,
    },

    'los_angeles': {
        'coord': (-118.27, 33.73),
        'pilot': (-118.40, 33.65),
        'approach': [
            (-118.55, 33.55), # outer
            (-118.45, 33.60),
            (-118.40, 33.65), # pilot boarding
            (-118.35, 33.69),
            (-118.27, 33.73), # port
        ],
        'fairway_heading': 60,
    },

    'new_york': {
        'coord': (-74.02, 40.65),
        'pilot': (-73.82, 40.45),
        'approach': [
            (-73.80, 40.30),  # ambrose light
            (-73.82, 40.45),  # pilot boarding
            (-73.90, 40.55),
            (-74.02, 40.65),  # port
        ],
        'fairway_heading': 340,
    },

    'colombo': {
        'coord': (79.85, 6.93),
        'pilot': (79.80, 6.88),
        'approach': [
            (79.75, 6.82),
            (79.80, 6.88),    # pilot boarding
            (79.83, 6.91),
            (79.85, 6.93),    # port
        ],
        'fairway_heading': 30,
    },

    'mumbai': {
        'coord': (72.85, 18.92),
        'pilot': (72.75, 18.80),
        'approach': [
            (72.65, 18.70),
            (72.75, 18.80),   # pilot boarding
            (72.80, 18.86),
            (72.85, 18.92),   # port
        ],
        'fairway_heading': 25,
    },
}


def _haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))


def find_nearest_port(lon, lat, radius_nm=50):
    """Find nearest port within radius_nm nautical miles."""
    best = None
    best_dist = radius_nm

    for port_name, port_data in PORT_APPROACHES.items():
        plon, plat = port_data['coord']
        dist = _haversine_nm(lat, lon, plat, plon)
        if dist < best_dist:
            best_dist = dist
            best = (port_name, port_data, dist)

    return best  # (name, data, dist) or None


def get_approach_waypoints(lon, lat, is_destination=True):
    """
    Get approach waypoints for a port near (lon, lat).
    is_destination=True  → return waypoints in approach order (sea→port)
    is_destination=False → return reversed (port→sea = departure)
    """
    result = find_nearest_port(lon, lat)
    if not result:
        return None, None

    port_name, port_data, dist_nm = result
    wps = port_data['approach']

    if not is_destination:
        wps = list(reversed(wps))

    return port_name, wps


def inject_port_approaches(from_lon, from_lat, to_lon, to_lat):
    """
    Returns departure WPs (origin port exit) and arrival WPs (dest port approach).
    These replace the first/last legs of the open-sea route.
    """
    result = {}

    # Origin port departure sequence
    origin_port, origin_wps = get_approach_waypoints(from_lon, from_lat, is_destination=False)
    if origin_port:
        result['origin'] = {
            'port': origin_port,
            'waypoints': origin_wps,
        }
        print(f'[PortApproach] Origin: {origin_port} ({len(origin_wps)} wps)')

    # Destination port arrival sequence
    dest_port, dest_wps = get_approach_waypoints(to_lon, to_lat, is_destination=True)
    if dest_port:
        result['destination'] = {
            'port': dest_port,
            'waypoints': dest_wps,
        }
        print(f'[PortApproach] Destination: {dest_port} ({len(dest_wps)} wps)')

    return result
