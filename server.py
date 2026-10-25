from collections import deque
import threading
import os
import sys
import time
import json
import platform
from flask import Flask, Response, render_template
from html2image import Html2Image

from session import SessionParser

if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.abspath(os.path.dirname(__file__))

hti = Html2Image(output_path=base_dir)


class App:
    def __init__(self, session_file_parser: SessionParser):
        self.session_file_parser = session_file_parser
        self.parent_pid = os.getppid()
        self.app = Flask(__name__, template_folder=os.path.join(base_dir, "templates"))
        self.new_message = threading.Condition()
        self.message_history = []
        self.subscribers = []
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

                        type_ = self.session_file_parser.last_action
                        message = json.dumps(
                            {
                                "type": type_,
                                "paths": self.session_file_parser.paths,
                                "measured": self.session_file_parser.measured,
                                "message": self.session_file_parser.message,
                            }
                        )
                        self.message_history.append(message)
                        if type_ is not None and type_ == "reset":
                            self.message_history.clear()
                        for subscriber in self.subscribers:
                            subscriber.append(message)
                        last_mtime = current_mtime
                        self.new_message.notify_all()
            except FileNotFoundError as e:
                print(e)
                continue
            time.sleep(5)

    def event_stream(self):
        subscriber_id = len(self.subscribers)
        self.subscribers.append(deque())
        if self.message_history:
            with self.new_message:
                self.subscribers[subscriber_id].extend(self.message_history)
                self.new_message.notify_all()

        def stream():
            while True:
                with self.new_message:
                    for message in self.subscribers[subscriber_id]:
                        yield f"data: {message}\n\n"
                    self.subscribers[subscriber_id].clear()
                    self.new_message.wait()

        return Response(stream(), mimetype="text/event-stream")
