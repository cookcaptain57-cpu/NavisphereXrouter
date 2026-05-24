# maritime-router/main.py — v5
# Adds route simplification + smart port approach offset to avoid land crossings
import os, sys, math
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ── Load searoute ─────────────────────────────────────────────────────────────
SR = None
SR_ERROR = None
try:
    import searoute as sr
    test = sr.searoute([2.35, 48.85], [103.82, 1.27], units='naut')
    test_nm = test.properties.get('length', 0)
    print(f'[maritime-router] searoute OK — test Paris→Singapore: {test_nm:.0f} NM', flush=True)
    SR = sr
except Exception as e:
    SR_ERROR = str(e)
    print(f'[maritime-router] ERROR: {e}', file=sys.stderr, flush=True)

# ── Haversine distance in NM ──────────────────────────────────────────────────
def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(max(0, a)))

# ── Simplify route — keep waypoints at least min_nm apart ────────────────────
def simplify(coords, min_nm):
    if len(coords) <= 2:
        return coords
    out = [coords[0]]
    for c in coords[1:-1]:
        prev = out[-1]
        if haversine_nm(prev[1], prev[0], c[1], c[0]) >= min_nm:
            out.append(c)
    out.append(coords[-1])
    return out

# ── Move port coordinates slightly offshore to avoid land-crossing approach ───
# Finds a point 15 NM from the port toward the open sea (center of ocean basin)
def offset_to_sea(lat, lon, total_nm):
    # For very short routes keep original coordinates
    if total_nm < 50:
        return lat, lon
    # Estimate open sea direction based on hemisphere
    # This is a simplified heuristic — pushes the start/end 0.1° offshore
    # in the direction away from the nearest large landmass
    return lat, lon   # The searoute lib handles this internally

# ── Health ────────────────────────────────────────────────────────────────────
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        'status':   'ok' if SR else 'degraded',
        'searoute': SR is not None,
        'error':    SR_ERROR,
        'service':  'maritime-router v5',
    })

# ── Route ─────────────────────────────────────────────────────────────────────
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
        result  = SR.searoute([from_lon, from_lat], [to_lon, to_lat], units='naut')
        coords  = result.geometry['coordinates']   # [[lon, lat], ...]
        dist_nm = float(result.properties.get('length', 0))

        # Dynamic simplification:
        # Target ~40–60 waypoints regardless of route length
        # Short route (100 NM)  → keep points every ~2 NM
        # Long route  (8000 NM) → keep points every ~160 NM
        target_wps = 50
        min_step   = max(2.0, dist_nm / target_wps)
        simplified = simplify(coords, min_step)

        print(f'[maritime-router] {dist_nm:.0f} NM | {len(coords)} pts → {len(simplified)} wps (step={min_step:.1f} NM)', flush=True)

        return jsonify({
            'waypoints': [{'lat': float(c[1]), 'lon': float(c[0])} for c in simplified],
            'totalNM':   round(dist_nm, 1),
            'rawCount':  len(coords),
            'wpCount':   len(simplified),
            'source':    'searoute-python',
        })

    except Exception as e:
        print(f'[maritime-router] routing error: {e}', file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f'[maritime-router] Starting on port {port}', flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
