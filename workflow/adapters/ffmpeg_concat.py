"""FFmpeg concat adapter — concatenate video clips with normalized codec.

Re-encodes to H.264 because HEVC clips from separate API calls have
incompatible POC sequences and cannot be losslessly stream-copied.
"""

import os

from workflow.adapters._ffmpeg_base import FfmpegBase
from workflow.adapters.registry import register


@register("ffmpeg_concat")
class FfmpegConcatAdapter(FfmpegBase):
    """Concatenate video clips via filter_complex re-encode."""

    @property
    def input_types(self) -> dict[str, str]:
        return {"clip_paths": "video[]"}

    @property
    def output_type(self) -> str:
        return "video"

    def submit(self, config: dict) -> str:
        self.log_prompt(config, {
            k: v for k, v in config.items() if not k.startswith("_")
        }, model="ffmpeg")

        clip_paths: list[str] = config["clip_paths"]
        output_path: str = config["output_path"]
        resolution: str | None = config.get("resolution")
        include_audio = config.get("include_audio", False)

        if not clip_paths:
            raise ValueError("concat requires at least one clip in clip_paths")

        for clip in clip_paths:
            self._require_file(clip, "Clip")

        inputs: list[str] = []
        filter_parts: list[str] = []
        concat_inputs: list[str] = []
        n = len(clip_paths)

        for i, clip in enumerate(clip_paths):
            inputs.extend(["-i", clip])
            if resolution:
                width, height = resolution.split(":")
                filter_parts.append(
                    f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]"
                )
            else:
                filter_parts.append(f"[{i}:v]setsar=1[v{i}]")
            concat_inputs.append(f"[v{i}]")

        filter_str = ";".join(filter_parts)

        if include_audio:
            audio_parts = "".join(f"[{i}:a]" for i in range(n))
            filter_str += (
                f";{''.join(concat_inputs)}concat=n={n}:v=1:a=0[outv]"
                f";{audio_parts}concat=n={n}:v=0:a=1[outa]"
            )
        else:
            filter_str += f";{''.join(concat_inputs)}concat=n={n}:v=1:a=0[outv]"

        self._ensure_dir(output_path)

        map_args = ["-map", "[outv]"]
        if include_audio:
            map_args.extend(["-map", "[outa]"])

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_str,
            *map_args,
            "-c:v", "libx264", "-crf", "16", "-preset", "medium",
            *(["-c:a", "aac", "-b:a", "192k"] if include_audio else []),
            "-movflags", "+faststart",
            output_path,
        ]

        self._run_ffmpeg(cmd)

        if not os.path.exists(output_path):
            raise RuntimeError(
                f"ffmpeg concat produced no output file at {output_path}"
            )

        return output_path
