from collections import deque
import threading
import os
import time
from flask import Flask, Response, render_template, request


class App:
    def __init__(self):
        self.parent_pid = os.getppid()
        self.app = Flask(__name__)
        self.new_message = threading.Condition()
        self.messages = deque()
        self.monitor_thread = threading.Thread(target=self.monitor_parent, daemon=True)
        self.monitor_thread.start()
        self.app.route("/", methods=["GET"])(self.page)
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

    def receive_message(self):
        with self.new_message:
            self.messages.append(
                request.args.get("message") or request.form.get("message")
            )
            self.new_message.notify_all()
        return ""

    def event_stream(self):
        def stream():
            while True:
                with self.new_message:
                    for message in self.messages:
                        yield f"data: {message}\n\n"
                    self.messages.clear()
                    self.new_message.wait()

        return Response(stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    app = App()
