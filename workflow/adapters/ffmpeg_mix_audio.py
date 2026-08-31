"""FFmpeg mix_audio adapter — mix narration and/or music onto a video."""

import os

from workflow.adapters._ffmpeg_base import FfmpegBase
from workflow.adapters.registry import register


@register("ffmpeg_mix_audio")
class FfmpegMixAudioAdapter(FfmpegBase):
    """Mix narration and/or music audio tracks onto a video."""

    @property
    def input_types(self) -> dict[str, str]:
        return {
            "video_path": "video",
            "narration_path": "audio",
            "music_path": "audio",
        }

    @property
    def output_type(self) -> str:
        return "video"

    def submit(self, config: dict) -> str:
        self.log_prompt(config, {
            k: v for k, v in config.items() if not k.startswith("_")
        }, model="ffmpeg")

        video_path: str = config["video_path"]
        output_path: str = config["output_path"]
        narration_path: str | None = config.get("narration_path")
        music_path: str | None = config.get("music_path")
        music_volume_db: int = config.get("music_volume_db", -12)

        self._require_file(video_path, "Video")
        self._ensure_dir(output_path)

        inputs = ["-i", video_path]
        filter_parts: list[str] = []
        audio_index = 1

        has_narration = narration_path and os.path.exists(narration_path)
        has_music = music_path and os.path.exists(music_path)

        if not has_narration and not has_music:
            raise ValueError("mix_audio requires at least one of narration_path or music_path")

        if has_narration:
            inputs.extend(["-i", narration_path])
            narr_idx = audio_index
            audio_index += 1
        if has_music:
            inputs.extend(["-i", music_path])
            music_idx = audio_index
            audio_index += 1

        if has_narration and has_music:
            filter_parts.append(
                f"[{narr_idx}:a]apad[narr_pad];"
                f"[{music_idx}:a]volume={music_volume_db}dB,apad[music_pad];"
                f"[narr_pad][music_pad]amix=inputs=2:duration=longest[aout]"
            )
        elif has_narration:
            filter_parts.append(f"[{narr_idx}:a]apad[aout]")
        else:
            filter_parts.append(
                f"[{music_idx}:a]volume={music_volume_db}dB,apad[aout]"
            )

        filter_str = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]

        self._run_ffmpeg(cmd)
        return output_path
