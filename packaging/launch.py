import sys
from pathlib import Path

from noteflow.desktop import main

raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) == 2 else None))
