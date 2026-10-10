"""One City, One Journey - multimodal router for Ahmedabad Metro + Janmarg BRTS + AMTS.

Pure standard library, fully offline. Connection Scan Algorithm (CSA) over the
combined GTFS (community AMTS/BRTS feed + our generated GMRC metro feed).
"""
import csv, math, os, pickle, bisect, collections

HOME = os.path.expanduser('~')
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
BUS = os.path.join(DATA, 'gtfs_bus')
METRO = os.path.join(DATA, 'gtfs_metro')
AMTS_FARES = os.path.join(DATA, 'amts_fare_slabs.csv')
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache.pkl')
TOMTOM = os.path.join(DATA, 'tomtom_2025_ahmedabad_10km_travel_time_by_hour_weekday.csv')
BRTS_MIXED_SHARE = 0.25   # WCTR 2019 GPS study: mixed-traffic stretches ~25% of Janmarg travel time


def load_congestion():
    """Hourly congestion factor = TomTom 10 km travel time / the free-flow (minimum) time. 2025, Ahmedabad."""
    rows = list(csv.DictReader(open(TOMTOM)))
    cols = {'wkdy': 'Wed_min', 'sat': 'Sat_min', 'sun': 'Sun_min'}
    out = {}
    for day, c in cols.items():
        vals = {int(r['hour'][:2]): float(r[c]) for r in rows}
        base = min(vals.values())
        out[day] = {h: v / base for h, v in vals.items()}
    return out


CONGESTION = load_congestion()


