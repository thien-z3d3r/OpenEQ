"""
Entry point for running OpenEQ via `python3 -m openeq`.
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main() or 0)
