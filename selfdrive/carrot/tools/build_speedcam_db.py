"""Build the compact speed camera DB for the C2 from the national standard data (data.go.kr 15028200).

Usage: python selfdrive/carrot/tools/build_speedcam_db.py <cameras_15028200.csv (cp949)> <output csv>

Keeps only cameras that enforce a speed limit (limit > 0, speed / signal+speed / section types) and writes
lat,lon,limit,kind,section_m with kind 0 = point camera, 1 = section start, 2 = section end.
"""
import csv
import sys
from collections import Counter

src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src, encoding="cp949")))


def norm(code):
  return "+".join(c.lstrip("0") or "0" for c in code.strip().split("+"))


SPEED_TYPES = {"1", "2", "1+2", "99"}  # 3 = lane/passage, 4 = parking/bus lane (no speed limit)
out, skipped = [], Counter()
for r in rows:
  t = norm(r["단속구분"])
  try:
    limit = int(float(r["제한속도"] or 0))
    lat, lon = float(r["위도"]), float(r["경도"])
  except ValueError:
    skipped["bad number"] += 1
    continue
  if t not in SPEED_TYPES:
    skipped[f"type {t}"] += 1
    continue
  if not 10 <= limit <= 130:
    skipped["no speed limit"] += 1
    continue
  if not (33.0 <= lat <= 38.7 and 124.5 <= lon <= 131.0):
    skipped["outside Korea"] += 1
    continue
  pos = norm(r["단속구간위치구분"]) if r["단속구간위치구분"].strip() else ""
  kind = {"1": 1, "2": 2}.get(pos, 0)
  try:
    section_m = int(float(r["과속단속구간길이"]) * 1000) if kind and r["과속단속구간길이"].strip() else 0
  except ValueError:
    section_m = 0
  if kind == 1 and section_m <= 0:
    kind = 0  # section start without a length: treat as a point camera
  out.append((round(lat, 6), round(lon, 6), limit, kind, section_m))

# identical entries (same spot, same limit) appear once per direction; keep one
uniq = sorted(set(out))
dates = Counter(r["데이터기준일자"][:7] for r in rows)
with open(dst, "w", encoding="utf-8", newline="\n") as f:
  f.write("# Korean fixed speed cameras for openpilot C2 (speed / signal+speed / section only)\n")
  f.write("# Source: 공공데이터포털 전국무인교통단속카메라표준데이터 (data.go.kr 15028200), 경찰청 / 지방자치단체\n")
  f.write(f"# Data reference month (most rows): {dates.most_common(1)[0][0]}; rows: {len(uniq)}\n")
  f.write("# kind: 0 point camera, 1 section start, 2 section end; section_m: section length in meters\n")
  f.write("lat,lon,limit,kind,section_m\n")
  for row in uniq:
    f.write(",".join(str(v) for v in row) + "\n")

print("input rows", len(rows), "kept", len(out), "unique", len(uniq))
print("skipped", dict(skipped))
print("kinds", Counter(r[3] for r in uniq))
print("limits", Counter(r[2] for r in uniq).most_common(8))
