"""Compatibility launcher for the existing visualization.py script."""

from pathlib import Path
import runpy


def main() -> None:
    """Run the preserved visualization script only when explicitly requested."""
    runpy.run_path(str(Path(__file__).with_name("visualization.py")), run_name="__main__")


if __name__ == "__main__":
    main()
