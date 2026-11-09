import os
import platform
import pathlib
import json

from milp_solver import STRONGHOLD_DATA
from util import get_base_dir, get_ring


class SessionParser:
    SESSION_FILE_PATH: pathlib.Path
    SEPARATOR: str = "\n\n"
    strongholds: list
    paths: list
    current_stronghold: int | None

    def __init__(self):
        base_dir = get_base_dir()
        self.SESSION_FILE_PATH = base_dir / ".session"
        self.reset_to_default()

    def parse_latest_session(self) -> tuple[bool, str | None]:
        text = self.SESSION_FILE_PATH.read_text()
        if len(text) == 0:
            return False, "Nothing in .session"
        sections = text.split(self.SEPARATOR)
        if len(sections) != 4:
            return False, "Not enough sections in .session"
        try:
            if len(sections[0]) != 0:
                self.strongholds = list(json.loads(sections[0]))
                if len(self.strongholds) < len(STRONGHOLD_DATA):
                    return (
                        False,
                        "Not enough measured strongholds. This is unexpected, manually edit .session to fix.",
                    )
            if len(sections[1]) != 0:
                self.paths = list(json.loads(sections[1]))
            if len(sections[2]) != 0:
                self.current_stronghold = int(sections[2])
            self.message = sections[3]
        except json.JSONDecodeError as err:
            return False, err.msg
        return True, None

    def update_current_stronghold(self, add: int):
        if self.current_stronghold is None:
            return
        self.current_stronghold += add
        self.current_stronghold = min(self.current_stronghold, 129)
        self.current_stronghold = max(self.current_stronghold, 8)

    def add_or_update_measurement(self, x: int, z: int) -> tuple[bool, str | None]:
        ring = get_ring(x, z)
        if ring is None:
            return False, "Stronghold not found in any ring"
        self.strongholds[ring - 1] = [x, z]
        return True, None

    def remove_measurement(self, ring: int) -> tuple[bool, str | None]:
        if ring - 1 < 0 or ring - 1 >= len(self.strongholds):
            return False, "ring is not within range [1, 8]"
        if self.strongholds[ring - 1] is None:
            return False, "ring has no measurement yet."
        self.strongholds[ring - 1] = None
        return True, None

    def sync_session(self, wayevents=False):
        self.SESSION_FILE_PATH.write_text(self.get_file_contents())
        # Post an update for waywall
        if platform.system() == "Linux" and wayevents:
            home = os.getenv("HOME")
            if home is None:
                print("Cannot infer $HOME.")
                return
            local_bin_path = home + "/.local/bin"
            cargo_path = home + "/.cargo/bin"
            # Try from $PATH directly
            if os.system("timeout 1 wayevents post update") == 0:
                return
            # Try local bin
            if os.system("timeout 1 " + local_bin_path + "/wayevents post update") == 0:
                return
            # Fallback to cargo path.
            os.system("timeout 1 " + cargo_path + "/wayevents post update")

    def sync_to_backup(self, file_name: str):
        backup_file_path = self.SESSION_FILE_PATH.with_name(file_name)
        backup_file_path.write_text(self.get_file_contents())

    def get_file_contents(self) -> str:
        return self.SEPARATOR.join(
            [
                json.dumps(self.strongholds),
                json.dumps(self.paths),
                str(
                    self.current_stronghold
                    if self.current_stronghold is not None
                    else ""
                ),
                self.message,
            ]
        )

    def is_empty(self):
        return (
            len(self.strongholds) == len(STRONGHOLD_DATA)
            and all(stronghold is None for stronghold in self.strongholds)
            and len(self.paths) == 0
            and self.current_stronghold is None
            and self.message == ""
        )

    def reset_to_default(self):
        self.strongholds = [None] * len(STRONGHOLD_DATA)
        self.paths = []
        self.current_stronghold = None
        self.message = ""
