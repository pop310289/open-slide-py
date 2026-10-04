"""Navigation semantics derived from the MIT open-slide player."""

import math


def fit_canvas(container_width, container_height, width=1920, height=1080):
    if not all(math.isfinite(x) for x in (container_width, container_height, width, height)):
        raise ValueError("Canvas dimensions must be finite")
    if min(container_width, container_height, width, height) <= 0:
        return 0.0, 0.0, 0.0
    scale = min(container_width / width, container_height / height)
    return scale, (container_width - width * scale) / 2, (container_height - height * scale) / 2


class Navigator:
    def __init__(self, steps, index=0):
        if not steps:
            raise ValueError("A presentation needs at least one slide")
        self.steps = tuple(max(0, int(n)) for n in steps)
        self.index = max(0, min(index, len(steps) - 1))
        self.revealed = self.steps[self.index]
        self.direction = "jump"

    def jump(self, index):
        index = max(0, min(int(index), len(self.steps) - 1))
        delta = index - self.index
        if delta == 0:
            return False
        self.direction = "forward" if delta == 1 else "backward" if delta == -1 else "jump"
        self.index = index
        self.revealed = 0 if self.direction == "forward" else self.steps[index]
        return True

    def next(self):
        if self.revealed < self.steps[self.index]:
            self.revealed += 1
            return True
        return self.jump(self.index + 1)

    def previous(self):
        if self.revealed > 0:
            self.revealed -= 1
            return True
        return self.jump(self.index - 1)
