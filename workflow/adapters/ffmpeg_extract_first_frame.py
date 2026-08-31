"""FFmpeg extract_first_frame adapter — extract the first frame from a video."""

import os

from workflow.adapters._ffmpeg_base import FfmpegBase
from workflow.adapters.registry import register


@register("ffmpeg_extract_first_frame")
class FfmpegExtractFirstFrameAdapter(FfmpegBase):
    """Extract the first frame (timestamp=0) from a video as a PNG."""

    @property
    def input_types(self) -> dict[str, str]:
        return {"video_path": "video"}

    @property
    def output_type(self) -> str:
        return "image"

    def submit(self, config: dict) -> str:
        self.log_prompt(config, {
            k: v for k, v in config.items() if not k.startswith("_")
        }, model="ffmpeg")

        video_path: str = config["video_path"]
        output_path: str = config["output_path"]

        self._require_file(video_path, "Video")
        self._ensure_dir(output_path)

        cmd = [
            "ffmpeg", "-y",
            "-ss", "0",
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            output_path,
        ]

        self._run_ffmpeg(cmd)

        if not os.path.exists(output_path):
            raise RuntimeError(
                f"ffmpeg extract_first_frame produced no output at {output_path}. "
                f"Video may be empty."
            )

        return output_path
