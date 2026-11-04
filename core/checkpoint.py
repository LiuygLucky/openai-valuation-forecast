"""Atomic checkpoint replacement with bounded Windows reader-lock retries."""

import time
from pathlib import Path


def write_checkpoint(path: Path, content: str):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.1 * (attempt + 1))
