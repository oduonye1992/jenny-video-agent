"""Structured plan schema — the universal format for creative plans.

Used by:
- scout-concept skill (writes plan.json from CLI or viewer)
- viewer backend (reads/writes plan.json)
- build-pipeline skill (reads shots + prompts to wire pipeline)
- engine resume (reads status per shot)

plan.json is the source of truth. plan.md is rendered from it for human review.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal


ShotType = Literal["TALKING_HEAD", "B-ROLL", "PRODUCT", "MONTAGE"]
AudioStrategy = Literal[
    "native",               # dialogue generated in video (talking head)
    "voiceover_plus_music", # silent clip + TTS + music in post (b-roll)
    "music_only",           # silent clip + music (product/montage)
    "silent",               # no audio
]
FrameSource = Literal[
    "pinterest",       # find reference → scene transfer
    "reference_photo", # user-provided photo → scene transfer
    "text-to-image",   # generate from Nano Banana spec
    "edit_from",       # nano edit from another shot's frame
    "chain_from",      # last frame of previous shot's video
    "existing",        # frame already exists on disk
]
ShotStatus = Literal[
    "draft",           # direction written, no prompt yet
    "prompted",        # model-specific prompt generated
    "framed",          # start frame generated
    "ready",           # ready for pipeline
    "generating",      # video gen in progress
    "done",            # video generated
    "failed",          # generation failed
]
PlanStatus = Literal[
    "draft",           # plan created, not yet reviewed
    "review",          # awaiting user approval
    "approved",        # plan approved, ready for frame gen
    "framing",         # generating frames
    "framed",          # all frames done, ready for pipeline
    "producing",       # pipeline running
    "done",            # final video complete
    "failed",          # production failed
]


@dataclass
class Character:
    name: str = ""
    age: str = ""
    ethnicity: str = ""
    hair: str = ""
    wardrobe: str = ""
    face: str = ""
    build: str = ""
    accessories: str = ""
    description: str = ""  # free-form "who they are" narrative


@dataclass
class ShotPrompts:
    """Model-specific prompts generated from the direction."""
    kling_v3: str | None = None
    veo_v3: str | None = None
    sora_v2: str | None = None
    kling_v2: str | None = None
    seedance_v1_5: str | None = None
    hailuo_02: str | None = None


@dataclass
class Shot:
    name: str                          # creative beat name: "The Reframe"
    type: ShotType                     # TALKING_HEAD, B-ROLL, PRODUCT, MONTAGE
    duration: float                    # seconds
    direction: str                     # the director's brief — model-agnostic
    setting: str = ""                  # where, when, key props
    camera: str = ""                   # shot size, angle, movement
    lighting: str = ""                 # sources, direction, temperature
    dialogue: str = ""                 # what they say (talking head)
    voiceover: str = ""                # narration over visual (b-roll)
    text_overlay: str = ""             # on-screen text (product/cta)
    audio: AudioStrategy = "native"
    frame_source: FrameSource = "pinterest"
    frame_source_ref: str = ""         # shot name to edit/chain from, or pinterest query
    selected_model: str = ""           # adapter name chosen for this shot
    prompts: ShotPrompts = field(default_factory=ShotPrompts)
    image_prompt: dict | None = None   # Nano Banana JSON spec for frame gen
    start_frame: str | None = None     # path to generated frame
    status: ShotStatus = "draft"


@dataclass
class AudioPlan:
    music_mood: str = ""               # "Minimal piano, builds slowly"
    music_prompt: str = ""             # ElevenLabs music prompt
    voice_tone: str = ""               # "Warm, quiet, confessional"
    voice_prompt: str = ""             # ElevenLabs voice design prompt


@dataclass
class Plan:
    title: str
    angle: str
    arc: list[str] = field(default_factory=lambda: ["hook", "build", "turn", "cta"])
    character: Character = field(default_factory=Character)
    shots: list[Shot] = field(default_factory=list)
    audio: AudioPlan = field(default_factory=AudioPlan)
    profile: str = "cheap"             # cheap / production
    aspect_ratio: str = "9:16"
    status: PlanStatus = "draft"
    slug: str = ""
    hook_variations: list[str] = field(default_factory=list)
    compliance_notes: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def save(self, concept_dir: str | Path) -> Path:
        """Save plan.json to concept directory."""
        path = Path(concept_dir) / "plan.json"
        path.write_text(self.to_json())
        return path

    @classmethod
    def load(cls, path: str | Path) -> Plan:
        """Load plan from plan.json."""
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> Plan:
        """Construct Plan from a dict (parsed JSON)."""
        char_data = data.get("character", {})
        character = Character(**char_data) if char_data else Character(name="")

        shots = []
        for s in data.get("shots", []):
            s = dict(s)  # shallow-copy to avoid mutating the caller's dict
            prompts_data = s.pop("prompts", {})
            prompts = ShotPrompts(**prompts_data) if prompts_data else ShotPrompts()
            shots.append(Shot(prompts=prompts, **s))

        audio_data = data.get("audio", {})
        audio = AudioPlan(**audio_data) if audio_data else AudioPlan()

        return cls(
            title=data.get("title", ""),
            angle=data.get("angle", ""),
            arc=data.get("arc", ["hook", "build", "turn", "cta"]),
            character=character,
            shots=shots,
            audio=audio,
            profile=data.get("profile", "cheap"),
            aspect_ratio=data.get("aspect_ratio", "9:16"),
            status=data.get("status", "draft"),
            slug=data.get("slug", ""),
            hook_variations=data.get("hook_variations", []),
            compliance_notes=data.get("compliance_notes", ""),
        )

    def to_markdown(self) -> str:
        """Render plan as human-readable markdown."""
        lines = [
            f"# {self.title}",
            "",
            f"## Angle",
            self.angle,
            "",
            f"## Arc",
            " → ".join(self.arc),
            "",
        ]

        # Character
        c = self.character
        lines += [
            "## Character",
            "",
            f"**{c.name}** — {c.description}" if c.description else f"**{c.name}**",
            "",
        ]
        for label, val in [
            ("Age", c.age), ("Ethnicity", c.ethnicity), ("Hair", c.hair),
            ("Wardrobe", c.wardrobe), ("Face", c.face), ("Build", c.build),
            ("Accessories", c.accessories),
        ]:
            if val:
                lines.append(f"- **{label}**: {val}")
        lines.append("")

        # Shots
        lines += ["---", "", "## Shot List", ""]
        for i, shot in enumerate(self.shots, 1):
            lines += [
                f"### Shot {i} — \"{shot.name}\" · {shot.duration}s · `{shot.type}`",
                "",
            ]
            if shot.setting:
                lines.append(f"**Setting**: {shot.setting}")
            if shot.camera:
                lines.append(f"**Camera**: {shot.camera}")
            if shot.lighting:
                lines.append(f"**Lighting**: {shot.lighting}")
            lines += ["", "**Direction**:", f"> {shot.direction}", ""]
            if shot.dialogue:
                lines += [f"**Dialogue**: {shot.dialogue}", ""]
            if shot.voiceover:
                lines += [f"**Voiceover**: {shot.voiceover}", ""]
            if shot.text_overlay:
                lines += [f"**Text overlay**: {shot.text_overlay}", ""]
            lines.append(f"**Audio**: {shot.audio}")
            lines.append(f"**Frame source**: {shot.frame_source}")
            if shot.frame_source_ref:
                lines.append(f"**Reference**: {shot.frame_source_ref}")
            if shot.selected_model:
                lines.append(f"**Model**: {shot.selected_model}")
            if shot.start_frame:
                lines.append(f"**Start frame**: `{shot.start_frame}`")
            lines += ["", "---", ""]

        # Audio
        lines += ["## Audio Strategy", ""]
        if self.audio.music_mood:
            lines.append(f"- **Music**: {self.audio.music_mood}")
        if self.audio.voice_tone:
            lines.append(f"- **Voice**: {self.audio.voice_tone}")
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

        # Prompts (if any generated)
        has_prompts = any(
            any([s.prompts.kling_v3, s.prompts.veo_v3, s.prompts.sora_v2,
                 s.prompts.kling_v2, s.prompts.seedance_v1_5, s.prompts.hailuo_02])
            for s in self.shots
        )
        if has_prompts:
            lines += ["## Model-Specific Prompts", ""]
            for shot in self.shots:
                p = shot.prompts
                for model, prompt in [
                    ("Kling 3.0", p.kling_v3), ("Veo 3.1", p.veo_v3),
                    ("Sora 2", p.sora_v2), ("Kling 2.6", p.kling_v2),
                    ("Seedance 1.5", p.seedance_v1_5), ("Hailuo 02", p.hailuo_02),
                ]:
                    if prompt:
                        lines += [
                            f"### {shot.name} ({model})",
                            "```",
                            prompt,
                            "```",
                            "",
                        ]

        lines += [f"*Profile: {self.profile} · Aspect: {self.aspect_ratio} · Status: {self.status}*"]
        return "\n".join(lines)
