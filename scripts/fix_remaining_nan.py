
from pathlib import Path

path = Path("data/cleaned/package_data.json")
temp = path.with_suffix(".json.tmp")

old = b'"end_time_utc": NaN'
new = b'"end_time_utc": null'

count = 0
carry = b""
overlap = len(old) - 1

with path.open("rb") as src, temp.open("wb") as dst:
    while True:
        chunk = src.read(1024 * 1024)

        if not chunk:
            break

        data = carry + chunk
        safe = data[:-overlap] if len(data) > overlap else b""
        carry = data[len(safe):]

        count += safe.count(old)
        dst.write(safe.replace(old, new))

    count += carry.count(old)
    dst.write(carry.replace(old, new))

temp.replace(path)

print("Targeted fixes:", count)
print("Completed.")
