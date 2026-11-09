import math
from copy import deepcopy
from PIL import Image, ImageDraw, ImageFont
from milp_solver import SCALE_FACTOR
from util import get_base_dir

IMG_SIZE = (400, 500)


class OverlayImageCreator:
    def __init__(self, config, save_path):
        self.lines = []
        self.circles = []
        self.config = config
        self.save_path = save_path
        self.image = Image.new("RGBA", IMG_SIZE, 128)
        self.draw = ImageDraw.Draw(self.image)
        self.MEASURED = []
        self.PATHS = []
        self.progress = 0
        self.scale = 125

    def draw_stronghold(self, x, y, size=10, color="green"):
        self.circles.append(
            lambda: self.draw.circle(
                (
                    (x * SCALE_FACTOR) / self.scale + 200,
                    (-y * SCALE_FACTOR) / self.scale + 200,
                ),
                size,
                fill=color,
            )
        )

    def draw_path(self, x1, y1, x2, y2, width=1, color="green"):
        self.lines.append(
            lambda: self.draw.line(
                (
                    (x1 * SCALE_FACTOR) / self.scale + 200,
                    (-y1 * SCALE_FACTOR) / self.scale + 200,
                    (x2 * SCALE_FACTOR) / self.scale + 200,
                    (-y2 * SCALE_FACTOR) / self.scale + 200,
                ),
                fill=color,
                width=width,
            )
        )

    def draw_strongholds(self):
        self.image.close()
        self.image = Image.new("RGBA", IMG_SIZE, 128)
        self.draw = ImageDraw.Draw(self.image)
        self.lines = []
        self.circles = []
        self.draw.rectangle([0, 0, 400, 400], fill=self.config["background"])
        for index, (x, y) in enumerate(self.MEASURED):
            self.draw_stronghold(x, y, 4, self.config["completed_stronghold"])

        for path in self.PATHS:
            for path_component in path:
                _, x, y = path_component
                self.draw_stronghold(x, y, 4, self.config["completed_stronghold"])

        for path in self.PATHS:
            if len(path) == 0:
                continue
            _, x, y = path[0]
            last = [x, y]
            for index, (type_, x, y) in enumerate(path):
                type_, x, y = path[index]
                x, y = [x, y]
                line_width = 2 if index == self.progress + 1 else 1
                if type_ != "origin":
                    self.draw_path(
                        last[0],
                        last[1],
                        x,
                        y,
                        line_width,
                        self.config["completed_path"],
                    )
                if type_ != "reset":
                    last = [x, y]

            test = self.progress
            while 0 <= test < len(path):
                type_, x, y = path[test]
                if type_ == "goto":
                    last = [x, y]
                    break
                test -= 1

            index = self.progress
            while index < len(path):
                type_, x, y = path[index]
                line_color = (
                    self.config["next_path"]
                    if index == self.progress + 1
                    else self.config["path"]
                )
                line_width = 4 if index == self.progress + 1 else 3
                stronghold_color = (
                    self.config["current_stronghold"]
                    if index == self.progress
                    else self.config["stronghold"]
                )
                from_x, from_y = x, y
                if type_ == "goto":
                    self.draw_path(last[0], last[1], x, y, line_width, line_color)
                elif type_ == "reset":
                    if index == self.progress:
                        from_x, from_y = last
                    else:
                        self.draw_path(last[0], last[1], x, y, line_width, line_color)
                self.draw_stronghold(from_x, from_y, 5, stronghold_color)
                if type_ != "reset":
                    last = [x, y]
                index += 1
        for line in self.lines:
            line()
        for circle in self.circles:
            circle()

    def next_action(self):
        if self.progress >= len(self.PATHS[0]) - 1:
            return "Complete!"

        type_, x, y = self.PATHS[0][self.progress + 1]
        previous_progress = self.progress
        last_type, last_x, last_y = self.PATHS[0][previous_progress]
        while last_type == "reset":
            previous_progress -= 1
            last_type, last_x, last_y = self.PATHS[0][previous_progress]
        if type_ == "origin":
            last_x, last_y = 0, 0
        x, y = round(x * SCALE_FACTOR / 128), round(y * SCALE_FACTOR / 128)
        last_x, last_y = (
            round(last_x * SCALE_FACTOR / 128),
            round(last_y * SCALE_FACTOR / 128),
        )
        delta_x, delta_y = last_x - x, last_y - y

        theta = (math.atan2(delta_y, delta_x) * 180 / math.pi + 90) % 360
        if theta > 180:
            theta -= 360
        if theta < -180:
            theta += 360
        message = ""
        if self.progress < len(self.PATHS[0]) - 2:
            next_type, _, _ = self.PATHS[0][self.progress + 2]
            if next_type == "origin":
                message = (
                    f"Take bed and go to ({x}, {y})\n(don't set spawn)\n{theta:.1f}"
                )
        if message == "":
            if type_ == "goto":
                message = f"Take bed and go to ({x}, {y})\n{theta:.1f}"
            elif type_ == "reset":
                message = f"Leave bed and go to ({x}, {y})\n{theta:.1f}"
            elif type_ == "origin":
                message = f"Take bed and go to ({x}, {y})\n{theta:.1f}"

            if self.progress == len(self.PATHS[0]) - 2:
                message += "\nDo not go through the fountain!"
        return message

    def update_progress(self, add):
        self.progress += add
        if self.progress >= len(self.PATHS[0]):
            self.progress = len(self.PATHS[0]) - 1
        elif self.progress < 0:
            self.progress = 0
        self.draw_strongholds()
        self.update_text(f"{self.progress + 8}/129\n" + self.next_action())

    def event_next(self):
        self.update_progress(1)

    def event_prev(self):
        self.update_progress(-1)

    def event_path(self, measured, paths, message):
        self.MEASURED = deepcopy(measured)
        for measured_stronghold in self.MEASURED:
            measured_stronghold[0], measured_stronghold[1] = (
                measured_stronghold[0] // SCALE_FACTOR,
                measured_stronghold[1] // SCALE_FACTOR,
            )
        self.PATHS = deepcopy(paths)

        self.draw_strongholds()
        self.update_text(message)

    def event_solved(self):
        self.update_progress(0)

    def update_text(self, text: str):
        if (
            self.config["font"] == ""
            or not (get_base_dir() / self.config["font"]).exists()
        ):
            font = ImageFont.load_default(20)
        else:
            font = ImageFont.truetype(
                get_base_dir() / self.config["font"], size=20, encoding="unic"
            )
        self.draw.rectangle([0, 400, 400, 500], fill=128)

        bbox = self.draw.multiline_textbbox(
            (0, 0),
            text,
            font=font,
            align="center",
            stroke_width=0,
        )
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        x = (400 - text_width) // 2 - bbox[0]
        y = 400 + (100 - text_height) // 2 - bbox[1]

        self.draw.multiline_text(
            (x, y), text, align="center", font=font, stroke_fill="white"
        )

    def event_reset(self):
        self.MEASURED = []
        self.PATHS = []
        self.progress = 0
        self.image.close()
        self.image = Image.new("RGBA", IMG_SIZE, 128)
        self.draw = ImageDraw.Draw(self.image)

    def save_png(self, file_path):
        self.image.save(file_path)
