"""Deterministic, fictional grid observations. All timestamps are UTC."""
from datetime import datetime, timedelta
import csv
import math
import random

START = datetime(2026, 7, 22, 17, 40)
END = START + timedelta(minutes=40)
NODE = 'NVA-DEMO-01'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS load_readings(ts TIMESTAMP, zone VARCHAR, actual_mw DOUBLE, forecast_mw DOUBLE, PRIMARY KEY(ts, zone));
CREATE TABLE IF NOT EXISTS reserve_readings(ts TIMESTAMP PRIMARY KEY, iso VARCHAR, reserve_mw DOUBLE);
CREATE TABLE IF NOT EXISTS reserve_history(ts TIMESTAMP PRIMARY KEY, iso VARCHAR, reserve_mw DOUBLE);
CREATE TABLE IF NOT EXISTS congestion_readings(ts TIMESTAMP, node VARCHAR, congestion_per_mwh DOUBLE, PRIMARY KEY(ts, node));
'''

def frame(i):
    ts = START + timedelta(minutes=i)
    load = round(12000 + 35 * math.sin(i / 4), 1)
    forecast = round(11900 + 25 * math.sin(i / 6), 1)
    if 22 <= i <= 26:
        load = 10450 + (i-22)*20
    if 27 <= i <= 34:
        load = 13000 + (i-27)*15
        forecast = 12000
    if i >= 35:
        load = round(12200 + 15 * math.sin(i / 4), 1)
        forecast = 12150
    reserves = round(3800 + 60 * math.sin(i / 5), 1)
    if 24 <= i <= 32:
        reserves = 1800 + (i-24)*25
    congestion = round(10 + 2 * math.sin(i / 3), 2)
    if 25 <= i <= 32:
        congestion = 48 + (i-25)*1.5
    return {
        'ts': ts,
        'load': [(ts, 'Dominion', load, forecast)],
        'reserves': [(ts, 'ERCOT', reserves)],
        'congestion': [(ts, NODE, congestion)],
    }

def seed(conn):
    conn.execute(SCHEMA)
    rng = random.Random(22)
    history=[]
    # Prior three years, same local-hour period, July 8 through August 5.
    for year in (2023, 2024, 2025):
        for day in range(29):
            for hour in (17, 18):
                ts = datetime(year,7,8,hour) + timedelta(days=day)
                history.append((ts, 'ERCOT', round(3800 + rng.gauss(0,260),1)))
    conn.executemany('INSERT INTO reserve_history VALUES (?, ?, ?)', history)
    congestion=[]
    for i in range(91*24):
        ts = START - timedelta(hours=91*24-i)
        congestion.append((ts, NODE, round(max(0, rng.gauss(10,4)),2)))
    conn.executemany('INSERT INTO congestion_readings VALUES (?, ?, ?)', congestion)
    for i in range(-10, 1):
        ingest(conn, frame(i))

def ingest(conn, item):
    for table, key, n in [('load_readings','load',4),('reserve_readings','reserves',3),('congestion_readings','congestion',3)]:
        if item[key]:
            conn.executemany(f'INSERT INTO {table} VALUES ({", ".join(["?"]*n)})', item[key])

def export_fixture(directory):
    """Human-readable replay source, separate from the growing runtime database."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'replay.csv').open('w',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['ts_utc','dominion_load_mw','forecast_mw','ercot_reserve_mw','node_congestion_dollars_mwh'])
        for i in range(41):
            x=frame(i)
            writer.writerow([x['ts'].isoformat()+'Z',x['load'][0][2],x['load'][0][3],x['reserves'][0][2],x['congestion'][0][2]])
