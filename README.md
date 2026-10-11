# StintBoard

Free live timing for iRacing. Gaps, intervals, sector times, pit stops, stints,
battles and a strategy table, in your browser, for lap-based and timed races.

*Not affiliated with or endorsed by iRacing.com Motorsport Simulations.*

## Download
Get **StintBoard-windows.zip** from the [Releases](../../releases/latest) page.

## How to use
1. Unzip it and start iRacing, then load into a session.
2. Double-click **StintBoard.exe**. Your browser opens the dashboard.
3. Click any driver to see their details in the focus panel.

To watch on a phone or tablet on the same Wi-Fi, open `http://YOUR-PC-IP:8080`
(find the IP by typing `ipconfig` in Command Prompt).

**Windows warning:** the first time, Windows may say "Windows protected your PC".
Click **More info**, then **Run anyway**. The app isn't code-signed, and the full
source code is in this repository so you can check it.

## Notes
- Windows only, because iRacing only shares live data with programs on the same PC.
- Gap trends and catch estimates need about 3 laps of data.
- iRacing doesn't share fuel or tyre data for other cars, so fuel is shown for your car only.

## Run from source
    pip install pyirsdk
    python server.py

## Build the exe yourself
Double-click `build.bat` (needs Python). The exe appears in `dist/`.

## Endurance features
- Driver swap tracking: time in the car for every driver on a team car
- Class filter and class positions for multiclass races
- Fuel planner (your car): burn per lap, laps of fuel, fuel to add to finish, stops still needed
- Track map drawn from your own first lap, with every car shown on it
