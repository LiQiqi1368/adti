import sys
from pathlib import Path

print(f"Python executable: {sys.executable}")
print(f"has _MEIPASS: {hasattr(sys, '_MEIPASS')}")

if hasattr(sys, '_MEIPASS'):
    print(f"_MEIPASS: {sys._MEIPASS}")
    p = Path(sys._MEIPASS)
    print(f"_MEIPASS exists: {p.exists()}")
    if p.exists():
        print(f"Top-level dirs: {[x.name for x in p.iterdir() if x.is_dir()]}")
        pb = p / "playwright_browsers"
        print(f"playwright_browsers exists: {pb.exists()}")
        if pb.exists():
            print(f"playwright_browsers contents: {[x.name for x in pb.iterdir()]}")
            chrome = pb / "chromium-1208" / "chrome-win64" / "chrome.exe"
            print(f"chrome.exe exists: {chrome.exists()}")
            print(f"chrome.exe path: {chrome}")
else:
    print("Running in development mode")
    # Check what the path would be
    print("Current dir:", Path.cwd())
    print("Script dir:", Path(__file__).parent)
