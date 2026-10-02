# all-portal-overlay

## Usage Steps

The recommended way of running the the overlay is via the [frozen binaries](https://github.com/lincoln-lm/all-portals-overlay/releases/tag/latest-commit) for Windows & Linux. Otherwise, the python scripts can be executed directly with [uv](https://docs.astral.sh/uv/getting-started/installation/) (replace ``ap_overlay`` with ``uv run main.py`` in all commands).

1. Enter overworld coordinates for the first 8 strongholds in order as a file ``strongholds.json`` in the same directory as the overlay

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

1. Launch the server with ``./ap_overlay server``. This will launch the web server for the overlay and button interface.

1. Open ``http://localhost:5002`` either in a browser or a browser overlay. It should appear blank at first. This will be where the path overlay and instructions are displayed and is the link you would put into an OBS browser overlay.

1. Open ``http://localhost:5002/buttons`` in a browser for a button interface to go to the next or previous stronghold. Alternatively, it may be convenient to set up hotkeys that run the commands ``./ap_overlay next``, ``./ap_overlay prev``, and ``./ap_overlay reset"``.

1. (in a separate terminal) Run the solver ``./ap_overlay solver`` specifying how many threads you want to give it (this will likely be a high upper bound, as it will not be able to use a large amount of threads at once) and a time limit in seconds. If either are not specified, they will default to 16 threads and 30000 seconds. ``./ap_overlay solver --threads 16 --time-limit 3600``. The overlay should periodically update with the current best path until it is fully solved or the time limit is reached. You can additionally specify the ``--headless`` flag to run the solver without opening the extra solver window.

1. Once the solver is complete, you can close the networkx window opened by the solver and the overlay should tell you the first step and be functional.

A backup of the solved path is stored in the current directory as ``backup_{timestamp}.json``. The backup can be utilized by running ``./ap_overlay solver`` with the ``--from-backup`` argument ``./ap_overlay solver --from-backup backup_2026-09-21_22-27-03.json``

## AutoHotkey

The commandline interface can be easily triggered with AutoHotkey

ex.

```
Run, "C:\path\to\overlay\ap_overlay.exe" next,, Hide
```

```
Run, "C:\path\to\overlay\ap_overlay.exe" prev,, Hide
```

```
Run, "C:\path\to\overlay\ap_overlay.exe" reset,, Hide
```
