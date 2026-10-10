"""Stdlib validation of gtfs_metro.zip: referential integrity, monotonic stop_times, OD spot checks."""
import csv, io, zipfile, os, collections, sys
Z = zipfile.ZipFile(os.path.expanduser('~/metro-hacks-ps08/gtfs_metro.zip'))
def t(n): return list(csv.DictReader(io.TextIOWrapper(Z.open(n), 'utf-8')))
def s(x): h, m, ss = map(int, x.split(':')); return h * 3600 + m * 60 + ss
err = []
def chk(c, msg):
    if not c: err.append(msg)
F = {n[:-4]: t(n) for n in Z.namelist()}
for need in ['agency', 'stops', 'routes', 'trips', 'stop_times', 'calendar']: chk(need in F, 'missing ' + need)
stops = {r['stop_id'] for r in F['stops']}; routes = {r['route_id'] for r in F['routes']}
svcs = {r['service_id'] for r in F['calendar']}; trips = {r['trip_id']: r for r in F['trips']}
agencies = {r['agency_id'] for r in F['agency']}
for k, f in [('stop_id', 'stops'), ('route_id', 'routes'), ('trip_id', 'trips'), ('service_id', 'calendar')]:
    ids = [r[k] for r in F[f]]; chk(len(ids) == len(set(ids)), 'dup ' + k)
chk(all(r['stop_id'].startswith('GMRC_') for r in F['stops']), 'stop prefix')
for r in F['stops']: chk(22.9 < float(r['stop_lat']) < 23.3 and 72.4 < float(r['stop_lon']) < 72.8, 'coord ' + r['stop_id'])
for r in F['routes']: chk(r['agency_id'] in agencies and r['route_type'] == '1', 'route ' + r['route_id'])
for r in F['trips']: chk(r['route_id'] in routes and r['service_id'] in svcs, 'trip ' + r['trip_id'])
by = collections.defaultdict(list)
for r in F['stop_times']:
    chk(r['trip_id'] in trips and r['stop_id'] in stops, 'st ref ' + r['trip_id']); by[r['trip_id']].append(r)
chk(set(by) == set(trips), 'trips without stop_times')
for tid, rows in by.items():
    rows.sort(key=lambda r: int(r['stop_sequence'])); prev = -1
    for r in rows:
        a, d = s(r['arrival_time']), s(r['departure_time'])
        chk(a >= prev and d >= a, 'non-monotonic ' + tid); prev = d
    chk(len({r['stop_id'] for r in rows}) == len(rows), 'loop ' + tid)
# blocks: stay-seated chain must continue at same stop, later time, same service
blk = collections.defaultdict(list)
for tid, r in trips.items():
    if r['block_id']: blk[r['block_id']].append(tid)
for b, ts in blk.items():
    ts.sort(key=lambda x: s(by[x][0]['departure_time']))
    for x, y in zip(ts, ts[1:]):
        chk(by[x][-1]['stop_id'] == by[y][0]['stop_id'] and s(by[y][0]['departure_time']) >= s(by[x][-1]['arrival_time'])
            and trips[x]['service_id'] == trips[y]['service_id'], 'block ' + b)
# fares
areas = {r['area_id'] for r in F['areas']}; prods = {r['fare_product_id']: r for r in F['fare_products']}
sa = {r['stop_id']: r['area_id'] for r in F['stop_areas']}
chk(set(sa) == stops and set(sa.values()) <= areas, 'stop_areas')
fl = {}
for r in F['fare_leg_rules']:
    chk(r['from_area_id'] in areas and r['to_area_id'] in areas and r['fare_product_id'] in prods, 'fare rule ref')
    fl[(r['from_area_id'], r['to_area_id'])] = int(prods[r['fare_product_id']]['amount'])
