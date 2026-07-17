import sys
import traceback
from src.main import main

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        with open("error.log", "w") as f:
            traceback.print_exc(file=f)
