import argparse
from datetime import datetime
import json
import pathlib
import sys
import requests

parser = argparse.ArgumentParser()
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
    "--test", action="store_true", help="Use test data instead of strongholds.json"
)
solver_parser.add_argument(
    "--player-count", type=int, default=1, help="Number of players"
)
solver_parser.add_argument(
    "--headless", action="store_true", help="Run the solver without a GUI"
)
solver_parser.add_argument(
    "--from-backup", type=pathlib.Path, default=None, help="Load from backup file"
)


args = parser.parse_args()


def send(data):
    if isinstance(data, str):
        data = {"message": json.dumps({"type": data})}
    requests.post("http://localhost:5002/message", data=data, timeout=1)


if args.command == "next":
    send("next")
elif args.command == "prev":
    send("prev")
elif args.command == "reset":
    send("reset")
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

    app = App()
elif args.command == "solver":
    from milp_solver import solve

    if args.from_backup:
        send(json.loads(args.from_backup.read_text()))
        send("solved")
        sys.exit(0)

    if args.test:
        data = None
    else:
        if getattr(sys, "frozen", False):
            strongholds_path = pathlib.Path(sys.executable).parent / "strongholds.json"
        else:
            strongholds_path = pathlib.Path(__file__).parent / "strongholds.json"

        data = json.loads(strongholds_path.read_text())

    def callback(thread, path):
        message = {
            "message": json.dumps(
                {
                    "type": "path",
                    "paths": [path],
                    "measured": thread.original_measured_shs,
                    "message": f"iteration: {thread.iteration}\n{thread.elapsed_time:.2f} seconds elapsed",
                }
            )
        }
        send(message)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        pathlib.Path(f"backup_{timestamp}.json").write_text(
            json.dumps(message), "utf-8"
        )

    solve(
        data,
        threads=args.threads,
        time_limit=args.time_limit,
        player_count=args.player_count,
        headless=args.headless,
        callback=callback,
    )

    send("solved")
