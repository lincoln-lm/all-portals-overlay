import pathlib
import sys

STRONGHOLD_DATA = (
    (3, 1280, 2816),
    (6, 4352, 5888),
    (10, 7424, 8960),
    (15, 10496, 12032),
    (21, 13568, 15104),
    (28, 16640, 18176),
    (36, 19712, 21248),
    (10, 22784, 24320),
)


def get_base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        base_dir = pathlib.Path(sys.executable).parent
    else:
        base_dir = pathlib.Path(__file__).parent
    return base_dir


def get_ring(x, z) -> int | None:
    distance = (x**2 + z**2) ** 0.5
    for i, (_, min_distance, max_distance) in enumerate(STRONGHOLD_DATA, start=1):
        if min_distance <= distance < max_distance:
            return i
    return None
