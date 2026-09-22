# all-portal-overlay

## Usage Steps

The recommended way of running the scripts are via [uv](https://docs.astral.sh/uv/getting-started/installation/).

1. Enter overworld coordinates for the first 8 strongholds in order as a file ``strongholds.json`` in the same directory as ``main.py``

Ex.

```json
[
    [
        -380,
        2020
    ],
    [
        -1292,
        4372
    ],
    [
        -380,
        8756
    ],
    [
        1860,
        10836
    ],
    [
        244,
        14484
    ],
    [
        1492,
        17892
    ],
    [
        1396,
        20468
    ],
    [
        -1180,
        23332
    ]
]
```

1. Run ``main.py`` ``uv run main.py``. This will launch the web server for the overlay and button interface.

2. Open ``http://localhost:5002`` either in a browser or a browser overlay. It should appear blank at first. This will be where the path overlay and instructions are displayed. It should not be open in multiple locations, and OBS browser overlays may keep it open even if the overlay is not visible.

3. Open ``http://localhost:5002/buttons`` in a browser for a button interface to go to the next or previous stronghold. Alternatively, it may be convenient to set up hotkeys that run the commands ``curl -X POST http://localhost:5002/message -d "message={\"type\":\"next\"}"``, ``curl -X POST http://localhost:5002/message -d "message={\"type\":\"prev\"}"``, and ``curl -X POST http://localhost:5002/message -d "message={\"type\":\"reset\"}"``.

4. Run ``solver.py`` specifying how many threads you want to give it (this will likely be a high upper bound, as it will not be able to use a large amount of threads at once) and a time limit in seconds. If either are not specified, they will default to 16 threads and 30000 seconds. ``uv run solver.py --threads 16 --time-limit 3600``. The overlay should periodically update with the current best path until it is fully solved or the time limit is reached.

5. Once the solver is complete, you can close the networkx window opened by the solver and the overlay should tell you the first step and be functional.

A backup of the solved path is stored in the current directory as ``backup_{timestamp}.json``. The backup can be utilized by running ``solver.py`` with the ``--from-backup`` argument ``uv run solver.py --from-backup backup_2026-09-21_22-27-03.json``
