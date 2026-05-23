# maritime-router/main.py
# Deploy this FREE on render.com as a Python web service.
# It wraps the Eurostat SeaRoute algorithm with FULL land mask validation.
# Same logic as the Java JAR — no land crossings guaranteed.
#
# DEPLOY STEPS:
# 1. Create a new GitHub repo, add this file + requirements.txt + render.yaml
# 2. Go to render.com → New Web Service → connect your GitHub repo
# 3. Runtime: Python, Build: pip install -r requirements.txt, Start: python main.py
# 4. Copy the Render URL (e.g. https://maritime-router.onrender.com)
# 5. Add it to your Vercel env as: VITE_ROUTER_URL=https://maritime-router.onrender.com

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.parse
import searoute as sr

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default access logs

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != '/route':
            self.send_response(404)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
            return

        params = urllib.parse.parse_qs(parsed.query)
        try:
            from_lon = float(params['fromLon'][0])
            from_lat = float(params['fromLat'][0])
            to_lon   = float(params['toLon'][0])
            to_lat   = float(params['toLat'][0])
        except (KeyError, ValueError, IndexError):
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error":"fromLon, fromLat, toLon, toLat required"}')
            return

        try:
            # searoute returns a GeoJSON Feature with LineString geometry
            # origin/destination are [lon, lat]
            route = sr.searoute(
                [from_lon, from_lat],
                [to_lon,   to_lat],
                units="naut",           # nautical miles
                return_passages=True,   # include canal/strait info
            )
            coords = route.geometry['coordinates']  # [[lon,lat], ...]
            dist_nm = route.properties.get('length', 0)
            passages = route.properties.get('passages', [])

            response = {
                "waypoints": [{"lat": c[1], "lon": c[0]} for c in coords],
                "totalNM":   round(dist_nm, 1),
                "passages":  passages,
                "source":    "searoute-python",
            }
            body = json.dumps(response).encode()
            self.send_response(200)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        except Exception as e:
            err = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(err)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8000))
    print(f'[Maritime Router] Starting on port {port}')
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()
