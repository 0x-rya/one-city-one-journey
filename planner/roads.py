"""Snap stop-to-stop bus legs onto the OSM road network (offline) so routes are drawn along real roads."""
import json, os, heapq, collections, math, pickle

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'osm_highways_ahd_gnr.geojson')
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'roads.pkl')
SKIP = {'footway', 'path', 'steps', 'pedestrian', 'track', 'cycleway', 'construction', 'proposed', 'corridor'}


def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def build():
    idx, coords, adj = {}, [], collections.defaultdict(list)

    def nid(lat, lon):
        k = (round(lat, 5), round(lon, 5))
        if k not in idx:
            idx[k] = len(coords)
            coords.append(k)
        return idx[k]

    for f in json.load(open(SRC))['features']:
        if f['properties'].get('highway') in SKIP:
            continue
        g = f['geometry']
        lines = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
        for ln in lines:
            prev = None
            for lon, lat in ln:
                n = nid(lat, lon)
                if prev is not None and prev != n:
                    d = hav(coords[prev], coords[n])
                    adj[prev].append((n, d))
                    adj[n].append((prev, d))   # buses: ignore oneway for drawing purposes
                prev = n
    grid = collections.defaultdict(list)
    for i, (la, lo) in enumerate(coords):
        if i in adj:
            grid[(int(la * 300), int(lo * 300))].append(i)
    return dict(coords=coords, adj=dict(adj), grid=dict(grid))


class Roads:
    def __init__(self):
        if os.path.exists(CACHE):
            self.g = pickle.load(open(CACHE, 'rb'))
        else:
            self.g = build()
            pickle.dump(self.g, open(CACHE, 'wb'), protocol=pickle.HIGHEST_PROTOCOL)
        self.memo = {}

    def nearest(self, p, max_m=250):
        gx, gy = int(p[0] * 300), int(p[1] * 300)
        best, bd = None, max_m
        C = self.g['coords']
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self.g['grid'].get((gx + dx, gy + dy), ()):
                    d = hav(p, C[i])
                    if d < bd:
                        best, bd = i, d
        return best

    def path(self, a, b):
        """Road path between two points, or straight line if no sensible road path."""
        key = (tuple(a), tuple(b))
        if key in self.memo:
            return self.memo[key]
        s, t = self.nearest(a), self.nearest(b)
        out = [list(a), list(b)]
        if s is not None and t is not None and s != t:
            straight = hav(a, b)
            limit = max(straight * 2.5, 600)
            C, adj = self.g['coords'], self.g['adj']
            dist, prev, pq = {s: 0.0}, {}, [(hav(C[s], C[t]), 0.0, s)]
            while pq:
                f, d, u = heapq.heappop(pq)
                if u == t:
                    break
                if d > dist.get(u, 1e18) or d > limit:
                    continue
                for v, w in adj.get(u, ()):
                    nd = d + w
                    if nd < dist.get(v, 1e18):
                        dist[v], prev[v] = nd, u
                        heapq.heappush(pq, (nd + hav(C[v], C[t]), nd, v))
            if t in prev:
                seq = [t]
                while seq[-1] != s:
                    seq.append(prev[seq[-1]])
                seq.reverse()
                out = [list(a)] + [list(C[i]) for i in seq] + [list(b)]
        self.memo[key] = out
        return out

    def snap(self, pts):
        if len(pts) < 2:
            return pts
        res = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            res.extend(self.path(a, b)[1:])
        return res
