import sys

if sys.version_info < (3, 14):
    sys.exit("Schalk benötigt Python 3.14.")
if sys.platform != "win32":
    sys.exit("Schalk läuft ausschließlich unter Windows.")

if __name__ == '__main__' and "--selbsttest" in sys.argv:
    # Check of the built EXE in a temporary data folder (set before src.utils.paths is imported)
    import os
    import tempfile
    os.environ["SCHALK_DATA_DIR"] = tempfile.mkdtemp(prefix="schalk_selbsttest_")
    from src.selftest import run
    sys.exit(run())

from src.main import main

if __name__ == '__main__':
    sys.exit(main())
