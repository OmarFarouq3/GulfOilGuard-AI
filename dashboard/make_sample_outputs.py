"""Write the MOCK scenario as real output files, to test loaders or show the file format.

Usage (from the repository root):
    python dashboard/make_sample_outputs.py <target_dir>

Then point the dashboard at it:
    $env:GULFOILGUARD_OUTPUTS = "<target_dir>"; streamlit run dashboard/app.py

Every file is labelled "synthetic": true. Do not write these into the real outputs/ folder.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from services.mock_data import write_sample_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target_dir", type=Path, help="Folder to create (e.g. sample_outputs)")
    target = parser.parse_args().target_dir.resolve()
    for path in write_sample_outputs(target):
        print(path)


if __name__ == "__main__":
    main()
