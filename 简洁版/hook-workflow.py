# Local override for PyInstaller's third-party hook-workflow.py.
# Our project has a local module named `workflow.py`, but it is not the
# external `workflow` package that the contrib hook expects.
# Leaving this file intentionally minimal avoids hook import failure.

hiddenimports = []
datas = []
binaries = []
