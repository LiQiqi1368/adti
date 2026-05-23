import sys
from pathlib import Path

if hasattr(sys, '_MEIPASS'):
    meipass = Path(sys._MEIPASS)
    print(f"_MEIPASS: {meipass}")
    
    # Test the exact path from code
    browser_path = meipass / "playwright_browsers" / "chromium-1208" / "chrome-win64" / "chrome.exe"
    print(f"Browser path: {browser_path}")
    print(f"Browser exists: {browser_path.exists()}")
    
    # Also check parent dirs
    pb = meipass / "playwright_browsers"
    print(f"playwright_browsers exists: {pb.exists()}")
    if pb.exists():
        print(f"playwright_browsers contents: {[x.name for x in pb.iterdir()]}")
        c8 = pb / "chromium-1208"
        print(f"chromium-1208 exists: {c8.exists()}")
        if c8.exists():
            print(f"chromium-1208 contents: {[x.name for x in c8.iterdir()]}")
            cw = c8 / "chrome-win64"
            print(f"chrome-win64 exists: {cw.exists()}")
            if cw.exists():
                print(f"chrome-win64 contents: {[x.name for x in cw.iterdir()]}")
