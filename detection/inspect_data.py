
from pathlib import Path
from collections import Counter

print("Current directory:", Path.cwd())
print()

for folder in [Path("images"), Path("masks")]:
    print(f"Checking: {folder}")
    print("Exists:", folder.exists())

    if folder.exists():
        files = [f for f in folder.rglob("*") if f.is_file()]
        real_files = [f for f in files if not f.name.startswith("._") and f.name != ".DS_Store"]

        print("Total files:", len(files))
        print("Real files:", len(real_files))
        print("Extensions:", Counter(f.suffix.lower() for f in real_files))
        print("Example paths:")
        for f in real_files[:10]:
            print(" ", f)

    print()



from pathlib import Path

folders = {
    "Training images": Path("images/train"),
    "Validation images": Path("images/val"),
    "Training masks": Path("masks/train"),
    "Validation masks": Path("masks/val")
}

for name, folder in folders.items():
    files = [
        f for f in folder.glob("*.png")
        if not f.name.startswith("._")
    ]

    print(f"{name}: {len(files)}")
