# maritime-router/main.py — v3
# More robust: explicit error logging, startup test, fallback if searoute fails
import os, sys, math, json
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── CORS ─────────────────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ── Try loading searoute ──────────────────────────────────────────────────────
SR = None
SR_ERROR = None
try:
    import searoute as sr
    # Quick startup test to verify it actually works
    test = sr.searoute([2.35, 48.85], [103.82, 1.27], units='naut')
    test_nm = test.properties.get('length', 0)
    print(f'[maritime-router] searoute OK — test route: {test_nm:.0f} NM', flush=True)
    SR = sr
except Exception as e:
    SR_ERROR = str(e)
    print(f'[maritime-router] ERROR loading searoute: {e}', file=sys.stderr, flush=True)

# ── Health check ──────────────────────────────────────────────────────────────
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        'status': 'ok' if SR else 'degraded',
        'searoute': SR is not None,
        'error': SR_ERROR,
        'service': 'maritime-router v3',
    })

# ── Route endpoint ────────────────────────────────────────────────────────────
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
        return jsonify({'error': f'Missing or invalid param: {e}. Need fromLon,fromLat,toLon,toLat'}), 400

    try:
        result  = SR.searoute([from_lon, from_lat], [to_lon, to_lat], units='naut')
        coords  = result.geometry['coordinates']   # [[lon, lat], ...]
        dist_nm = result.properties.get('length', 0)
        return jsonify({
            'waypoints': [{'lat': float(c[1]), 'lon': float(c[0])} for c in coords],
            'totalNM':   round(float(dist_nm), 1),
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
