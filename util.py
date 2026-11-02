import pathlib
import sys


def get_base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        base_dir = pathlib.Path(sys.executable).parent
    else:
        base_dir = pathlib.Path(__file__).parent
    return base_dir
