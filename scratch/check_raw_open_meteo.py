import asyncio
import sys
sys.path.insert(0, ".")
from backend.config import STATIONS
from backend.open_meteo_client import poll_all_stations_current

async def check():
    readings = await poll_all_stations_current(STATIONS)
    for sid, r in readings.items():
        print(f"Station {sid:20s}: temp={r.temperature}°C, pres={r.pressure}hPa, hum={r.humidity}%")

if __name__ == "__main__":
    asyncio.run(check())
