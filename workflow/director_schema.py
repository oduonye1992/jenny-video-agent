"""Director schema — the production document.

Takes the story from creative.json and adds HOW to shoot it: camera, lighting,
color grade, wardrobe specifics, choreographed action, frame sourcing strategy.

Every shot is fully self-contained — no cross-references between shots.
A production house could execute any single shot without needing context from others.

Used by:
- director-agent subagent (writes director.json)
- build-pipeline skill (reads shots + prompts to wire pipeline)
- model-specific prompt agents: sora-agent, veo-agent, kling-agent (reads shots, writes prompts)
- viewer backend (reads/writes for director review screen)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

from workflow.plan_schema import ShotType, AudioStrategy, FrameSource, ShotStatus


DirectorStatus = Literal["draft", "framed", "prompted", "ready"]


@dataclass
class DirectorCharacterRef:
    """Character visual reference for this shot — inlined, not cross-referenced."""
    name: str = ""
    physical_description: str = ""     # skin tone, hair, build, face — full
    wardrobe: str = ""                 # specific to THIS shot (may vary)
    accessories: str = ""
    reference_photos: list[str] = field(default_factory=list)  # paths to locked refs


@dataclass
class DirectorAudioPlan:
    """Audio strategy for this specific shot."""
    strategy: AudioStrategy = "native"
    dialogue: str = ""                 # what is said (talking head — in video audio)
    dialogue_delivery: str = ""        # "steady, low, matter-of-fact, close-mic, dry"
    voiceover: str = ""                # narration text (b-roll — separate TTS)
    voiceover_delivery: str = ""       # TTS delivery direction
    ambient: str = "None."             # always None — enforced


@dataclass
class DirectorFramePlan:
    """How the starting frame for this shot will be sourced."""
    strategy: FrameSource = "pinterest"
    reference_query: str = ""          # pinterest search query, or ref photo path
    edit_from_shot: str | None = None  # shot_id to derive from
    chain_from_shot: str | None = None # shot_id to chain from
    anchor_group: str | None = None    # group ID for shared-anchor shots
    image_prompt: dict | None = None   # Nano Banana JSON spec (if text-to-image)
    generated_frame: str | None = None # path to approved frame (filled after gen)


@dataclass
class DirectorShot:
    """A fully self-contained production spec for one shot."""
    shot_id: str                       # "shot_01" — stable ID for caching/folders
    beat_name: str                     # "The Confession" — display name from creative
    beat_role: str = ""                # hook / build / turn / cta
    type: ShotType = "TALKING_HEAD"
    duration: float = 4.0

    # Production direction
    setting: str = ""                  # full environment description
    camera: str = ""                   # focal length, aperture, angle, movement
    lighting: str = ""                 # sources, direction, color temp, shadows
    color_grade: str = ""              # named colors with hex, saturation, grain
    action: str = ""                   # full choreographed action (movement verbs)
    imperfection: str = ""             # coffee ring, throw blanket, etc.

    # Character (inlined per shot)
    character: DirectorCharacterRef = field(default_factory=DirectorCharacterRef)

    # Audio
    audio: DirectorAudioPlan = field(default_factory=DirectorAudioPlan)

    # Frame sourcing
    frame: DirectorFramePlan = field(default_factory=DirectorFramePlan)

    # Negative direction (model-agnostic)
    avoid: list[str] = field(default_factory=list)

    # Cache invalidation
    content_hash: str = ""             # hash of creative-facing fields
    status: ShotStatus = "draft"

    def compute_content_hash(self) -> str:
        """Hash the fields that come from the creative — if these haven't changed,
        the director's work is still valid."""
        hashable = json.dumps({
            "beat_name": self.beat_name,
            "beat_role": self.beat_role,
            "type": self.type,
            "duration": self.duration,
            "dialogue": self.audio.dialogue,
            "voiceover": self.audio.voiceover,
        }, sort_keys=True)
        return hashlib.sha256(hashable.encode()).hexdigest()[:12]

    def update_content_hash(self) -> None:
        self.content_hash = self.compute_content_hash()


