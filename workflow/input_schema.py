"""Input schema — the original brief or source material.

Captures what the user asked for before any creative decisions were made.
This is the first document in the chain: input → creative → director → pipeline.

Used by:
- scout-concept skill (saves at intake)
- scout-deconstruct skill (saves at intake)
- viewer backend (reads for concept detail page)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ConceptInput:
    """The raw intake — what the user provided before creative work began."""

    brief: str = ""                     # the idea, script, or topic
    source_url: str | None = None       # video URL if deconstructing (TikTok, IG, YouTube)
    source_video: str | None = None     # local path to uploaded video file
    video_type: str | None = None       # talking head, b-roll, slideshow, mixed
    duration: float | None = None       # target duration in seconds
    profile: str = "cheap"              # cheap or production
    mode: str = "interactive"           # interactive, semi-auto, full-auto
    notes: str = ""                     # additional creative direction or constraints
    created: str = ""                   # ISO timestamp

    def __post_init__(self):
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat()

    # -- Serialization --

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def save(self, concept_dir: str | Path) -> Path:
        """Save input.json to concept directory."""
        path = Path(concept_dir) / "input.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())
        return path

    @classmethod
    def load(cls, concept_dir: str | Path) -> ConceptInput | None:
        """Load input.json from concept directory, or None if missing."""
        path = Path(concept_dir) / "input.json"
        if not path.exists():
            return None
        return cls.from_dict(json.loads(path.read_text()))

    @classmethod
    def from_dict(cls, data: dict) -> ConceptInput:
        """Build from a dictionary, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})
