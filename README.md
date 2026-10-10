# One City, One Journey (Metro Hacks 2026, PS-08)

A metro + BRTS + AMTS journey planner for Ahmedabad and Gandhinagar with a single fare estimate. It runs entirely on a laptop with no network.

**New here? Read [GUIDE.md](GUIDE.md) first.** It's a two-minute read with things to try.

## Run

```
./run_planner.sh          # then open http://localhost:8008
```

On Windows, use `run_planner.bat`. Change the port with `PORT=9000 ./run_planner.sh`.

## Requirements

- **Python 3.9 or newer.** Only the standard library is used, so there is nothing to `pip install`.
- A modern browser. The page loads no external resources; `d3.min.js` is bundled.

The first start builds two caches (`planner/cache.pkl`, `planner/roads.pkl`) in about 10 to 20 s. Later starts take about 3 s.

## Folder layout

```
planner/
  server.py         HTTP server + JSON API (/plan, /heat, /base)
  router.py         Connection Scan Algorithm router, fares, fare split, rush-hour delay model, plan B
  roads.py          snaps bus and walk legs onto OpenStreetMap roads
  index.html, i18n.js, d3.min.js   offline web app (EN / HI / GU)
  data/
    gtfs_bus/       AMTS, BRTS (Janmarg) and Gandhinagar bus GTFS (community feed croyla/amd-gtfs)
    gtfs_metro/     GMRC metro GTFS we built from official GMRC timetable and fare data
    amts_fare_slabs.csv   AMTS fares (reconstructed from June 2023 news; see amts_fares_SOURCES.md)
    tomtom_2025_...csv    hourly congestion used for the delay model
    osm_*.geojson   OpenStreetMap roads (ODbL)
tools/              scripts used to build gtfs_metro from the GMRC data (for reference)
```

## How it works

- **Routing:** Connection Scan Algorithm over about 646,000 scheduled stop-to-stop connections (metro + BRTS + AMTS). A plan takes about 0.2 s.
- **Options:** fastest overall, metro + BRTS, bus only, and metro + AMTS feeder. Duplicate options are dropped.
- **Fares:**
  - Metro: GMRC fare matrix, with consecutive metro legs charged as one journey.
  - BRTS: AJL fare zones.
  - AMTS: distance slabs.
- **Fare split (proposal):**
  - An integrated ticket costs the sum of the operators' fares minus 10%.
  - Each operator gives up a share of that discount in proportion to the distance it carried the passenger.
  - A clearing house run by a PPP partner keeps 1%.
- **Delay model:**
  - AMTS: scheduled time × TomTom 2025 hourly congestion factor (×1.47 at 09:00, ×1.72 at 18:00).
  - BRTS: the same factor applied to 25% of its travel time (WCTR 2019 GPS study).
  - Metro: unaffected.
  - If a connection is likely to be missed, the router re-plans from that stop using the same modes. That backup route is plan B.

## Data sources and honesty notes

- **Metro:** GMRC official fare matrix (1,378 station pairs), official headways from 18 May 2026, and the official (labelled "tentative") Phase-2 trip timetable. Line 1 and 2 trips are generated from the official headways.
- **Bus:** community GTFS (github.com/croyla/amd-gtfs), scraped from the AMTS, AJL and GSCDL portals. Scheduled times, not live. 1.8% of bus hops with impossible speeds (bad stop coordinates in the source) are excluded.
- **Fares:** metro and BRTS from official tables. AMTS fares are reconstructed from June 2023 news reports.
- **Delays:** an estimate from sourced traffic data. No observed AMTS/BRTS delay data is public. The 850 AMTS buses have GPS through the Smart City command centre, and that feed is the obvious PPP data source.

## Attribution

- Bus GTFS: [croyla/amd-gtfs](https://github.com/croyla/amd-gtfs) (MIT, see `planner/data/gtfs_bus/LICENSE`).
- Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL).
- Hourly congestion figures from the [TomTom Traffic Index](https://www.tomtom.com/traffic-index/) (Ahmedabad, 2025).
- Metro timetable and fares: Gujarat Metro Rail Corporation (GMRC) public website.
- [d3.js](https://d3js.org) (ISC licence), bundled for offline use.