def delay_factor(mode, t, day):
    f = CONGESTION.get(day, CONGESTION['wkdy']).get((t // 3600) % 24, 1.0)
    if mode == 'AMTS':
        return f
    if mode == 'BRTS':
        return (1 - BRTS_MIXED_SHARE) + BRTS_MIXED_SHARE * f
    return 1.0

WALK_MPS = 1.2          # walking speed
DETOUR = 1.3            # straight line -> street distance
BUS_DETOUR = 1.25       # straight line between stops -> road distance (AMTS fare)
MAX_TRANSFER_M = 400    # stop-to-stop transfer walk radius (straight line)
MAX_ACCESS_M = 1200     # origin/destination walk radius
CHANGE_S = 180          # min time to change vehicles at the same stop
TRANSFER_PEN = 240      # extra 'dislike' seconds per transfer walk (generalised cost)
MIN_RIDE_M = 1000       # don't alight after a pointless hop shorter than this
INTEGRATION_DISCOUNT = 0.10   # proposed discount on an integrated ticket
CLEARING_FEE = 0.01           # PPP clearing-house fee on integrated tickets


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def walk_s(m):
    return int(m * DETOUR / WALK_MPS)


def tsec(t):
    h, m, s = t.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def rows(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        yield from csv.DictReader(f)


def mode_of(route_id, agency):
    if route_id.startswith('GMRC'):
        return 'METRO'
    if route_id.startswith('BRTS_') or agency == 'AJL':
        return 'BRTS'
    return 'AMTS'


def fix_bad_coords(stops, st, trips, max_kmh=45.0, rounds=3):
    """Community GTFS has some mis-geocoded stops (e.g. a stop 3+ km from its neighbours but
    3 min away by bus). Flag stops whose adjacent hops imply impossible bus speeds and move
    them to the median midpoint of their neighbours across all trips."""
    fixed = {}
    for _ in range(rounds):
        bad_votes, votes, mids = collections.Counter(), collections.Counter(), collections.defaultdict(list)
        for tid, seq in st.items():
            if not trips.get(tid) or trips[tid][0].startswith('GMRC'):
                continue
            seq = sorted(seq)
            for i in range(1, len(seq) - 1):
                p, c, n = seq[i - 1], seq[i], seq[i + 1]
                if not all(x[1] in stops for x in (p, c, n)):
                    continue
                P, C, N = stops[p[1]], stops[c[1]], stops[n[1]]
                d1, d2 = hav(P[1], P[2], C[1], C[2]), hav(C[1], C[2], N[1], N[2])
                t1, t2 = max(c[2] - p[3], 60), max(n[2] - c[3], 60)
                votes[c[1]] += 1
                if d1 / t1 * 3.6 > max_kmh and d2 / t2 * 3.6 > max_kmh and d1 > 800 and d2 > 800:
                    bad_votes[c[1]] += 1
                mids[c[1]].append(((P[1] + N[1]) / 2, (P[2] + N[2]) / 2))
        changed = 0
        for sid, b in bad_votes.items():
            if b >= max(1, votes[sid] * 0.5) and mids[sid]:
                la = sorted(m[0] for m in mids[sid])[len(mids[sid]) // 2]
                lo = sorted(m[1] for m in mids[sid])[len(mids[sid]) // 2]
                if sid not in fixed:
                    fixed[sid] = (stops[sid][1], stops[sid][2])
                stops[sid] = (stops[sid][0], la, lo)
                changed += 1
        if not changed:
            break
    print('fixed %d mis-located stops' % len(fixed))
    return fixed


def build():
    stops, routes, trips = {}, {}, {}
    for d in (BUS, METRO):
        for r in rows(os.path.join(d, 'stops.txt')):
            stops[r['stop_id']] = (r['stop_name'], float(r['stop_lat']), float(r['stop_lon']))
        for r in rows(os.path.join(d, 'routes.txt')):
            routes[r['route_id']] = dict(mode=mode_of(r['route_id'], r.get('agency_id', '')),
                                         short=r['route_short_name'], long=r['route_long_name'],
                                         color=r.get('route_color') or '')
        for r in rows(os.path.join(d, 'trips.txt')):
            trips[r['trip_id']] = (r['route_id'], r['service_id'], r.get('trip_headsign', ''))

    # stop_times -> per-trip ordered list
    st = collections.defaultdict(list)
    for d in (BUS, METRO):
        for r in rows(os.path.join(d, 'stop_times.txt')):
            st[r['trip_id']].append((int(r['stop_sequence']), r['stop_id'],
                                     tsec(r['arrival_time']), tsec(r['departure_time'])))


    conns = []  # (dep, arr, from, to, trip, cumdist_from, cumdist_to)
    for tid, seq in st.items():
        if tid not in trips:
            continue
        seq.sort()
        cum = 0.0
        for a, b in zip(seq, seq[1:]):
            if a[1] not in stops or b[1] not in stops:
                continue
            sa, sb = stops[a[1]], stops[b[1]]
            d = hav(sa[1], sa[2], sb[1], sb[2])
            # community GTFS has some mis-geocoded / merged stops: a 'hop' that would need
            # > 50 km/h on a city bus is a data error -> mark it so nobody rides across it
            bad = (not tid.startswith('GMRC')) and d > 1000 and d / max(b[2] - a[3], 60) * 3.6 > 50
            conns.append((a[3], b[2], a[1], b[1], tid, cum, cum + d, bad))
            cum += d
    conns.sort()

    # transfer footpaths via a coarse grid
    grid = collections.defaultdict(list)
    for sid, (_, la, lo) in stops.items():
        grid[(int(la * 200), int(lo * 200))].append(sid)
    foot = collections.defaultdict(list)
    for sid, (_, la, lo) in stops.items():
        gx, gy = int(la * 200), int(lo * 200)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for o in grid[(gx + dx, gy + dy)]:
                    if o == sid:
                        continue
                    m = hav(la, lo, stops[o][1], stops[o][2])
                    if m <= MAX_TRANSFER_M:
                        foot[sid].append((o, walk_s(m), int(m * DETOUR)))

    # fares
    def fare_tables(d, cat_prefix):
        area = {}
        for r in rows(os.path.join(d, 'stop_areas.txt')):
            area.setdefault(r['stop_id'], r['area_id'])
        prod = {r['fare_product_id']: float(r['amount']) for r in rows(os.path.join(d, 'fare_products.txt'))}
        od = {}
        for r in rows(os.path.join(d, 'fare_leg_rules.txt')):
            if cat_prefix in r['fare_product_id']:
                od[(r['from_area_id'], r['to_area_id'])] = prod[r['fare_product_id']]
        return area, od

    brts_area, brts_od = fare_tables(BUS, 'ADULT')
    metro_area, metro_od = fare_tables(METRO, 'ADULT')
    amts_slabs = []
    for r in rows(AMTS_FARES):
        if r['rider_category'] == 'adult':
            amts_slabs.append((float(r['max_km']) if r['max_km'] else 1e9, float(r['fare_inr'])))
    amts_slabs.sort()

    return dict(stops=stops, routes=routes, trips=trips, conns=conns, foot=dict(foot),
                brts_area=brts_area, brts_od=brts_od, metro_area=metro_area, metro_od=metro_od,
                amts_slabs=amts_slabs)


def load():
    if os.path.exists(CACHE):
        with open(CACHE, 'rb') as f:
            return pickle.load(f)
    data = build()
    with open(CACHE, 'wb') as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    return data


class Router:
    def __init__(self):
        self.d = load()
        self.deps = [c[0] for c in self.d['conns']]
        g = collections.defaultdict(list)
        for sid, (_, la, lo) in self.d['stops'].items():
            g[(int(la * 50), int(lo * 50))].append(sid)
        self.grid = g

    def near(self, lat, lon, radius=MAX_ACCESS_M):
        out = []
        gx, gy = int(lat * 50), int(lon * 50)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for s in self.grid[(gx + dx, gy + dy)]:
                    _, la, lo = self.d['stops'][s]
                    m = hav(lat, lon, la, lo)
                    if m <= radius:
                        out.append((s, walk_s(m), int(m * DETOUR)))
        return out

    def service_ok(self, service_id, day):
        if service_id.startswith('GMRC_'):
            return service_id == 'GMRC_DAILY' or service_id == {'wkdy': 'GMRC_WKDY', 'sat': 'GMRC_SAT', 'sun': 'GMRC_SUN'}[day]
        return True  # bus feed runs all days

    def csa(self, o, dst, t0, modes, day='wkdy', horizon=4 * 3600, state=False):
        """Earliest-arrival CSA. Returns list of legs or None."""
        D = self.d
        INF = 1 << 40
        ready = collections.defaultdict(lambda: INF)   # time you can board at stop
        how = {}                                         # stop -> ('access',m) | ('walk',from,dur,m) | ('ride',trip,board_conn,alight_conn)
        for s, w, m in self.near(*o):
            if t0 + w < ready[s]:
                ready[s] = t0 + w
                how[s] = ('access', w, m)
        egress = {s: (w, m) for s, w, m in self.near(*dst)} if dst else {}
        best_arr, best_stop = INF, None
        # direct walk
        direct = hav(o[0], o[1], dst[0], dst[1]) if dst else 1e9
        if direct <= 2500:
            best_arr = t0 + walk_s(direct)
        boarded = {}
        trips, routes, conns = D['trips'], D['routes'], D['conns']
        i = bisect.bisect_left(self.deps, t0)
        end = t0 + horizon
        while i < len(conns):
            c = conns[i]
            i += 1
            dep, arr, fs, ts, tid = c[0], c[1], c[2], c[3], c[4]
            if dep > end or dep >= best_arr:
                break
            if c[7]:
                boarded.pop(tid, None)   # trip is broken at a bad hop: must re-board after it
                continue
            if tid not in boarded:
                rid, sid, _ = trips[tid]
                if routes[rid]['mode'] not in modes or not self.service_ok(sid, day):
                    continue
                if ready[fs] > dep:
                    continue
                boarded[tid] = c
            # alight at ts? (skip pointless short hops)
            if c[6] - boarded[tid][5] < MIN_RIDE_M:
                continue
            if arr + CHANGE_S < ready[ts]:
                ready[ts] = arr + CHANGE_S
                how[ts] = ('ride', tid, boarded[tid], c)
                for nb, w, m in D['foot'].get(ts, ()):
                    if arr + w + TRANSFER_PEN < ready[nb]:
                        ready[nb] = arr + w + TRANSFER_PEN
                        how[nb] = ('walk', ts, w, m, arr)
                if ts in egress and arr + egress[ts][0] < best_arr:
                    best_arr, best_stop = arr + egress[ts][0], ts
        if state:
            return ready, how
        if best_stop is None:
            if best_arr < INF:
                return [dict(kind='walk', dur=walk_s(direct), m=int(direct * DETOUR),
                             frm='Start', to='Destination', dep=t0, arr=best_arr,
                             path=[[o[0], o[1]], [dst[0], dst[1]]])]
            return None
        # reconstruct
        legs = []
        st = D['stops']
        w, m = egress[best_stop]
        legs.append(dict(kind='walk', dur=w, m=m, frm=st[best_stop][0], to='Destination',
                         path=[[st[best_stop][1], st[best_stop][2]], [dst[0], dst[1]]]))
        s = best_stop
        guard = 0
        while guard < 50:
            guard += 1
            h = how[s]
            if h[0] == 'access':
                legs.append(dict(kind='walk', dur=h[1], m=h[2], frm='Start', to=st[s][0],
                                 path=[[o[0], o[1]], [st[s][1], st[s][2]]]))
                break
            if h[0] == 'walk':
                f = h[1]
                legs.append(dict(kind='walk', dur=h[2], m=h[3], frm=st[f][0], to=st[s][0],
                                 path=[[st[f][1], st[f][2]], [st[s][1], st[s][2]]]))
                s = f
                continue
            _, tid, bc, ac = h
            rid = trips[tid][0]
            r = routes[rid]
            legs.append(dict(kind='ride', mode=r['mode'], route=r['short'], route_long=r['long'],
                             color=r['color'], headsign=trips[tid][2], trip=tid,
                             frm=st[bc[2]][0], to=st[ac[3]][0], from_id=bc[2], to_id=ac[3],
                             dep=bc[0], arr=ac[1], km=(ac[6] - bc[5]) / 1000.0,
                             path=self.trip_path(tid, bc[2], ac[3])))
            s = bc[2]
        legs.reverse()
        # stamp times on walk legs
        t = t0
        for L in legs:
            if L['kind'] == 'walk':
                L['dep'], L['arr'] = t, t + L['dur']
                t = L['arr']
            else:
                t = L['arr']
        return legs

    def trip_path(self, tid, a, b):
        D = self.d
        pts, on = [], False
        for c in self._trip_conns(tid):
            if c[2] == a:
                on = True
            if on:
                if not pts:
                    pts.append([D['stops'][c[2]][1], D['stops'][c[2]][2]])
                pts.append([D['stops'][c[3]][1], D['stops'][c[3]][2]])
            if on and c[3] == b:
                break
        return pts

    def _trip_conns(self, tid):
        if not hasattr(self, '_tc'):
            tc = collections.defaultdict(list)
            for c in self.d['conns']:
                tc[c[4]].append(c)
            self._tc = tc
        return self._tc[tid]

    # ---------- fares ----------
    def leg_fare(self, L):
        D = self.d
        if L['mode'] == 'METRO':
            a, b = D['metro_area'].get(L['from_id']), D['metro_area'].get(L['to_id'])
            f = D['metro_od'].get((a, b)) or D['metro_od'].get((b, a))
            return f if f is not None else 0.0, 'GMRC official fare matrix'
        if L['mode'] == 'BRTS':
            a, b = D['brts_area'].get(L['from_id']), D['brts_area'].get(L['to_id'])
            f = D['brts_od'].get((a, b)) or D['brts_od'].get((b, a))
            if f is not None:
                return f, 'AJL fare table (GTFS)'
        km = L['km'] * BUS_DETOUR
        for mx, f in D['amts_slabs']:
            if km <= mx:
                return f, 'AMTS slab, %.1f km est. (news, Jun 2023)' % km
        return D['amts_slabs'][-1][1], 'AMTS slab'

    def price(self, legs):
        rides = [L for L in legs if L['kind'] == 'ride']
        # GMRC joins consecutive metro legs into one fare (fare_leg_join_rules)
        merged = []
        for L in rides:
            if merged and L['mode'] == 'METRO' and merged[-1]['mode'] == 'METRO':
                merged[-1] = dict(merged[-1], to_id=L['to_id'], to=L['to'], km=merged[-1]['km'] + L['km'],
                                  joined=True)
            else:
                merged.append(dict(L))
        tickets = []
        for L in merged:
            f, src = self.leg_fare(L)
            tickets.append(dict(mode=L['mode'], frm=L['frm'], to=L['to'], km=round(L['km'], 1),
                                fare=f, src=src))
        total = sum(t['fare'] for t in tickets)
        ops = {t['mode'] for t in tickets}
        split = None
        if len(ops) > 1:
            # Proposal: integrated ticket = sum of operator fares - 10%, rounded to Rs 1.
            # Discount shared in proportion to passenger-km; clearing house keeps 1%.
            integ = round(total * (1 - INTEGRATION_DISCOUNT))
            pkm = collections.Counter()
            own = collections.Counter()
            for t in tickets:
                pkm[t['mode']] += max(t['km'], 0.5)
                own[t['mode']] += t['fare']
            disc = total - integ
            tot_km = sum(pkm.values())
            fee = round(integ * CLEARING_FEE, 2)
            shares = []
            for op in ('METRO', 'BRTS', 'AMTS'):
                if op in own:
                    gross = own[op] - disc * pkm[op] / tot_km
                    net = gross - fee * (gross / integ)
                    shares.append(dict(op=op, own_fare=own[op], km=round(pkm[op], 1),
                                       discount_borne=round(disc * pkm[op] / tot_km, 2),
                                       net=round(net, 2)))
            split = dict(integrated=integ, separate=total, saving=disc, clearing_fee=fee, shares=shares)
        return dict(tickets=tickets, total=total, split=split)

    def legs_to(self, s, o, how):
        st, trips, routes = self.d['stops'], self.d['trips'], self.d['routes']
        legs = []
        for _ in range(50):
            h = how[s]
            if h[0] == 'access':
                break
            if h[0] == 'walk':
                s = h[1]
                continue
            _, tid, bc, ac = h
            legs.append(dict(kind='ride', mode=routes[trips[tid][0]]['mode'], frm=st[bc[2]][0], to=st[ac[3]][0],
                             from_id=bc[2], to_id=ac[3], km=(ac[6] - bc[5]) / 1000.0))
            s = bc[2]
        legs.reverse()
        return legs

    def heat(self, o, t0, modes, day='wkdy', horizon=2 * 3600):
        """Travel time (min) and fare (Rs, integrated ticket) from o to every reachable stop."""
        ready, how = self.csa(o, None, t0, modes, day, horizon, state=True)
        out = []
        st = self.d['stops']
        for s, h in how.items():
            t = ready[s] - (CHANGE_S if h[0] == 'ride' else 0) - (TRANSFER_PEN if h[0] == 'walk' else 0)
            mins = (t - t0) / 60
            if mins > horizon / 60:
                continue
            legs = self.legs_to(s, o, how)
            if not legs:
                fare = 0
            else:
                p = self.price(legs)
                fare = p['split']['integrated'] if p['split'] else p['total']
            out.append([round(st[s][1], 5), round(st[s][2], 5), round(mins, 1), fare])
        return out

    def delayed_arrival(self, legs, t, day):
        for L in legs:
            if L['kind'] == 'walk':
                t += L['dur']
            else:
                dur = L['arr'] - L['dep']
                t = max(t, L['dep']) + int(dur * delay_factor(L['mode'], L['dep'], day))
        return t

    def simulate(self, opt, dst, day):
        """Propagate expected rush-hour delays through an itinerary. If a connection is likely missed,
        re-plan from that stop at the late arrival time (the rider's plan B)."""
        legs, t, late_legs = opt['legs'], opt['dep'], []
        for k, L in enumerate(legs):
            if L['kind'] == 'walk':
                t += L['dur']
                continue
            if t > L['dep'] + 60:        # reached the stop after the vehicle left (1 min grace)
                p = L['path'][0]
                fb = self.csa((p[0], p[1]), dst, t, opt.get('modeset') or {'METRO', 'BRTS', 'AMTS'}, day)
                res = dict(missed=dict(at=L['frm'], mode=L['mode'], route=L['route'], sched=L['dep'], reach=t, leg=k))
                if fb:
                    arr = self.delayed_arrival(fb, t, day)   # plan B suffers the same traffic
                    rides = [x for x in fb if x['kind'] == 'ride']
                    res['fallback'] = dict(legs=fb, arr=arr, mins=round((arr - opt['dep']) / 60),
                                           transfers=max(len(rides) - 1, 0), modes=sorted({x['mode'] for x in rides}),
                                           fare=self.price(legs[:k] + fb))
                    res['arr'] = arr
                else:
                    res['arr'] = None
                res['late_legs'] = late_legs
                return res
            dur = L['arr'] - L['dep']
            f = delay_factor(L['mode'], L['dep'], day)
            extra = int(dur * (f - 1))
            if extra >= 60:
                late_legs.append(dict(mode=L['mode'], route=L['route'], extra_min=round(extra / 60), factor=round(f, 2)))
            t = max(t, L['dep']) + dur + extra
        return dict(arr=t, late_legs=late_legs, missed=None)

    def plan(self, o, dst, t0, day='wkdy'):
        options = []
        seen = set()
        for label, modes in (('Fastest (any mode)', {'METRO', 'BRTS', 'AMTS'}),
                             ('Metro + BRTS only', {'METRO', 'BRTS'}),
                             ('Bus only (no metro)', {'BRTS', 'AMTS'}),
                             ('Metro + AMTS feeder', {'METRO', 'AMTS'})):
            legs = self.csa(o, dst, t0, modes, day)
            if not legs:
                continue
            if 'Metro' in label and not any(L.get('mode') == 'METRO' for L in legs):
                continue
            key = tuple((L.get('trip'), L.get('frm')) for L in legs if L['kind'] == 'ride')
            if key in seen:
                continue
            seen.add(key)
            rides = [L for L in legs if L['kind'] == 'ride']
            walks = [L for L in legs if L['kind'] == 'walk']
            arr = legs[-1]['arr']
            options.append(dict(label=label, modeset=modes, legs=legs, dep=t0, arr=arr, mins=round((arr - t0) / 60),
                                transfers=max(len(rides) - 1, 0),
                                walk_m=sum(L['m'] for L in walks),
                                walk_min=round(sum(L['dur'] for L in walks) / 60),
                                modes=sorted({L['mode'] for L in rides}),
                                fare=self.price(legs)))
        options.sort(key=lambda x: x['arr'])
        for op in options:
            sim = self.simulate(op, dst, day)
            exp = sim['arr']
            sim['mins'] = round((exp - t0) / 60) if exp else None
            sim['late_min'] = round((exp - op['arr']) / 60) if exp else None
            op['expected'] = sim
            op['modeset'] = sorted(op['modeset'])
        return options


if __name__ == '__main__':
    import sys, time
    t = time.time()
    R = Router()
    print('loaded in %.1fs, %d connections, %d stops' % (time.time() - t, len(R.d['conns']), len(R.d['stops'])))
    t = time.time()
    res = R.plan((23.05014, 72.51156), (22.99855, 72.61112), 9 * 3600)   # Thaltej Gam -> Maninagar
    print('planned in %.2fs' % (time.time() - t))
    for op in res:
        print('\n==', op['label'], op['mins'], 'min, transfers', op['transfers'], 'walk', op['walk_min'], 'min, fare Rs', op['fare']['total'])
        for L in op['legs']:
            if L['kind'] == 'walk':
                print('   walk %dm (%d min) %s -> %s' % (L['m'], L['dur'] // 60, L['frm'], L['to']))
            else:
                print('   %s %s %s -> %s  %.1f km' % (L['mode'], L['route'], L['frm'], L['to'], L['km']))
        if op['fare']['split']:
            print('   split:', op['fare']['split'])
