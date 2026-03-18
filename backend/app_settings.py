from __future__ import annotations

import os
from typing import Optional

USE_FTS5_SEARCH = os.getenv("USE_FTS5_SEARCH", "true").lower() == "true"


def clean_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None
