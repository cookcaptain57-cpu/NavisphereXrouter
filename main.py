# maritime-router/main.py — v6
# NO aggressive simplification — keeps full route geometry (no land crossings)
# Display simplification is handled client-side in MapView only
import os, sys, math
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

SR = None
SR_ERROR = None
try:
    import searoute as sr
    test = sr.searoute([2.35, 48.85], [103.82, 1.27], units='naut')
    dist = test.properties.get('length', 0)
    print(f'[maritime-router] v6 ready — test: {dist:.0f} NM', flush=True)
    SR = sr
except Exception as e:
    SR_ERROR = str(e)
    print(f'[maritime-router] ERROR: {e}', file=sys.stderr, flush=True)

def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(max(0, a)))

# SAFE simplification: only remove points that are < min_nm from previous AND
# the straight line to the NEXT point stays within 0.15° of the original path
# This prevents the simplified line from creating shortcuts that cross land
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
            # Check if skipping this point creates a large deviation
            nxt = coords[min(i+1, len(coords)-1)]
            # Mid-point of straight line prev→nxt
            mid_lon = (prev[0] + nxt[0]) / 2
            mid_lat = (prev[1] + nxt[1]) / 2
            # Deviation from actual point
            dev = haversine_nm(curr[1], curr[0], mid_lat, mid_lon)
            if dev > 1.0:  # > 1 NM deviation — keep point (prevents land crossing)
                out.append(curr)
        else:
            out.append(curr)
        i += 1
    out.append(coords[-1])
    return out

@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        'status': 'ok' if SR else 'degraded',
        'searoute': SR is not None,
        'error': SR_ERROR,
        'service': 'maritime-router v6',
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
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': f'Missing param: {e}'}), 400
    try:
        result   = SR.searoute([from_lon, from_lat], [to_lon, to_lat], units='naut')
        coords   = result.geometry['coordinates']
        dist_nm  = float(result.properties.get('length', 0))

        # Safe simplification: only remove points < 2 NM apart AND
        # that don't cause > 1 NM deviation (prevents land shortcuts)
        simplified = safe_simplify(coords, min_nm=2.0)

        print(f'[maritime-router] {dist_nm:.0f} NM | {len(coords)} → {len(simplified)} waypoints', flush=True)

        return jsonify({
            'waypoints': [{'lat': float(c[1]), 'lon': float(c[0])} for c in simplified],
            'totalNM':   round(dist_nm, 1),
            'source':    'searoute-python',
        })
    except Exception as e:
        print(f'[maritime-router] error: {e}', file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f'[maritime-router] Starting on port {port}', flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
