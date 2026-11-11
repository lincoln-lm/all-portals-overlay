import threading
import os
import time
import platform
import base64
from flask import Flask, Response, render_template

from util import get_base_dir

base_dir = get_base_dir().resolve()


class App:
    def __init__(self):
        self.parent_pid = os.getppid()
        self.app = Flask(__name__, template_folder=base_dir / "templates")
        self.image_path = base_dir / "all-portals-overlay.png"
        if platform.system() == "Linux":
            self.monitor_thread = threading.Thread(
                target=self.monitor_parent, daemon=True
            )
            self.monitor_thread.start()
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

    def get_overlay_png_encoded_string(self):
        if self.image_path.exists():
            return base64.b64encode(self.image_path.read_bytes()).decode("utf-8")
        # transparent 1x1 png
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="

    def get_image_mtime(self):
        if self.image_path.exists():
            return self.image_path.lstat().st_mtime
        return 0

    def event_stream(self):
        def stream():
            last_mtime = self.get_image_mtime()
            b64_img = self.get_overlay_png_encoded_string()
            yield f"data: data:image/png;base64,{b64_img}\n\n"
            while True:
                if self.get_image_mtime() != last_mtime:
                    last_mtime = self.get_image_mtime()
                    b64_img = self.get_overlay_png_encoded_string()
                    yield f"data: data:image/png;base64,{b64_img}\n\n"
                time.sleep(0.2)

        return Response(stream(), mimetype="text/event-stream")
