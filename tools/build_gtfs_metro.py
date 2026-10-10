"""Build GTFS for Ahmedabad-Gandhinagar Metro (GMRC). Stdlib only.
Inputs read-only from ~/metro-hacks-data/01_transit. Output ~/metro-hacks-ps08/gtfs_metro{/,.zip}."""
import csv, os, zipfile, collections
R = os.path.expanduser('~/metro-hacks-data/01_transit')
OUT = os.path.expanduser('~/metro-hacks-ps08/gtfs_metro')
ZIP = OUT + '.zip'
os.makedirs(OUT, exist_ok=True)
def rd(p): return list(csv.DictReader(open(os.path.join(R, p), encoding='utf-8-sig')))
def wr(name, hdr, rows):
    with open(os.path.join(OUT, name), 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n'); w.writerow(hdr); w.writerows(rows)
def hms(s): return '%02d:%02d:%02d' % (s // 3600, s % 3600 // 60, s % 60)
def sec(t): h, m = t.split(':')[:2]; return int(h) * 3600 + int(m) * 60

# ---------- stations ----------
gm = rd('metro/fares_stations/gmrc_station_list_official_site.csv')
op = {int(g['gmrc_station_id']): g['station_name'] for g in gm if g['status_on_gmrc_site'] == 'operational'}
assert len(op) == 53
scr = [x for x in rd('secondary_scraped/stops.csv') if x['agency'] == 'metro']
# scraped id suffix = GMRC id - 1. Scraped list contains WIP #29 (labelled 'Sabarmati Railway Station')
# and lacks #31 Sabarmati. ASSUMPTION: by OD-matrix distances (Ranip-AEC 2.27 km, AEC-Sabarmati 1.29,
# Sabarmati-Motera 1.39) the scraped 'Sabarmati Railway Station' point (23.0856,72.5922) is in fact Sabarmati (#31).
coord = {}
for s in scr:
    gid = int(s['stop_id'].rsplit('-', 1)[1]) + 1
    if gid == 29: gid = 31
    coord[gid] = (float(s['lat']), float(s['lon']), s['interchange_group_id'])
assert set(coord) == set(op), set(op) ^ set(coord)
name2id = {v: k for k, v in op.items()}
SID = lambda i: 'GMRC_%d' % i

# ---------- OD matrix ----------
OD = {}
for r in rd('metro/fares_stations/gmrc_fare_od_matrix_official_api.csv'):
    a, b = int(r['from_id']), int(r['to_id'])
    v = dict(fare=int(r['fare_inr_token']), km=float(r['distance_km']), t=int(r['travel_time_min']), ix=r['interchange'])
    OD[(a, b)] = OD[(b, a)] = v
assert len(OD) == 53 * 52

# ---------- lines (station order verified by OD distance from first terminus) ----------
L1 = list(range(1, 19))
L2 = [19, 20, 21, 22, 23, 24, 11, 25, 26, 27, 28, 30, 31, 32, 33]
L3 = list(range(33, 53))
L4 = [40, 53, 54]
for seq in (L1, L2, L3, L4):
    d = [0] + [OD[(seq[0], s)]['km'] for s in seq[1:]]
    assert d == sorted(d), seq
    assert all(OD[(seq[0], s)]['ix'] == '0' for s in seq[1:])
def cum(seq):  # cumulative minutes from seq[0], straight from the official matrix
    return [0] + [OD[(seq[0], s)]['t'] for s in seq[1:]]

ROUTES = {  # colours: GMRC map / Wikipedia line colours (Blue, Red, Yellow?, Violet) -- see report
    'GMRC_L1': ('Line 1', 'Blue Line: Vastral Gam - Thaltej Gam', '0B5ED7', 'FFFFFF'),
    'GMRC_L2': ('Line 2', 'Red Line: APMC - Koteshwar Road', 'E31E24', 'FFFFFF'),
    'GMRC_L3': ('Line 3', 'Yellow Line: Koteshwar Road - Mahatma Mandir', 'F5C400', '000000'),
    'GMRC_L4': ('Line 4', 'Violet Line: GNLU - GIFT City', '7B3FA0', 'FFFFFF'),
}

# ---------- services ----------
CAL = [('GMRC_WKDY', 1, 1, 1, 1, 1, 0, 0), ('GMRC_SAT', 0, 0, 0, 0, 0, 1, 0), ('GMRC_SUN', 0, 0, 0, 0, 0, 0, 1),
       ('GMRC_DAILY', 1, 1, 1, 1, 1, 1, 1)]
START, END = '20260930', '20270329'  # match bus feed calendar

trips, st, n = [], [], collections.Counter()
def add_trip(route, svc, seq, times, headsign, direction, block=''):
    """times: arrival seconds per stop; departure = arrival + 30 s dwell (not at last stop; first stop dep = given time)."""
    n[route] += 1
    tid = '%s_%s_%s_%03d' % (route, svc.split('_')[1], 'U' if direction == 0 else 'D', n[(route, svc, direction)] + 1)
    n[(route, svc, direction)] += 1
    trips.append([route, svc, tid, headsign, direction, block])
    for k, (s, t) in enumerate(zip(seq, times)):
        if k == 0: arr = dep = t
        elif k == len(seq) - 1: arr = dep = t
        else: arr, dep = t, t + 30
        st.append([tid, hms(arr), hms(dep), SID(s), k + 1, 1 if k in (0, len(seq) - 1) else 0])
    return tid

def run(seq, t0):
    c = cum(seq); return [t0 + 60 * x for x in c]

# Line 1 headways (w.e.f. 18-05-2026 sheet)
def l1_headway(t, day):
    m = t / 60
    if m < 7 * 60 or m >= 22 * 60: return 20
    peak = (8 * 60 <= m < 11 * 60) or (17 * 60 <= m < 20 * 60)
    if day == 'WKDY': return 7 if peak else 10
    if day == 'SAT': return 10 if peak else 12
    return 12
for day in ('WKDY', 'SAT', 'SUN'):
    for direction, seq in ((0, L1[::-1]), (1, L1)):  # 0: Thaltej Gam -> Vastral Gam, 1: reverse
        t = sec('06:20')
        while t <= sec('23:00'):
            add_trip('GMRC_L1', 'GMRC_' + day, seq, run(seq, t), op[seq[-1]], direction)
            t += l1_headway(t, day) * 60

# Phase-2 through trains from the tidy timetable
TT = collections.defaultdict(dict)
for r in rd('metro/timetable/gmrc_timetable_phase2_wef_2026-05-18_tidy.csv'):
    nm = {'Mahatma Mandir': 'Mahatama Mandir', 'GIFT City': 'Gift City'}.get(r['station'], r['station'])
    TT[(int(r['service_sl_no']), r['direction'])][name2id[nm]] = sec(r['time'])
def interp(seq, timed):
    """Times at every station of seq: timed points kept exactly, intermediates by OD-matrix minutes, scaled."""
    c = [OD[(seq[0], s)]['t'] if s != seq[0] else 0 for s in seq]
    idx = [k for k, s in enumerate(seq) if s in timed]
    assert idx[0] == 0 and idx[-1] == len(seq) - 1, (seq, timed)
    out = [None] * len(seq)
    for a, b in zip(idx, idx[1:]):
        ta, tb = timed[seq[a]], timed[seq[b]]
        for k in range(a, b + 1):
            f = (c[k] - c[a]) / (c[b] - c[a]) if c[b] != c[a] else 0
            out[k] = round((ta + f * (tb - ta)) / 30) * 30
    return out
through_up, through_dn = [], []
for (svc, d), timed in sorted(TT.items()):
    gift = 54 in timed
    if d.startswith('UP'):
        full = L2 + (L3[1:L3.index(40) + 1] + L4[1:] if gift else L3[1:])
    else:
        full = (L4[::-1] + L3[:L3.index(40)][::-1] if gift else L3[::-1]) + L2[::-1][1:]
    times = interp(full, timed)
    k = full.index(33)  # split at Koteshwar Road into Line 2 piece + Line 3/4 piece, chained by block_id
    blk = 'GMRC_P2_%s_%02d' % ('U' if d.startswith('UP') else 'D', svc)
    p3 = 'GMRC_L4' if gift else 'GMRC_L3'
    if d.startswith('UP'):
        add_trip('GMRC_L2', 'GMRC_DAILY', full[:k + 1], times[:k + 1], op[full[-1]].replace('Mahatama', 'Mahatma'), 0, blk)
        add_trip(p3, 'GMRC_DAILY', full[k:], times[k:], op[full[-1]].replace('Mahatama', 'Mahatma'), 0, blk)
        through_up.append(times[0])
    else:
        add_trip(p3, 'GMRC_DAILY', full[:k + 1], times[:k + 1], 'APMC', 1, blk)
        add_trip('GMRC_L2', 'GMRC_DAILY', full[k:], times[k:], 'APMC', 1, blk)
        through_dn.append(times[k])

# Line 2 shuttles APMC<->Koteshwar Road: 12 min to 22:00 then 20 min; slots within 6 min of a through train dropped
def l2_slots(first, last):
    t, out = first, []
    while t <= last:
        out.append(t); t += (12 if t < sec('22:00') else 20) * 60
    if out[-1] != last: out.append(last)
    return out
for direction, seq, first, last, thr in ((0, L2, '06:20', '23:10', through_up), (1, L2[::-1], '06:16', '23:00', through_dn)):
    for t in l2_slots(sec(first), sec(last)):
        if any(abs(t - x) < 6 * 60 for x in thr): continue
        add_trip('GMRC_L2', 'GMRC_DAILY', seq, run(seq, t), op[seq[-1]], direction)

# ---------- write ----------
wr('agency.txt', ['agency_id', 'agency_name', 'agency_url', 'agency_timezone', 'agency_lang', 'agency_phone', 'agency_fare_url'],
   [['GMRC', 'Gujarat Metro Rail Corporation (GMRC) Ltd', 'https://www.gujaratmetrorail.com', 'Asia/Kolkata', 'en', '',
     'https://www.gujaratmetrorail.com/ahmedabad/route-and-fares/']])
wr('feed_info.txt', ['feed_publisher_name', 'feed_publisher_url', 'feed_lang', 'feed_start_date', 'feed_end_date', 'feed_version'],
   [['metro-hacks PS-08 (unofficial, built from GMRC published data)', 'https://www.gujaratmetrorail.com', 'en', START, END, '2026-10-10']])
wr('stops.txt', ['stop_id', 'stop_code', 'stop_name', 'stop_lat', 'stop_lon', 'location_type', 'stop_desc'],
   [[SID(i), i, op[i], '%.6f' % coord[i][0], '%.6f' % coord[i][1], 0,
     ('interchange_group ' + coord[i][2]) if coord[i][2] else ''] for i in sorted(op)])
wr('routes.txt', ['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_type', 'route_color', 'route_text_color', 'network_id'],
   [[k, 'GMRC', *v[:2], 1, *v[2:], 'GMRC'] for k, v in ROUTES.items()])
wr('calendar.txt', ['service_id', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'start_date', 'end_date'],
   [[*c, START, END] for c in CAL])
wr('trips.txt', ['route_id', 'service_id', 'trip_id', 'trip_headsign', 'direction_id', 'block_id'], trips)
wr('stop_times.txt', ['trip_id', 'arrival_time', 'departure_time', 'stop_id', 'stop_sequence', 'timepoint'], st)
# Fares v2 (mirrors bus feed: one area per station, from/to area -> product). Token/QR single-journey fare.
amounts = sorted({v['fare'] for v in OD.values()})
wr('rider_categories.txt', ['rider_category_id', 'rider_category_name', 'is_default_fare_category'], [['GMRC_ADULT', 'Adult', 1]])
wr('fare_products.txt', ['fare_product_id', 'fare_product_name', 'rider_category_id', 'amount', 'currency'],
   [['GMRC_ADULT_%d' % a, 'GMRC Single Journey INR %d' % a, 'GMRC_ADULT', a, 'INR'] for a in amounts])
wr('areas.txt', ['area_id', 'area_name'], [['GMRC_AREA_%d' % i, op[i]] for i in sorted(op)])
wr('stop_areas.txt', ['area_id', 'stop_id'], [['GMRC_AREA_%d' % i, SID(i)] for i in sorted(op)])
wr('fare_leg_rules.txt', ['leg_group_id', 'network_id', 'from_area_id', 'to_area_id', 'fare_product_id'],
   [['GMRC_OD', 'GMRC', 'GMRC_AREA_%d' % a, 'GMRC_AREA_%d' % b, 'GMRC_ADULT_%d' % OD[(a, b)]['fare']]
    for a in sorted(op) for b in sorted(op) if a != b])
# Interchange (Old High Court / GNLU / Koteshwar stay-seated) is one gated journey: join consecutive GMRC legs.
wr('fare_leg_join_rules.txt', ['from_network_id', 'to_network_id'], [['GMRC', 'GMRC']])

with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir(OUT)):
        if f.endswith('.txt'): z.write(os.path.join(OUT, f), f)
print('trips', collections.Counter(t[0] for t in trips), 'stop_times', len(st), '->', ZIP)
