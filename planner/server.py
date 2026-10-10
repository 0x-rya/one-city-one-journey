"""Offline web server for the One City, One Journey planner.  Run:  python3 -I server.py  -> http://localhost:8008"""
import json, os, sys, collections
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from router import Router  # noqa: E402
from roads import Roads  # noqa: E402

R = Router()
R._trip_conns('warmup')  # build trip index once
RD = Roads()


def snap_plan(opts):
    for o in opts:
        for L in o['legs']:
            if L['kind'] == 'walk' or L['mode'] in ('BRTS', 'AMTS'):
                L['path'] = RD.snap(L['path'])
        fb = (o.get('expected') or {}).get('fallback')
        for L in (fb['legs'] if fb else []):
            if L['kind'] == 'walk' or L['mode'] in ('BRTS', 'AMTS'):
                L['path'] = RD.snap(L['path'])
    return opts


def base_layer():
    roads = []
    src = os.path.join(HERE, 'data', 'osm_major_roads_ahd_gnr.geojson')
    for f in json.load(open(src))['features']:
        if f['properties']['highway'] not in ('motorway', 'trunk', 'primary', 'secondary'):
            continue
        g = f['geometry']
        lines = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
        for ln in lines:
            pts = ln[::3] + ([ln[-1]] if len(ln) % 3 != 1 else [])
            roads.append([[round(y, 4), round(x, 4)] for x, y in pts])
    # metro lines: longest trip per route
    best = {}
    for tid, (rid, _, _) in R.d['trips'].items():
        if rid.startswith('GMRC'):
            n = len(R._trip_conns(tid))
            if n > best.get(rid, (0, None))[0]:
                best[rid] = (n, tid)
    metro = []
    for rid, (_, tid) in best.items():
        cs = R._trip_conns(tid)
        st = R.d['stops']
        pts = [[st[cs[0][2]][1], st[cs[0][2]][2]]] + [[st[c[3]][1], st[c[3]][2]] for c in cs]
        r = R.d['routes'][rid]
        metro.append(dict(name=r['short'], color='#' + (r['color'] or '0B5ED7'), pts=pts))
    stops = []
    mode_by_stop = {}
    for tid, (rid, _, _) in R.d['trips'].items():
        pass
    for sid, (nm, la, lo) in R.d['stops'].items():
        kind = 'METRO' if sid.startswith('GMRC') else ('BRTS' if sid in R.d['brts_area'] else 'BUS')
        stops.append([nm, la, lo, kind])
    return dict(roads=roads, metro=metro, stops=stops)


BASE = json.dumps(base_layer()).encode()


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def log_message(self, *a):
        pass

    def _json(self, obj):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/base':
            return self._json(BASE)
        if u.path == '/plan':
            q = parse_qs(u.query)
            o = tuple(map(float, q['from'][0].split(',')))
            d = tuple(map(float, q['to'][0].split(',')))
            hh, mm = q.get('time', ['09:00'])[0].split(':')
            day = q.get('day', ['wkdy'])[0]
            return self._json(snap_plan(R.plan(o, d, int(hh) * 3600 + int(mm) * 60, day)))
        if u.path == '/heat':
            q = parse_qs(u.query)
            o = tuple(map(float, q['from'][0].split(',')))
            hh, mm = q.get('time', ['09:00'])[0].split(':')
            modes = set(q.get('modes', ['METRO,BRTS,AMTS'])[0].split(','))
            return self._json(R.heat(o, int(hh) * 3600 + int(mm) * 60, modes, q.get('day', ['wkdy'])[0]))
        return super().do_GET()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8008))
    print('One City, One Journey planner -> http://localhost:%d' % port)
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
