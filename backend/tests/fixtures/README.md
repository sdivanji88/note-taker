# Fixtures

Real photos of highlighted *Permutation City* pages, used by the `live` extractor tests
(`uv run pytest -m live`).

- `sample-p163.jpg` — **committed.** Downscaled to 1600px with all EXIF/GPS stripped. Page 163: three
  highlighted passages plus the handwritten margin note "Insurance fraud is a main plot point?".
- `PXL_*.jpg` — **not committed** (gitignored). Full-size originals; they carry GPS location. Keep them
  local. One of them (`PXL_20261109_120732142.jpg`) is rotated 90° in the pixels with no EXIF
  orientation tag; it exercises rotation detection. It also has a single pale highlight line.

Never commit a photo straight from the phone: strip EXIF first.
