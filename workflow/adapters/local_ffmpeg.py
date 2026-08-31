"""Local ffmpeg adapter — sync operations for video manipulation.

Supports:
  - concat: concatenate video clips (normalized resolution/codec)
  - mix_audio: mix narration + music onto a video
  - extract_frame: extract a single frame at a timestamp
  - slideshow: assemble image slides + music into a video
  - de_ai: anti-AI post-processing (contrast, grain, motion blur, vignette)
"""

import os
import subprocess
import tempfile

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register


@register("local_ffmpeg")
class LocalFfmpegAdapter(Adapter):
    """Sync adapter wrapping ffmpeg subprocess calls."""

    @property
    def timeout_seconds(self) -> int:
        return 300

    @property
    def is_sync(self) -> bool:
        return True

    def submit(self, config: dict) -> str:
        """Run the ffmpeg operation and return the output path."""
        # Log the ffmpeg config (useful for debugging assembly params)
        self.log_prompt(config, {
            k: v for k, v in config.items()
            if not k.startswith("_")
        }, model="ffmpeg")

        operation = config.get("operation")
        if operation == "concat":
            return self._concat(config)
        elif operation == "mix_audio":
            return self._mix_audio(config)
        elif operation == "extract_frame":
            return self._extract_frame(config)
        elif operation == "extract_last_frame":
            return self._extract_last_frame(config)
        elif operation == "slideshow":
            return self._slideshow(config)
        elif operation == "extract_clip":
            return self._extract_clip(config)
        elif operation == "de_ai":
            return self._de_ai(config)
        else:
            raise ValueError(
                f"Unknown local_ffmpeg operation: '{operation}'. "
                f"Expected: concat, mix_audio, extract_frame, extract_last_frame, extract_clip, slideshow, de_ai"
            )

    def poll(self, job_id: str) -> tuple[Status, dict]:
        """Sync adapter — always completed after submit."""
        return Status.COMPLETED, {"output": job_id}

    def get_result(self, job_id: str) -> str:
        """Return the output path (same as job_id for sync adapters)."""
        return job_id

    # ── Operations ────────────────────────────────────────────────────────

    def _concat(self, config: dict) -> str:
        """Concatenate video clips via filter_complex re-encode.

        Re-encodes to H.264 because HEVC clips from separate API calls have
        incompatible POC sequences and cannot be losslessly stream-copied.
        Preserves native resolution and framerate — no scaling or fps forcing.

        Config keys:
            clip_paths: list[str] — paths to input clips
            output_path: str — destination path
            resolution: str — "W:H" to force all clips to this size (optional)
            include_audio: bool — carry audio streams through (default False)
        """
        clip_paths: list[str] = config["clip_paths"]
        output_path: str = config["output_path"]
        resolution: str | None = config.get("resolution")
        include_audio = config.get("include_audio", False)

        if not clip_paths:
            raise ValueError("concat requires at least one clip in clip_paths")

        for clip in clip_paths:
            if not os.path.exists(clip):
                raise FileNotFoundError(f"Clip not found: {clip}")

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

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

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

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed (exit {result.returncode}): "
                f"{result.stderr[-500:]}"
            )

        if not os.path.exists(output_path):
            raise RuntimeError(
                f"ffmpeg concat produced no output file at {output_path}"
            )

        return output_path

    def _mix_audio(self, config: dict) -> str:
        """Mix narration and/or music onto a video.

        Config keys:
            video_path: str — input video
            narration_path: str | None — narration audio file
            music_path: str | None — background music file
            music_volume_db: int — music attenuation (default -12)
            output_path: str — destination path
        """
        video_path: str = config["video_path"]
        output_path: str = config["output_path"]
        narration_path: str | None = config.get("narration_path")
        music_path: str | None = config.get("music_path")
        music_volume_db: int = config.get("music_volume_db", -12)

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        inputs = ["-i", video_path]
        filter_parts: list[str] = []
        audio_index = 1  # next input index after video

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

        # Build audio filter — video is the master duration.
        # Audio tracks are padded with silence (apad) if shorter than the video,
        # and the final output is trimmed to the video length (-shortest).
        if has_narration and has_music:
            # Pad narration to video length, attenuate music, mix together
            filter_parts.append(
                f"[{narr_idx}:a]apad[narr_pad];"
                f"[{music_idx}:a]volume={music_volume_db}dB,apad[music_pad];"
                f"[narr_pad][music_pad]amix=inputs=2:duration=longest[aout]"
            )
        elif has_narration:
            # Pad narration with silence to fill the video duration
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

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg mix_audio failed (exit {result.returncode}): "
                f"{result.stderr[-500:]}"
            )

        return output_path

    def _slideshow(self, config: dict) -> str:
        """Assemble image slides + music into a video.

        Config keys:
            slide_paths: list[str] — paths to slide PNG images
            slide_durations: list[float] — duration per slide in seconds
            music_path: str | None — background music file
            music_volume_db: int — music attenuation (default -8)
            transition: str — "crossfade" or "cut" (default "crossfade")
            transition_duration: float — crossfade duration (default 0.5)
            output_path: str — destination path
        """
        slide_paths: list[str] = config["slide_paths"]
        slide_durations: list[float] = config["slide_durations"]
        music_path: str | None = config.get("music_path")
        music_volume_db: int = config.get("music_volume_db", -8)
        transition: str = config.get("transition", "crossfade")
        transition_dur: float = config.get("transition_duration", 0.5)
        output_path: str = config["output_path"]

        if not slide_paths:
            raise ValueError("slideshow requires at least one slide")
        for p in slide_paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"Slide not found: {p}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # Build ffmpeg inputs: each image with its duration
        inputs: list[str] = []
        for i, (path, dur) in enumerate(zip(slide_paths, slide_durations)):
            inputs.extend(["-loop", "1", "-t", str(dur), "-i", path])

        n = len(slide_paths)

        if transition == "crossfade" and n > 1:
            # Build xfade filter chain
            filter_parts: list[str] = []
            # Scale all inputs
            for i in range(n):
                filter_parts.append(f"[{i}:v]scale=720:1280,setsar=1,fps=30[v{i}]")

            # Chain xfade transitions
            prev = "[v0]"
            offset = slide_durations[0] - transition_dur
            for i in range(1, n):
                out = f"[xf{i}]" if i < n - 1 else "[outv]"
                filter_parts.append(
                    f"{prev}[v{i}]xfade=transition=fade:duration={transition_dur}:offset={offset}{out}"
                )
                prev = f"[xf{i}]"
                if i < n - 1:
                    offset += slide_durations[i] - transition_dur

            filter_str = ";".join(filter_parts)
        else:
            # Simple concat (no transitions)
            filter_parts = []
            for i in range(n):
                filter_parts.append(f"[{i}:v]scale=720:1280,setsar=1,fps=30[v{i}]")
            concat_in = "".join(f"[v{i}]" for i in range(n))
            filter_str = ";".join(filter_parts)
            filter_str += f";{concat_in}concat=n={n}:v=1:a=0[outv]"

        # Add music if present
        if music_path and os.path.exists(music_path):
            music_idx = n
            inputs.extend(["-i", music_path])
            filter_str += f";[{music_idx}:a]volume={music_volume_db}dB[aout]"

            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_str,
                "-map", "[outv]",
                "-map", "[aout]",
                "-c:v", "libx264", "-crf", "22", "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                output_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_str,
                "-map", "[outv]",
                "-c:v", "libx264", "-crf", "22", "-preset", "medium",
                "-movflags", "+faststart",
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg slideshow failed (exit {result.returncode}): "
                f"{result.stderr[-500:]}"
            )

        return output_path

    def _extract_clip(self, config: dict) -> str:
        """Extract a short clip segment from a video.

        Config keys:
            video_path: str — input video
            start: float — start time in seconds (default 0)
            duration: float — clip duration in seconds (default 3)
            output_path: str — destination MP4 path
        """
        video_path: str = config["video_path"]
        start: float = config.get("start", 0)
        duration: float = config.get("duration", 3)
        output_path: str = config["output_path"]

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "16", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg extract_clip failed (exit {result.returncode}): "
                f"{result.stderr[-500:]}"
            )

        if not os.path.exists(output_path):
            raise RuntimeError(
                f"ffmpeg extract_clip produced no output file at {output_path}."
            )

        return output_path

    def _de_ai(self, config: dict) -> str:
        """Anti-AI post-processing — tightens AI video to look more natural.

        Translates CapCut-style grading into FFmpeg filters:
          - Contrast boost (+7 CapCut ≈ 1.07 eq scale) — crisper image
          - Exposure bump (+3 CapCut ≈ +0.03 brightness)
          - Light denoising (-10% particles ≈ hqdn3d) — cleans AI noise
          - No motion blur added (-20% ≈ skip tmix)

        Config keys:
            video_path: str — input video
            output_path: str — destination path
            contrast: float — 0.0-2.0, default 1.07 (CapCut +7)
            brightness: float — -1.0 to 1.0, default 0.03 (CapCut +3)
            saturation: float — 0.0-2.0, default 1.0 (no change)
            denoise: float — hqdn3d strength, 0=off, default 3.0 (light cleanup)
            vignette: float — 0=off, higher=stronger, default 0 (off)
            preset: str — "ugc" (default), "cinematic", "none" (skip)
        """
        video_path: str = config["video_path"]
        output_path: str = config["output_path"]

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # Presets — smart defaults per style
        preset = config.get("preset", "ugc")
        if preset == "none":
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path

        if preset == "cinematic":
            defaults = {
                "contrast": 1.05, "brightness": 0.02, "saturation": 0.95,
                "denoise": 4.0, "vignette": 0.3,
            }
        else:  # ugc (default)
            defaults = {
                "contrast": 1.07, "brightness": 0.03, "saturation": 1.0,
                "denoise": 3.0, "vignette": 0,
            }

        contrast = config.get("contrast", defaults["contrast"])
        brightness = config.get("brightness", defaults["brightness"])
        saturation = config.get("saturation", defaults["saturation"])
        denoise = config.get("denoise", defaults["denoise"])
        vignette_strength = config.get("vignette", defaults["vignette"])

        # Build filter chain
        filters: list[str] = []

        # 1. Denoise — clean up AI micro-artifacts (CapCut particles -10%)
        if denoise > 0:
            filters.append(f"hqdn3d={denoise}")

        # 2. Color grading — contrast boost, exposure bump (CapCut contrast +7, exposure +3)
        eq_parts = []
        if contrast != 1.0:
            eq_parts.append(f"contrast={contrast}")
        if brightness != 0.0:
            eq_parts.append(f"brightness={brightness}")
        if saturation != 1.0:
            eq_parts.append(f"saturation={saturation}")
        if eq_parts:
            filters.append(f"eq={':'.join(eq_parts)}")

        # 3. Vignette — optional, off by default for UGC
        if vignette_strength > 0:
            angle = 0.6 + (vignette_strength * 0.5)
            filters.append(f"vignette=a={angle}")

        if not filters:
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path

        filter_str = ",".join(filters)

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", filter_str,
            "-c:v", "libx264", "-crf", "14", "-preset", "medium",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg de_ai failed (exit {result.returncode}): "
                f"{result.stderr[-500:]}"
            )

        return output_path

    def _extract_frame(self, config: dict) -> str:
        """Extract a single frame from a video at a given timestamp.

        Config keys:
            video_path: str — input video
            timestamp: float — time in seconds
            output_path: str — destination PNG path
        """
        video_path: str = config["video_path"]
        timestamp: float = config.get("timestamp", 0.0)
        output_path: str = config["output_path"]

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg extract_frame failed (exit {result.returncode}): "
                f"{result.stderr[-500:]}"
            )

        if not os.path.exists(output_path):
            raise RuntimeError(
                f"ffmpeg extract_frame produced no output file at {output_path}. "
                f"Video may be empty or timestamp {config.get('timestamp', 0.0)}s is beyond duration."
            )

        return output_path

    def _extract_last_frame(self, config: dict) -> str:
        """Extract the last frame from a video.

        Uses -sseof to seek from the end of the file. Saves the frame as a PNG
        for visual inspection of frame chaining in multi-shot pipelines.

        Config keys:
            video_path: str — input video
            output_path: str — destination PNG path
        """
        video_path: str = config["video_path"]
        output_path: str = config["output_path"]

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-sseof", "-0.1",
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg extract_last_frame failed (exit {result.returncode}): "
                f"{result.stderr[-500:]}"
            )

        if not os.path.exists(output_path):
            raise RuntimeError(
                f"ffmpeg extract_last_frame produced no output at {output_path}. "
                f"Video may be empty."
            )

        return output_path
