import sys

if sys.version_info < (3, 14):
    sys.exit("Schalk benötigt Python 3.14.")
if sys.platform != "win32":
    sys.exit("Schalk läuft ausschließlich unter Windows.")

from src.main import main

if __name__ == '__main__':
    sys.exit(main())
