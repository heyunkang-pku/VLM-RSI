"""Future integration boundaries, intentionally no inference implementation at Gate A."""
from typing import Protocol

class VideoParser(Protocol):
    def parse(self, video_payload: dict, *, seed: int) -> dict: ...
class AtomicChecker(Protocol):
    def check(self, claim_payload: dict) -> dict: ...
class FrozenSolver(Protocol):
    def solve(self, question_payload: dict, *, seed: int) -> dict: ...

def launch_models(*args, **kwargs):
    raise PermissionError('Gate A: no model inference or GPU launch is implemented/authorized')
