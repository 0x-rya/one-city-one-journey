# One City, One Journey: quick guide

A journey planner for Ahmedabad and Gandhinagar that combines metro, BRTS and AMTS. It runs on your laptop and keeps working with Wi-Fi off.

---

## Start it

**You need:** Python 3 (most Macs already have it).

```
./run_planner.sh        then open  http://localhost:8008
```

On Windows, double-click `run_planner.bat` instead.

The first start takes about 15 seconds. After that it's quick.

---

## What it does

- Plans a trip using metro, BRTS and AMTS buses together.
- Shows **one total fare**, even when the trip uses more than one operator.
- Shows how the fare would be **split between the operators**.
- Shows where you **change vehicles**, and the walks in between.
- Warns you about **rush-hour delays**, and shows the backup route if you'd miss a bus.
- **Plays the journey** on the map with a time slider.
- Shows **how far you can get** from any point, as a heatmap.
- Works in **English, Hindi and Gujarati**.

---

## Try these

1. Click **Vastral Gam to Gujarat University**. The metro takes 48 min for ₹20; buses alone take 81 min.
2. Click the other option tabs, or a faded route on the map, to compare.
3. Press **▶** at the bottom of the map and watch every option travel on the same clock.
4. Pick **Thaltej Gam to Maninagar** and set the time to **18:00**. Open the bus-only option, then click **Show plan B**.
5. Click **Show heatmap**. Switch between *Metro only* and *Buses only* to see the difference.
6. Switch the language to **ગુજરાતી**.
7. Turn your **Wi-Fi off** and plan another trip. It still works.

---

## Good to know

- **Bus times are timetables, not live tracking.** Rush-hour delays are an estimate based on 2025 traffic data.
- **Metro times and fares** are from GMRC's official timetable and fare chart.
- **AMTS fares** come from June 2023 news reports.

Technical details are in **README.md**.
