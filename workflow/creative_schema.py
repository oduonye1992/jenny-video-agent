"""Creative schema — the story document.

Captures WHAT the ad says, WHO appears, and HOW it's structured emotionally.
No production details (camera, lighting, color) — those live in director_schema.py.

Used by:
- creative-agent subagent (writes creative.json)
- scout-concept skill (orchestrates the flow)
- viewer backend (reads/writes for creative review screen)
- director-agent subagent (reads as input)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

from workflow.plan_schema import ShotType, AudioStrategy


CreativeStatus = Literal["draft", "approved"]


@dataclass
class CreativeCharacter:
    """Who appears in the ad. Vibes and demographics, not production specs."""
    name: str = ""
    who: str = ""                      # "A woman who's been running on empty..."
    age: str = ""                      # "Early 40s"
    ethnicity: str = ""                # "Black"
    hair: str = ""                     # "Dark brown, natural twist-out..."
    wardrobe: str = ""                 # "Cream pinstripe suit"
    voice: str = ""                    # "Warm, quiet, confessional"


@dataclass
class CreativeBeat:
    """A story beat — what the viewer sees and feels."""
    name: str                          # "The Confession"
    role: str = ""                     # hook / build / turn / cta
    type: ShotType = "TALKING_HEAD"
    duration: float = 4.0
    emotion: str = ""                  # "Steady, matter-of-fact"
    action_summary: str = ""           # what a viewer would notice
    dialogue: str = ""                 # with inline delivery notes [whispered]
    voiceover: str = ""                # narration over visual (b-roll)
    text_overlay: str = ""             # on-screen text (product/cta)


@dataclass
class CreativeAudio:
    """Audio direction — mood, not specs."""
    music_direction: str = ""          # "Minimal piano, builds slowly"
    voice_direction: str = ""          # "Warm, quiet, confessional"
    audio_strategy: AudioStrategy = "native"


@dataclass
class Creative:
    title: str
    angle: str                         # the specific take — one sentence
    arc: list[str] = field(default_factory=lambda: ["hook", "build", "turn", "cta"])
    character: CreativeCharacter = field(default_factory=CreativeCharacter)
    beats: list[CreativeBeat] = field(default_factory=list)
    audio: CreativeAudio = field(default_factory=CreativeAudio)
    hook_variations: list[str] = field(default_factory=list)
    compliance_notes: str = ""
    target_duration: float = 0.0
    target_platform: str = "tiktok"
    version: int = 1
    status: CreativeStatus = "draft"

    # -- Serialization --

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def save(self, concept_dir: str | Path) -> Path:
        """Save creative.json to concept directory."""
        path = Path(concept_dir) / "creative.json"
        path.write_text(self.to_json())
        return path

    @classmethod
    def load(cls, path: str | Path) -> Creative:
        """Load from creative.json."""
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> Creative:
        """Construct Creative from a dict (parsed JSON)."""
        char_data = data.get("character", {})
        character = CreativeCharacter(**char_data) if char_data else CreativeCharacter()

        beats = []
        for b in data.get("beats", []):
            beats.append(CreativeBeat(**b))

        audio_data = data.get("audio", {})
        audio = CreativeAudio(**audio_data) if audio_data else CreativeAudio()

        return cls(
            title=data.get("title", ""),
            angle=data.get("angle", ""),
            arc=data.get("arc", ["hook", "build", "turn", "cta"]),
            character=character,
            beats=beats,
            audio=audio,
            hook_variations=data.get("hook_variations", []),
            compliance_notes=data.get("compliance_notes", ""),
            target_duration=data.get("target_duration", 0.0),
            target_platform=data.get("target_platform", "tiktok"),
            version=data.get("version", 1),
            status=data.get("status", "draft"),
        )

    # -- Markdown rendering --

    def to_markdown(self) -> str:
        """Render as human-readable markdown for creative review."""
        lines = [
            f"# {self.title}",
            "",
            "## Angle",
            self.angle,
            "",
            "## Arc",
            " → ".join(self.arc),
            "",
        ]

        # Character
        c = self.character
        lines += [
            "## Character",
            "",
            f"**{c.name}**" + (f" — {c.who}" if c.who else ""),
            "",
        ]
        for label, val in [
            ("Age", c.age), ("Ethnicity", c.ethnicity), ("Hair", c.hair),
            ("Wardrobe", c.wardrobe), ("Voice", c.voice),
        ]:
            if val:
                lines.append(f"- **{label}**: {val}")
        lines.append("")

        # Beats
        lines += ["---", "", "## Beats", ""]
        for i, beat in enumerate(self.beats, 1):
            lines += [
                f"### {i}. \"{beat.name}\" · {beat.duration}s · `{beat.type}` · _{beat.role}_",
                "",
            ]
            if beat.emotion:
                lines.append(f"**Emotion**: {beat.emotion}")
            if beat.action_summary:
                lines.append(f"**What happens**: {beat.action_summary}")
            if beat.dialogue:
                lines += ["", f"> {beat.dialogue}"]
            if beat.voiceover:
                lines += ["", f"*VO: {beat.voiceover}*"]
            if beat.text_overlay:
                lines += ["", f"[TEXT: {beat.text_overlay}]"]
            lines += ["", "---", ""]

        # Audio
        lines += ["## Audio", ""]
        if self.audio.music_direction:
            lines.append(f"- **Music**: {self.audio.music_direction}")
        if self.audio.voice_direction:
            lines.append(f"- **Voice**: {self.audio.voice_direction}")
        lines.append(f"- **Strategy**: {self.audio.audio_strategy}")
        lines.append("")

        # Hooks
        if self.hook_variations:
            lines += ["## Hook Variations", ""]
            for i, hook in enumerate(self.hook_variations, 1):
                lines.append(f"{i}. {hook}")
            lines.append("")

        # Compliance
        if self.compliance_notes:
            lines += ["## Compliance", "", self.compliance_notes, ""]

        lines += [
            f"*Duration: {self.target_duration}s · Platform: {self.target_platform} "
            f"· Version: {self.version} · Status: {self.status}*"
        ]
        return "\n".join(lines)
