import argparse
import pathlib
import shutil
import sys
from datetime import datetime
import time

from session import SessionParser
from image import OverlayImageCreator
from util import get_base_dir

parser = argparse.ArgumentParser()
parser.add_argument(
    "--wayevents", action="store_true", help="Post an update to wayevents (Linux only)"
)
subparsers = parser.add_subparsers(dest="command", required=True)

subparsers.add_parser("next", help="Advance to the next stronghold in the path")
subparsers.add_parser("prev", help="Go back to the previous stronghold in the path")
subparsers.add_parser("reset", help="Reset the overlay")

ring_parser = subparsers.add_parser("ring", help="Get the ring of a stronghold")
ring_parser.add_argument("x", type=int, help="X coordinate of the stronghold")
ring_parser.add_argument("z", type=int, help="Z coordinate of the stronghold")
ring_parser.add_argument(
    "-c",
    "--chunk",
    dest="chunk",
    action="store_true",
    help="Use chunk coordinates instead of block coordinates",
)
ring_parser.add_argument(
    "-n",
    "--nether",
    dest="nether",
    action="store_true",
    help="Use nether coordinates instead of overworld coordinates",
)

server_parser = subparsers.add_parser("server", help="Run the server")

solver_parser = subparsers.add_parser("solver", help="Run the MILP solver")
solver_parser.add_argument(
    "--threads", type=int, default=16, help="Number of threads to (try to) use"
)
solver_parser.add_argument(
    "--time-limit", type=int, default=30000, help="Solver time limit in seconds"
)
solver_parser.add_argument(
    "--test",
    action="store_true",
    help="Use test data instead of strongholds in .session",
)
solver_parser.add_argument(
    "--player-count", type=int, default=1, help="Number of players"
)
solver_parser.add_argument(
    "--headless", action="store_true", help="Run the solver without a GUI"
)

add_measurement_parser = subparsers.add_parser(
    "add-measurement", help="Add or update a particular ring's measurement"
)
add_measurement_parser.add_argument(
    "ring",
    type=int,
    help="Ring number of the stronghold you are going to add",
)
add_measurement_parser.add_argument(
    "x", type=int, help="X coordinate of the measurement stronghold"
)
add_measurement_parser.add_argument(
    "z", type=int, help="Z coordinate of the measurement stronghold"
)

remove_measurement_parser = subparsers.add_parser(
    "remove-measurement", help="Remove a particular ring's measurement"
)
remove_measurement_parser.add_argument(
    "ring", type=int, help="Ring number of the stronghold you want to remove"
)

restore_parser = subparsers.add_parser(
    "restore", help="Restore current session from a backup"
)
restore_parser.add_argument("file_path", type=pathlib.Path, help="Path to backup file")

args = parser.parse_args()
base_dir = get_base_dir()

session_file_parser = SessionParser()
if not session_file_parser.SESSION_FILE_PATH.exists():
    session_file_parser.sync_session(
        args.wayevents
    )  # Creates a new .session and writes blank data
success, err = session_file_parser.parse_latest_session()
if not success:
    if err is not None:
        print(err, file=sys.stderr)
    else:
        print("Unknown error", file=sys.stderr)
    sys.exit(0)

creator = OverlayImageCreator(session_file_parser.SESSION_FILE_PATH.resolve())


def update_overlay_png():
    creator.event_path(
        session_file_parser.strongholds,
        session_file_parser.paths,
        session_file_parser.message,
    )
    if session_file_parser.current_stronghold is not None:
        creator.event_solved()
        for i in range(session_file_parser.current_stronghold - 8):
            creator.event_next()
    creator.save_png(base_dir / "all-portals-overlay.png")


def update_session_file(add):
    session_file_parser.update_current_stronghold(add)
    update_overlay_png()
    session_file_parser.sync_session(args.wayevents)


if args.command == "next":
    update_session_file(1)
elif args.command == "prev":
    update_session_file(-1)
elif args.command == "reset":
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file_name = f".session-{timestamp}"
    session_file_parser.sync_to_backup(backup_file_name)
    session_file_parser.reset_to_default()
    update_overlay_png()
    session_file_parser.sync_session(args.wayevents)
    print(f"Backup saved to {backup_file_name}. Restore with: restore <backup_file>")
elif args.command == "ring":
    from milp_solver import STRONGHOLD_DATA

    x = args.x
    z = args.z
    if args.chunk:
        x *= 16
        z *= 16
    if args.nether:
        x *= 8
        z *= 8
    distance = (x**2 + z**2) ** 0.5
    for i, (_, min_distance, max_distance) in enumerate(STRONGHOLD_DATA, start=1):
        if min_distance <= distance < max_distance:
            print(i)
            break
    else:
        print("Stronghold not found in any ring")

elif args.command == "server":
    from server import App

    app = App(session_file_parser=session_file_parser)
elif args.command == "solver":
    from milp_solver import solve

    if (
        session_file_parser.current_stronghold is not None
        and session_file_parser.current_stronghold >= 8
    ):
        # Nothing to do because a solved session already exists.
        sys.exit(0)

    if args.test:
        data = None
    else:
        data = session_file_parser.strongholds

    def callback(thread, path):
        session_file_parser.paths = [path]
        session_file_parser.message = (
            f"iteration: {thread.iteration}\n{thread.elapsed_time:.2f} seconds elapsed"
        )
        update_overlay_png()
        session_file_parser.sync_session(args.wayevents)

    if data is not None and any(measurement is None for measurement in data):
        print(
            "Not enough measured strongholds for solving. Add them with add-measurement",
            file=sys.stderr,
        )
        sys.exit(0)
    solve(
        data,
        threads=args.threads,
        time_limit=args.time_limit,
        player_count=args.player_count,
        headless=args.headless,
        callback=callback,
    )

    # Give a slight delay between update from the callback and this solved update for clients to render correctly.
    time.sleep(0.25)

    session_file_parser.current_stronghold = 8
    session_file_parser.message = ""
    update_overlay_png()
    session_file_parser.sync_session(args.wayevents)
elif args.command == "add-measurement":
    success, err = session_file_parser.add_or_update_measurement(
        args.ring, args.x, args.z
    )
    if not success:
        if err is not None:
            print(err, file=sys.stderr)
        else:
            print("Unknown error occurred", file=sys.stderr)
        sys.exit(0)
    session_file_parser.sync_session(args.wayevents)
elif args.command == "remove-measurement":
    success, err = session_file_parser.remove_measurement(args.ring)
    if not success:
        if err is not None:
            print(err, file=sys.stderr)
        else:
            print("Unknown error occurred", file=sys.stderr)
        sys.exit(0)
    session_file_parser.sync_session(args.wayevents)
elif args.command == "restore":
    shutil.copy(args.file_path, session_file_parser.SESSION_FILE_PATH)
    session_file_parser.parse_latest_session()
    session_file_parser.sync_session(args.wayevents)
