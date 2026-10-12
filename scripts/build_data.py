#!/usr/bin/env python3
"""data/raw/ のCSV（みるもからエクスポートしたもの）を集計し docs/data/dashboard.json を生成する。

CSVの種類はファイル名ではなくヘッダー行で判定するので、ファイル名は自由。
期間が重複するCSVを追加しても、日時をキーに重複排除してマージする。

    python3 scripts/build_data.py
"""
import csv
import io
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "data" / "dashboard.json"

EVENT_TYPES = ["離床", "トイレON", "トイレOFF", "ドアオープン", "ドアクローズ"]
NIGHT_START, NIGHT_END = 22, 6  # 夜間帯 22:00〜翌6:00
SENSOR_BUCKET_MIN = 10  # センサー値の平均化単位（分）


def read_csv(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"文字コードを判定できません: {path}")
    return list(csv.reader(io.StringIO(text)))


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_all():
    events, sensor, sleep = {}, {}, {}
    for path in sorted(RAW_DIR.glob("*.csv")):
        rows = read_csv(path)
        if not rows:
            continue
        header = rows[0]
        if header[0] == "発生日時":
            for r in rows[1:]:
                if len(r) < 2 or not r[0]:
                    continue
                ts = datetime.strptime(r[0], "%Y/%m/%d %H:%M:%S")
                events[(ts, r[1])] = {"ts": ts, "type": r[1], "text": r[2] if len(r) > 2 else ""}
        elif header[0] == "日時" and "温度" in header:
            idx = {name: i for i, name in enumerate(header)}
            for r in rows[1:]:
                if not r or not r[0] or len(r) <= idx["温度"] or r[idx["温度"]] == "":
                    continue
                ts = datetime.strptime(r[0], "%Y/%m/%d %H:%M")
                sensor[ts] = {
                    "temp": to_float(r[idx["温度"]]),
                    "hum": to_float(r[idx["湿度"]]),
                    "lux": to_float(r[idx["照度"]]),
                    "wbgt": to_float(r[idx["暑さ指数"]]),
                    "motion": to_float(r[idx["運動指数"]]),
                    "presence": r[idx["外出情報"]],
                }
        elif header[0] == "日時" and "就寝" in header:
            for r in rows[1:]:
                if not r or not r[0]:
                    continue
                vals = dict(zip(header, r))
                if not any(vals.get(k) for k in ("就寝", "起床", "睡眠時間", "夜間起床")):
                    continue  # 未確定（当日分など）の空行で既存データを上書きしない
                sleep[r[0]] = {
                    "date": r[0].replace("/", "-"),
                    "bed": vals.get("就寝") or None,
                    "wake": vals.get("起床") or None,
                    "duration": vals.get("睡眠時間") or None,
                    "nightWake": to_float(vals.get("夜間起床")),
                }
        else:
            print(f"[skip] 未対応のCSV形式: {path.name}")
    return (
        sorted(events.values(), key=lambda e: e["ts"]),
        dict(sorted(sensor.items())),
        [sleep[k] for k in sorted(sleep)],
    )


def night_key(ts):
    """夜間帯に属するなら、その夜の開始日（22時側の日付）を返す。"""
    if ts.hour >= NIGHT_START:
        return ts.date().isoformat()
    if ts.hour < NIGHT_END:
        return (ts.date() - timedelta(days=1)).isoformat()
    return None


def build():
    events, sensor, sleep = load_all()
    dates = sorted({e["ts"].date() for e in events} | {t.date() for t in sensor})
    if not dates:
        raise SystemExit("data/raw/ にCSVがありません")
    day_list = []
    d = dates[0]
    while d <= dates[-1]:
        day_list.append(d.isoformat())
        d += timedelta(days=1)

    # 日別・時間帯別の件数
    daily = {day: Counter() for day in day_list}
    hourly = defaultdict(lambda: [0] * 24)  # (day, type) -> 24h
    night_bedexit = Counter()
    for e in events:
        day = e["ts"].date().isoformat()
        daily[day][e["type"]] += 1
        hourly[(day, e["type"])][e["ts"].hour] += 1
        if e["type"] == "離床" and (nk := night_key(e["ts"])) in daily:
            night_bedexit[nk] += 1

    # トイレ滞在時間（ON → 次のOFF）
    toilet_visits = []
    open_on = None
    for e in events:
        if e["type"] == "トイレON":
            open_on = e["ts"]
        elif e["type"] == "トイレOFF" and open_on is not None:
            minutes = (e["ts"] - open_on).total_seconds() / 60
            if minutes <= 180:  # 欠損による異常ペアは除外
                toilet_visits.append({"start": open_on.strftime("%Y-%m-%dT%H:%M:%S"), "min": round(minutes, 1)})
            open_on = None
    toilet_by_day = defaultdict(list)
    for v in toilet_visits:
        toilet_by_day[v["start"][:10]].append(v["min"])

    # センサー：10分平均 + 日別サマリ
    buckets = defaultdict(list)
    sensor_daily = defaultdict(list)
    for ts, v in sensor.items():
        b = ts.replace(minute=ts.minute - ts.minute % SENSOR_BUCKET_MIN)
        buckets[b].append(v)
        sensor_daily[ts.date().isoformat()].append(v)

    def avg(vals, key, nd=1):
        xs = [v[key] for v in vals if v[key] is not None]
        return round(statistics.fmean(xs), nd) if xs else None

    sensor_series = [
        {
            "t": b.strftime("%Y-%m-%dT%H:%M"),
            "temp": avg(vs, "temp"),
            "hum": avg(vs, "hum"),
            "lux": avg(vs, "lux"),
            "wbgt": avg(vs, "wbgt"),
            "motion": avg(vs, "motion"),
            "away": sum(1 for v in vs if v["presence"] and v["presence"] != "在宅"),
        }
        for b, vs in sorted(buckets.items())
    ]

    days = []
    for day in day_list:
        c = daily[day]
        sv = sensor_daily.get(day, [])
        temps = [v["temp"] for v in sv if v["temp"] is not None]
        days.append({
            "date": day,
            "counts": {t: c.get(t, 0) for t in EVENT_TYPES},
            "nightBedExit": night_bedexit.get(day, 0),
            "toiletAvgMin": round(statistics.fmean(toilet_by_day[day]), 1) if toilet_by_day[day] else None,
            "toiletMaxMin": max(toilet_by_day[day]) if toilet_by_day[day] else None,
            "tempAvg": avg(sv, "temp"),
            "tempMin": min(temps) if temps else None,
            "tempMax": max(temps) if temps else None,
            "humAvg": avg(sv, "hum"),
            "wbgtMax": max((v["wbgt"] for v in sv if v["wbgt"] is not None), default=None),
            "motionAvg": avg(sv, "motion"),
            "sensorMinutes": len(sv),
            "hourly": {t: hourly[(day, t)] for t in EVENT_TYPES},
        })

    out = {
        "deviceId": "351",
        "generatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "period": {"from": day_list[0], "to": day_list[-1]},
        "nightWindow": [NIGHT_START, NIGHT_END],
        "eventTypes": EVENT_TYPES,
        "days": days,
        "sensor": sensor_series,
        "sleep": sleep,
        "toiletVisits": toilet_visits,
        "events": [
            {"t": e["ts"].strftime("%Y-%m-%dT%H:%M:%S"), "type": e["type"], "text": e["text"]}
            for e in events
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(events)} events, {len(sensor)} sensor rows, "
          f"{len(sleep)} sleep rows, {day_list[0]}〜{day_list[-1]}")


if __name__ == "__main__":
    build()
