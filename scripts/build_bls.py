"""Download the BLS 4.0 data, check it against a pinned hash and convert it.

    uv run --group bls-build python scripts/build_bls.py /out/bls.sqlite

The Docker image runs this in a build stage. BLS 4.0 is published by the Max
Rubner-Institut under CC BY 4.0.
"""

import hashlib
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from snacky.sources.bls import build

URL = "https://blsdb.de/assets/uploads/BLS_4_0_2025_DE.zip"
# Pinned so a changed upstream file fails the image build instead of shipping unseen.
SHA256 = "12b7a6ba62807ec9b301eb276f897dc85f99b2292311618dec3749a12d984c91"
MEMBER = "BLS_4_0_2025_DE/BLS_4_0_Daten_2025_DE.xlsx"


def main(out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "bls.zip"
        request = urllib.request.Request(URL, headers={"User-Agent": "snacky-build/0.1"})
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as f:
            while chunk := response.read(1 << 20):
                f.write(chunk)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != SHA256:
            sys.exit(f"sha256 mismatch for {URL}: expected {SHA256}, got {digest}")
        with zipfile.ZipFile(archive) as z:
            xlsx = Path(z.extract(MEMBER, tmp))
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"{build(xlsx, out)} foods written to {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build_bls.py OUT")
    main(Path(sys.argv[1]))
