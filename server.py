from collections import deque
import threading
import os
import sys
import time
import platform
import base64
from flask import Flask, Response, render_template

from session import SessionParser
from util import get_base_dir

base_dir = get_base_dir().resolve()


class App:
    def __init__(self, session_file_parser: SessionParser):
        self.session_file_parser = session_file_parser
        self.parent_pid = os.getppid()
        self.app = Flask(__name__, template_folder=base_dir / "templates")
        self.new_message = threading.Condition()
        if platform.system() == "Linux":
            self.monitor_thread = threading.Thread(
                target=self.monitor_parent, daemon=True
            )
            self.monitor_thread.start()
        self.session_file_watcher = threading.Thread(
            target=self.watch_session_file, daemon=True
        )
        self.session_file_watcher.start()
        self.app.route("/", methods=["GET"])(self.page)
        self.app.route("/data")(self.event_stream)
        self.app.run(
            host="0.0.0.0",
            port=5002,
        )

    def monitor_parent(self):
        while True:
            try:
                os.kill(self.parent_pid, 0)
            except OSError:
                os._exit(1)
            time.sleep(1)

    def page(self):
        return render_template("index.html")

    def watch_session_file(self):
        last_mtime = self.session_file_parser.SESSION_FILE_PATH.lstat().st_mtime
        while True:
            try:
                with self.new_message:
                    current_mtime = (
                        self.session_file_parser.SESSION_FILE_PATH.lstat().st_mtime
                    )
                    if current_mtime != last_mtime:
                        success, err = self.session_file_parser.parse_latest_session()
                        if not success:
                            if err is not None:
                                print(err, file=sys.stderr)
                            else:
                                print("Unknown error occurred", file=sys.stderr)
                            continue

                        last_mtime = current_mtime
                        self.new_message.notify_all()
            except FileNotFoundError as e:
                print(e, file=sys.stderr)
            finally:
                time.sleep(1)

    @staticmethod
    def get_overlay_png_encoded_string():
        with open(base_dir / "all-portals-overlay.png", "rb") as file:
            encoded_string = base64.b64encode(file.read()).decode("utf-8")
        return encoded_string

    def event_stream(self):
        def stream():
            while True:
                with self.new_message:
                    b64_img = self.get_overlay_png_encoded_string()
                    yield f"data: data:image/png;base64,{b64_img}\n\n"
                    self.new_message.wait()

        return Response(stream(), mimetype="text/event-stream")
