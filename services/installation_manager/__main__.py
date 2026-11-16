import sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].startswith("candidate-"):
        from .candidate_main import run

        run(sys.argv[1], Path(sys.argv[2]), *sys.argv[3:])
    else:
        from .main import main

        main()