@dataclass
class DirectorPlan:
    version: int = 1
    creative_version: int = 1          # which creative.json version this was built from
    aspect_ratio: str = "9:16"
    profile: str = "cheap"             # cheap / production
    shots: list[DirectorShot] = field(default_factory=list)

    # Global audio
    music_prompt: str = ""             # ElevenLabs music prompt
    voice_design_prompt: str = ""      # ElevenLabs voice design prompt
    voice_id: str | None = None        # locked voice_id (from try-voice)

    status: DirectorStatus = "draft"

    # -- Serialization --

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def save(self, concept_dir: str | Path) -> Path:
        """Save director.json to concept directory."""
        path = Path(concept_dir) / "director.json"
        path.write_text(self.to_json())
        return path

    @classmethod
    def load(cls, path: str | Path) -> DirectorPlan:
        """Load from director.json."""
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> DirectorPlan:
        """Construct DirectorPlan from a dict (parsed JSON)."""
        shots = []
        for s in data.get("shots", []):
            # Shallow-copy to avoid mutating the caller's dict
            s = dict(s)

            # Nested dataclasses
            char_data = s.pop("character", {})
            character = DirectorCharacterRef(**char_data) if char_data else DirectorCharacterRef()

            audio_data = s.pop("audio", {})
            audio = DirectorAudioPlan(**audio_data) if audio_data else DirectorAudioPlan()

            frame_data = s.pop("frame", {})
            frame = DirectorFramePlan(**frame_data) if frame_data else DirectorFramePlan()

            shots.append(DirectorShot(
                character=character,
                audio=audio,
                frame=frame,
                **s,
            ))

        return cls(
            version=data.get("version", 1),
            creative_version=data.get("creative_version", 1),
            aspect_ratio=data.get("aspect_ratio", "9:16"),
            profile=data.get("profile", "cheap"),
            shots=shots,
            music_prompt=data.get("music_prompt", ""),
            voice_design_prompt=data.get("voice_design_prompt", ""),
            voice_id=data.get("voice_id"),
            status=data.get("status", "draft"),
        )

    # -- Markdown rendering --

    def to_markdown(self) -> str:
        """Render as human-readable markdown for director review."""
        lines = [
            "# Director's Shot List",
            "",
            f"*{len(self.shots)} shots · {self.aspect_ratio} · {self.profile} profile · v{self.version}*",
            "",
        ]

        for i, shot in enumerate(self.shots, 1):
            lines += [
                f"## Shot {i} — \"{shot.beat_name}\" · {shot.duration}s · `{shot.type}` · _{shot.beat_role}_",
                "",
            ]

            # Setting & production
            if shot.setting:
                lines.append(f"**Setting**: {shot.setting}")
            if shot.camera:
                lines.append(f"**Camera**: {shot.camera}")
            if shot.lighting:
                lines.append(f"**Lighting**: {shot.lighting}")
            if shot.color_grade:
                lines.append(f"**Color grade**: {shot.color_grade}")
            if shot.imperfection:
                lines.append(f"**Imperfection**: {shot.imperfection}")

            # Action
            if shot.action:
                lines += ["", "**Action**:", f"> {shot.action}"]

            # Character
            c = shot.character
            if c.name:
                lines += [
                    "",
                    f"**Character**: {c.name}",
                    f"- {c.physical_description}" if c.physical_description else "",
                    f"- **Wardrobe**: {c.wardrobe}" if c.wardrobe else "",
                    f"- **Accessories**: {c.accessories}" if c.accessories else "",
                ]
                lines = [l for l in lines if l != ""]  # clean empty

            # Audio
            a = shot.audio
            if a.dialogue:
                lines += ["", f"**Dialogue**: {a.dialogue}"]
                if a.dialogue_delivery:
                    lines.append(f"**Delivery**: {a.dialogue_delivery}")
            if a.voiceover:
                lines += ["", f"**Voiceover**: {a.voiceover}"]
                if a.voiceover_delivery:
                    lines.append(f"**VO delivery**: {a.voiceover_delivery}")
            lines.append(f"**Audio strategy**: {a.strategy}")

            # Frame
            f_plan = shot.frame
            lines.append(f"**Frame source**: {f_plan.strategy}")
            if f_plan.reference_query:
                lines.append(f"**Reference**: {f_plan.reference_query}")
            if f_plan.edit_from_shot:
                lines.append(f"**Edit from**: {f_plan.edit_from_shot}")
            if f_plan.chain_from_shot:
                lines.append(f"**Chain from**: {f_plan.chain_from_shot}")
            if f_plan.generated_frame:
                lines.append(f"**Start frame**: `{f_plan.generated_frame}`")

            # Avoid
            if shot.avoid:
                lines.append(f"**Avoid**: {', '.join(shot.avoid)}")

            lines += ["", "---", ""]

        # Global audio
        lines += ["## Audio", ""]
        if self.music_prompt:
            lines.append(f"- **Music prompt**: {self.music_prompt}")
        if self.voice_design_prompt:
            lines.append(f"- **Voice design**: {self.voice_design_prompt}")
        if self.voice_id:
            lines.append(f"- **Voice ID**: {self.voice_id}")
        lines.append("")

        lines.append(f"*Status: {self.status}*")
        return "\n".join(lines)