chk(len(fl) == 53 * 52, 'fare rule count %d' % len(fl))
# no id collision with bus feed
bus = zipfile.ZipFile(os.path.expanduser('~/metro-hacks-data/01_transit/gtfs_secondary/gtfs.zip'))
for f, k in [('stops', 'stop_id'), ('routes', 'route_id'), ('trips', 'trip_id'), ('areas', 'area_id'), ('fare_products', 'fare_product_id'), ('agency', 'agency_id'), ('calendar', 'service_id')]:
    if f + '.txt' in bus.namelist():
        b = {r[k] for r in csv.DictReader(io.TextIOWrapper(bus.open(f + '.txt'), 'utf-8'))}
        chk(not (b & {r[k] for r in F[f]}), 'collision ' + f)
cal_bus = list(csv.DictReader(io.TextIOWrapper(bus.open('calendar.txt'), 'utf-8')))
chk(all((r['start_date'], r['end_date']) == (cal_bus[0]['start_date'], cal_bus[0]['end_date']) for r in F['calendar']), 'calendar range')
# OD spot checks vs official matrix
OD = {}
for r in csv.DictReader(open(os.path.expanduser('~/metro-hacks-data/01_transit/metro/fares_stations/gmrc_fare_od_matrix_official_api.csv'))):
    OD[(r['from_id'], r['to_id'])] = r
name = {r['stop_id']: r['stop_name'] for r in F['stops']}
chains = dict(by)  # also stay-seated block chains
for b_, ts in blk.items(): chains[b_] = [r for x in ts for r in (by[x] if x == ts[0] else by[x][1:])]
def ride(a, b):  # min in-vehicle time over single trips / stay-seated chains serving a then b
    best = None
    for tid, rows in chains.items():
        ids = [r['stop_id'] for r in rows]
        if a in ids and b in ids and ids.index(a) < ids.index(b):
            m = (s(rows[ids.index(b)]['arrival_time']) - s(rows[ids.index(a)]['departure_time'])) / 60
            best = m if best is None else min(best, m)
    return best
print('OD spot checks (generated min ride / official minutes; fare rule / official fare):')
for a, b in [(1, 18), (19, 33), (33, 52), (40, 54), (7, 14), (19, 52)]:
    o = OD[(str(a), str(b))]; g = ride('GMRC_%d' % a, 'GMRC_%d' % b)
    f = fl[('GMRC_AREA_%d' % a, 'GMRC_AREA_%d' % b)]
    ok = g is not None and abs(g - int(o['travel_time_min'])) <= 2 and f == int(o['fare_inr_token'])
    print(f"  {name['GMRC_%d'%a]:>16} -> {name['GMRC_%d'%b]:<16} ride {g} vs {int(o['travel_time_min'])}  fare {f} vs {o['fare_inr_token']}  {'OK' if ok else 'MISMATCH'}")
    chk(ok, 'OD %s-%s' % (a, b))
# Line 4 gap
l4 = [s(by[x][0]['departure_time']) for x, r in trips.items() if r['route_id'] == 'GMRC_L4' for y in [0] if by[x][0]['stop_id'] in ('GMRC_40', 'GMRC_54')]
gnlu = sorted(s(by[x][-1 if r['direction_id']=='0' else 0]['departure_time']) for x, r in trips.items() if r['route_id'] == 'GMRC_L4')  # GIFT terminus times
gnlu = sorted(s(rw['departure_time']) for x, r in trips.items() if r['route_id'] == 'GMRC_L4' for rw in by[x] if rw['stop_id'] == ('GMRC_40' if r['direction_id']=='0' else 'GMRC_54'))
chk(not any(sec_ > 10 * 3600 + 18 * 60 and sec_ < 16 * 3600 + 6 * 60 for sec_ in gnlu), 'L4 gap violated')
print('L4 departures (GNLU up / GIFT down):', [f'{x//3600:02d}:{x%3600//60:02d}' for x in gnlu])
print('counts:', {k: len(v) for k, v in F.items()})
print('ERRORS:', len(err), sorted(set(err))[:20]); sys.exit(1 if err else 0)
