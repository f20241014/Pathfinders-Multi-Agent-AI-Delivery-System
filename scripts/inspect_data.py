
import json
from pathlib import Path

files = [
    Path("data/raw/route_data.json"),
    Path("data/raw/package_data.json")
]

for file in files:
    print("\n" + "=" * 60)
    print("FILE:", file.name)

    if not file.exists():
        print("File not found!")
        continue

    print("Size:", round(file.stat().st_size / (1024 * 1024), 2), "MB")

    with file.open("r", encoding="utf-8") as f:
        sample = f.read(5000)

    print("\nFirst 5000 characters:")
    print(sample)

    print("\nFirst character:", repr(sample[:1]))
    print("Last character of sample:", repr(sample[-1:]))
