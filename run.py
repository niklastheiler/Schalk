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
    try:
        from src.selftest import run
    except BaseException:
        # A missing module of the build: reported in the file, the windowed EXE would show a dialog nobody closes
        import traceback
        with open(os.path.join(tempfile.gettempdir(), "schalk_selbsttest.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        sys.exit(1)
    sys.exit(run())

from src.main import main

if __name__ == '__main__':
    sys.exit(main())
