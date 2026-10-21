import sys
from pathlib import Path

# Appended, not prepended: ground/cmd.py would otherwise shadow the stdlib cmd module.
sys.path.append(str(Path(__file__).parent.parent / "ground"))
