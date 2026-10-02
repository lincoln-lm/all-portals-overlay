from collections import deque
import threading
import os
import sys
import time
import json
import platform
from flask import Flask, Response, render_template, request

if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.abspath(os.path.dirname(__file__))


class App:
    def __init__(self):
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
        self.app.route("/", methods=["GET"])(self.page)
        self.app.route("/buttons", methods=["GET"])(self.button_page)
        self.app.route("/data")(self.event_stream)
        self.app.route("/message", methods=["POST"])(self.receive_message)
        self.app.run(host="0.0.0.0", port=5002)

    def monitor_parent(self):
        while True:
            try:
                os.kill(self.parent_pid, 0)
            except OSError:
                os._exit(1)
            time.sleep(1)

    def page(self):
        return render_template("index.html")

    def button_page(self):
        return render_template("buttons.html")

    def receive_message(self):
        with self.new_message:
            message = request.args.get("message") or request.form.get("message")
            self.message_history.append(message)
            if json.loads(message)["type"] == "reset":
                self.message_history.clear()
            for subscriber in self.subscribers:
                subscriber.append(message)
            self.new_message.notify_all()
        return ""

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
