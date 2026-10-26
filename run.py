import sys
import traceback

if sys.version_info < (3, 11):
    sys.exit("Schalk benötigt Python 3.11 oder neuer.")

from src.main import main
from src.utils.paths import ERROR_LOG

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        with open(ERROR_LOG, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
