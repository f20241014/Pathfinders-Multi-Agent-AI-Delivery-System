
import re
from pathlib import Path

source = Path("data/raw/package_data.json")
destination = Path("data/cleaned/package_data.json")

pattern = re.compile(rb'\bNaN\b')

count = 0
carry = b""
destination.parent.mkdir(parents=True, exist_ok=True)

with source.open("rb") as src, destination.open("wb") as dst:
    while True:
        chunk = src.read(1024 * 1024)

        if not chunk:
            break

        combined = carry + chunk
        safe = combined[:-20]
        carry = combined[-20:]

        cleaned, replacements = pattern.subn(b"null", safe)
        dst.write(cleaned)
        count += replacements

    cleaned, replacements = pattern.subn(b"null", carry)
    dst.write(cleaned)
    count += replacements

print("Package cleaning completed.")
print("NaN values replaced:", count)

