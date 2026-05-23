import sys
from pathlib import Path

print(f"has _MEIPASS: {hasattr(sys, '_MEIPASS')}")
if hasattr(sys, '_MEIPASS'):
    print(f"_MEIPASS: {sys._MEIPASS}")
else:
    print("No _MEIPASS")

# In COLLECT mode, check if we can find the exe path
print(f"Executable: {sys.executable}")
exe_dir = Path(sys.executable).parent
print(f"Exe dir: {exe_dir}")
print(f"Exe dir exists: {exe_dir.exists()}")
if exe_dir.exists():
    print(f"Exe dir contents: {[x.name for x in exe_dir.iterdir()]}")
    internal = exe_dir / "_internal"
    print(f"_internal exists: {internal.exists()}")
    if internal.exists():
        print(f"_internal contents: {[x.name for x in internal.iterdir() if x.is_dir()]}")
        pb = internal / "playwright_browsers"
        print(f"playwright_browsers exists: {pb.exists()}")
        if pb.exists():
            print(f"playwright_browsers contents: {[x.name for x in pb.iterdir()]}")
