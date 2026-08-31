"""Tests for DAG template builders.

Each template is a pure function: spec dict in, DAG out. No API calls, fully deterministic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from workflow.dag import DAG, Step
from workflow.templates import broll, talking_head, slideshow, motion_control, video


def _dag(template, spec):
    """Compile a spec via the template and return a DAG."""
    return DAG.from_json(template.compile(spec))


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def broll_spec_3_shots():
    return {
        "video_type": "broll",
        "run_name": "test-broll",
        "models": {
            "image_gen": {"adapter": "test_image_adapter"},
            "video_gen": {"adapter": "test_video_adapter"},
            "upscale": {"adapter": ""},
            "tts": {"adapter": "test_tts_adapter"},
            "music": {"adapter": "test_music_adapter"},
        },
        "shots": [
            {"shot_id": "shot_1", "scene": "scene1", "subject": "subj1", "action": "act1", "lighting": "warm daylight", "camera": "medium shot, 50mm", "color_grade": "warm filmic", "style": "phone camera UGC", "video_prompt": "SCENE: test scene 1"},
            {"shot_id": "shot_2", "scene": "scene2", "subject": "subj2", "action": "act2", "lighting": "warm daylight", "camera": "medium shot, 50mm", "color_grade": "warm filmic", "style": "phone camera UGC", "video_prompt": "SCENE: test scene 2"},
            {"shot_id": "shot_3", "scene": "scene3", "subject": "subj3", "action": "act3", "lighting": "warm daylight", "camera": "medium shot, 50mm", "color_grade": "warm filmic", "style": "phone camera UGC", "video_prompt": "SCENE: test scene 3"},
        ],
        "narration": {"script": "Hello world", "voice_description": "Warm female narrator, mid-20s, conversational"},
        "music": {"mood": "calm", "prompt": "gentle piano"},
        "merge": {"resolution": "1080:1920"},
        "mix": {"music_volume_db": -12},
        "output": {"dir": "outputs/runs/test-broll", "final_filename": "final.mp4"},
    }


@pytest.fixture
def talking_head_spec_3_shots():
    return {
        "video_type": "talking_head",
        "models": {
            "image_gen": {"adapter": "test_image_adapter"},
            "image_upscale": {"adapter": ""},
            "video_gen": {"adapter": "test_video_adapter"},
            "upscale": {"adapter": ""},
            "ffmpeg": {"adapter": "test_ffmpeg_adapter"},
        },
        "character": {
            "name": "Duke",
            "description": "A friendly golden retriever",
            "outfit": "red bandana",
        },
        "shots": [
            {
                "scene": "a cozy living room",
                "subject": "Duke, a friendly golden retriever",
                "action": "waves hello warmly",
                "camera": "medium close-up",
                "lighting": "warm natural light",
                "color_grade": "warm filmic, slight grain",
                "style": "phone camera UGC, slightly shaky",
                "dialogue": "[friendly] Hey there!",
                "duration": 5,
                "video_prompt": "SCENE: Duke waves hello in a cozy living room.",
            },
            {
                "scene": "same cozy living room",
                "subject": "Duke",
                "action": "talks about sleep",
                "camera": "medium close-up",
                "lighting": "warm natural light",
                "color_grade": "warm filmic, slight grain",
                "style": "phone camera UGC, slightly shaky",
                "dialogue": "[calm] Let's talk about sleep.",
                "duration": 5,
                "video_prompt": "SCENE: Duke talks about sleep calmly.",
            },
            {
                "scene": "same cozy living room",
                "subject": "Duke",
                "action": "says goodbye with a wave",
                "camera": "medium close-up",
                "lighting": "warm natural light",
                "color_grade": "warm filmic, slight grain",
                "style": "phone camera UGC, slightly shaky",
                "dialogue": "[warm] Bye for now!",
                "duration": 5,
                "video_prompt": "SCENE: Duke says goodbye with a warm wave.",
            },
        ],
        "aspect_ratio": "9:16",
        "output": {"dir": "outputs/test-th", "final_filename": "final.mp4"},
    }


@pytest.fixture
def slideshow_spec_4_slides():
    return {
        "video_type": "slideshow",
        "models": {
            "music": {"adapter": "test_music_adapter"},
            "ffmpeg": {"adapter": "test_ffmpeg_adapter"},
        },
        "slides": [
            {"headline": "Slide 1", "body": "Body 1", "duration": 3},
            {"headline": "Slide 2", "body": "Body 2", "duration": 4},
            {"headline": "Slide 3", "body": "Body 3", "duration": 5},
            {"headline": "Slide 4", "body": "Body 4", "duration": 3},
        ],
        "music": {"mood": "upbeat"},
        "aspect_ratio": "9:16",
        "output": {"dir": "outputs/test-ss", "final_filename": "final.mp4"},
    }


@pytest.fixture
def motion_control_spec():
    return {
        "video_type": "motion_control",
        "models": {
            "image_gen": {"adapter": "test_image_adapter"},
            "video_gen": {"adapter": "test_video_adapter"},
            "ffmpeg": {"adapter": "test_ffmpeg_adapter"},
        },
        "character": {
            "name": "Duke",
            "description": "A friendly golden retriever",
            "outfit": "red bandana",
        },
        "reference_clip": {
            "url": "https://example.com/clip.mp4",
            "start_time": 0,
            "end_time": 10,
            "frame_timestamp": 0,
        },
        "aspect_ratio": "9:16",
        "output": {"dir": "outputs/test-mc", "final_filename": "final.mp4"},
    }


# ── B-roll template tests ──────────────────────────────────────────────────


class TestBrollTemplate:
    def test_step_count(self, broll_spec_3_shots):
        dag = _dag(broll,broll_spec_3_shots)
        # 3 image_gen + 3 video_gen + tts + music + merge + mix = 10
        assert len(dag.steps) == 10

    def test_each_video_gen_depends_on_its_image_gen(self, broll_spec_3_shots):
        dag = _dag(broll,broll_spec_3_shots)
        for i in range(1, 4):
            vid_step = dag.get_step(f"video_gen_shot_{i}")
            assert vid_step.depends_on == [f"image_gen_shot_{i}"]

    def test_merge_depends_on_all_video_gen(self, broll_spec_3_shots):
        dag = _dag(broll,broll_spec_3_shots)
        merge = dag.get_step("merge_videos")
        expected = [f"video_gen_shot_{i}" for i in range(1, 4)]
        assert merge.depends_on == expected

    def test_mix_audio_depends_on_merge_tts_music(self, broll_spec_3_shots):
        dag = _dag(broll,broll_spec_3_shots)
        mix = dag.get_step("mix_audio")
        assert set(mix.depends_on) == {"merge_videos", "tts", "music"}

    def test_tts_has_no_dependencies(self, broll_spec_3_shots):
        dag = _dag(broll,broll_spec_3_shots)
        tts = dag.get_step("tts")
        assert tts.depends_on == []

    def test_music_has_no_dependencies(self, broll_spec_3_shots):
        dag = _dag(broll,broll_spec_3_shots)
        music = dag.get_step("music")
        assert music.depends_on == []

    def test_adapter_names_from_spec(self, broll_spec_3_shots):
        dag = _dag(broll,broll_spec_3_shots)
        assert dag.get_step("image_gen_shot_1").adapter_name == "test_image_adapter"
        assert dag.get_step("video_gen_shot_1").adapter_name == "test_video_adapter"
        assert dag.get_step("tts").adapter_name == "test_tts_adapter"
        assert dag.get_step("music").adapter_name == "test_music_adapter"
        assert dag.get_step("merge_videos").adapter_name == "ffmpeg_concat"
        assert dag.get_step("mix_audio").adapter_name == "ffmpeg_mix_audio"


# ── Talking head template tests ─────────────────────────────────────────────


class TestTalkingHeadTemplate:
    def test_step_count(self, talking_head_spec_3_shots):
        dag = _dag(talking_head,talking_head_spec_3_shots)
        # 1 anchor + 3 video_gen + 3 extract_last_frame + merge = 8
        assert len(dag.steps) == 8

    def test_shots_are_sequential_via_extract(self, talking_head_spec_3_shots):
        """Each shot depends on the previous shot's extract_last_frame, not the raw video."""
        dag = _dag(talking_head,talking_head_spec_3_shots)
        shot1 = dag.get_step("video_gen.shot_1")
        shot2 = dag.get_step("video_gen.shot_2")
        shot3 = dag.get_step("video_gen.shot_3")
        assert shot1.depends_on == ["image_gen.anchor"]
        assert shot2.depends_on == ["extract_last_frame.shot_1"]
        assert shot3.depends_on == ["extract_last_frame.shot_2"]

    def test_merge_depends_on_all_video_gen(self, talking_head_spec_3_shots):
        dag = _dag(talking_head,talking_head_spec_3_shots)
        merge = dag.get_step("merge_videos")
        expected = ["video_gen.shot_1", "video_gen.shot_2", "video_gen.shot_3"]
        assert merge.depends_on == expected

    def test_no_tts_or_music_steps(self, talking_head_spec_3_shots):
        dag = _dag(talking_head,talking_head_spec_3_shots)
        step_ids = list(dag.steps.keys())
        assert "tts" not in step_ids
        assert "music" not in step_ids

    def test_frame_chaining_start_frame_from(self, talking_head_spec_3_shots):
        """Frame chaining goes through extract_last_frame nodes for pipeline JSON compat."""
        dag = _dag(talking_head,talking_head_spec_3_shots)
        shot1 = dag.get_step("video_gen.shot_1")
        shot2 = dag.get_step("video_gen.shot_2")
        shot3 = dag.get_step("video_gen.shot_3")
        assert shot1.config["start_frame_from"] == "image_gen.anchor"
        assert shot2.config["start_frame_from"] == "extract_last_frame.shot_1"
        assert shot3.config["start_frame_from"] == "extract_last_frame.shot_2"

    def test_extract_last_frame_steps_exist(self, talking_head_spec_3_shots):
        """Each shot gets an extract_last_frame step for debugging frame chaining."""
        dag = _dag(talking_head,talking_head_spec_3_shots)
        for i in range(1, 4):
            step = dag.get_step(f"extract_last_frame.shot_{i}")
            assert step.adapter_name == "ffmpeg_extract_last_frame"
            assert step.config["video_from"] == f"video_gen.shot_{i}"
            assert step.config["output_filename"] == f"shot_{i}_last_frame.png"
            assert step.depends_on == [f"video_gen.shot_{i}"]

    def test_extract_last_frame_is_in_critical_path(self, talking_head_spec_3_shots):
        """Extract steps are in the critical path — next shot depends on the extracted frame."""
        dag = _dag(talking_head,talking_head_spec_3_shots)
        shot2 = dag.get_step("video_gen.shot_2")
        assert shot2.depends_on == ["extract_last_frame.shot_1"]

    def test_build_anchor_shot_preserves_creative_fields(self, talking_head_spec_3_shots):
        anchor = talking_head._build_anchor_shot(
            talking_head_spec_3_shots["shots"][0],
            talking_head_spec_3_shots["character"],
        )
        # Character integration is handled by prompt_builder via spec.character,
        # not by _build_anchor_shot. Verify shot fields are preserved.
        assert "a cozy living room" in anchor["scene"]
        assert "medium close-up" in anchor["camera"]
        # Action is overridden for still anchor frame
        assert "looking directly into front camera" in anchor["action"]


# ── Slideshow template tests ────────────────────────────────────────────────


class TestSlideshowTemplate:
    def test_step_count(self, slideshow_spec_4_slides):
        dag = _dag(slideshow,slideshow_spec_4_slides)
        # 4 pil_render + music + assemble = 6
        assert len(dag.steps) == 6

    def test_all_pil_render_have_no_dependencies(self, slideshow_spec_4_slides):
        dag = _dag(slideshow,slideshow_spec_4_slides)
        for i in range(1, 5):
            step = dag.get_step(f"pil_render.slide_{i}")
            assert step.depends_on == []

    def test_assemble_depends_on_all_pil_render_and_music(self, slideshow_spec_4_slides):
        dag = _dag(slideshow,slideshow_spec_4_slides)
        assemble = dag.get_step("assemble_slideshow")
        expected = [f"pil_render.slide_{i}" for i in range(1, 5)] + ["music"]
        assert assemble.depends_on == expected

    def test_music_duration_hint_is_sum_of_slide_durations(self, slideshow_spec_4_slides):
        dag = _dag(slideshow,slideshow_spec_4_slides)
        music = dag.get_step("music")
        # 3 + 4 + 5 + 3 = 15s = 15000ms
        assert music.config["music_length_ms"] == 15000


# ── Motion control template tests ───────────────────────────────────────────


class TestMotionControlTemplate:
    def test_step_count(self, motion_control_spec):
        dag = _dag(motion_control,motion_control_spec)
        assert len(dag.steps) == 4

    def test_linear_dependency_chain(self, motion_control_spec):
        dag = _dag(motion_control,motion_control_spec)
        dl = dag.get_step("download_clip")
        ext = dag.get_step("extract_frame")
        img = dag.get_step("image_gen.character_frame")
        vid = dag.get_step("video_gen.motion_control")

        assert dl.depends_on == []
        assert ext.depends_on == ["download_clip"]
        assert img.depends_on == ["extract_frame"]
        assert vid.depends_on == ["image_gen.character_frame"]

    def test_video_gen_has_motion_reference_and_start_frame(self, motion_control_spec):
        dag = _dag(motion_control,motion_control_spec)
        vid = dag.get_step("video_gen.motion_control")
        assert vid.config["motion_reference_from"] == "download_clip"
        assert vid.config["start_frame_from"] == "image_gen.character_frame"


# ── Talking head: single-shot optimization ─────────────────────────────────


class TestTalkingHeadSingleShot:
    @pytest.fixture
    def single_shot_spec(self):
        return {
            "video_type": "talking_head",
            "models": {
                "image_gen": {"adapter": "test_image_adapter"},
                "image_upscale": {"adapter": ""},
                "video_gen": {"adapter": "test_video_adapter"},
                "upscale": {"adapter": ""},
                "ffmpeg": {"adapter": "test_ffmpeg_adapter"},
            },
            "character": {"name": "Kelly", "description": "Young woman"},
            "shots": [
                {
                    "scene": "modern kitchen, morning light",
                    "subject": "Kelly, young woman",
                    "action": "talks excitedly to camera, gestures with hands",
                    "camera": "medium close-up, selfie angle",
                    "lighting": "bright morning light through window",
                    "color_grade": "warm, slightly overexposed",
                    "style": "phone camera UGC",
                    "dialogue": "[excited] Check this out!",
                    "duration": 8,
                    "video_prompt": "SCENE: Kelly talks excitedly in a modern kitchen.",
                },
            ],
            "aspect_ratio": "9:16",
            "output": {"dir": "outputs/test-single", "final_filename": "final.mp4"},
        }

    def test_single_shot_no_merge_step(self, single_shot_spec):
        dag = _dag(talking_head,single_shot_spec)
        assert "merge_videos" not in dag.steps

    def test_single_shot_step_count(self, single_shot_spec):
        dag = _dag(talking_head,single_shot_spec)
        # 1 anchor + 1 video_gen + 1 extract_last_frame = 3 (no merge, no de_ai by default)
        assert len(dag.steps) == 3

    def test_single_shot_output_filename_is_final(self, single_shot_spec):
        dag = _dag(talking_head,single_shot_spec)
        shot = dag.get_step("video_gen.shot_1")
        assert shot.config["output_filename"] == "final.mp4"


# ── Talking head: prop in anchor prompt ────────────────────────────────────


class TestTalkingHeadProp:
    def test_anchor_shot_includes_prop(self):
        character = {"name": "Kelly", "description": "Young woman with curly hair"}
        first_shot = {"scene": "modern kitchen", "subject": "Kelly"}
        prop = {
            "description": "iPhone showing a wellness app",
            "held_by": "in right hand, screen facing camera",
        }
        anchor = talking_head._build_anchor_shot(first_shot, character, prop)
        assert "iPhone showing a wellness app" in anchor["props"]
        assert "in right hand, screen facing camera" in anchor["props"]

    def test_anchor_shot_no_prop(self):
        character = {"name": "Kelly", "description": "Young woman"}
        first_shot = {"scene": "kitchen", "subject": "Kelly"}
        anchor = talking_head._build_anchor_shot(first_shot, character)
        assert not anchor.get("props", "")

    def test_build_dag_passes_prop_to_anchor(self):
        spec = {
            "video_type": "talking_head",
            "models": {
                "image_gen": {"adapter": "test"},
                "video_gen": {"adapter": "test"},
            },
            "character": {"name": "Kelly", "description": "Young woman"},
            "prop": {
                "description": "phone with a wellness app",
                "held_by": "in left hand",
            },
            "shots": [{"scene": "room", "subject": "Kelly", "action": "talks", "camera": "medium close-up", "lighting": "warm daylight", "color_grade": "warm filmic", "style": "phone camera UGC", "duration": 5, "video_prompt": "SCENE: Kelly talks in room."}],
            "output": {"dir": "out", "final_filename": "final.mp4"},
        }
        dag = _dag(talking_head,spec)
        anchor = dag.get_step("image_gen.anchor")
        # Prop should be in the nano_banana_spec's prompt object
        nano_spec = anchor.config.get("nano_banana_spec", {})
        prompt_obj = nano_spec.get("prompt", {})
        # Check that prop text appears somewhere in the spec
        spec_text = str(prompt_obj)
        assert "phone with a wellness app" in spec_text
        assert "in left hand" in spec_text


# ── Behavior tests: character reference photos wiring ─────────────────────


class TestTalkingHeadCharacterRefWiring:
    """Verify character reference_photos reach video gen step configs."""

    @pytest.fixture
    def th_spec_with_refs(self):
        return {
            "video_type": "talking_head",
            "models": {
                "image_gen": {"adapter": "test_image_adapter"},
                "video_gen": {"adapter": "fal_kling_v3"},
                "upscale": {"adapter": ""},
            },
            "character": {
                "name": "Guy",
                "description": "Mid-twenties male, brown hair",
                "reference_photos": ["/tmp/frontal.png", "/tmp/side.png"],
            },
            "shots": [
                {
                    "scene": "coffee shop",
                    "subject": "Guy, mid-twenties male",
                    "action": "talks to camera",
                    "camera": "medium close-up",
                    "lighting": "warm daylight",
                    "color_grade": "warm filmic",
                    "style": "phone camera UGC",
                    "dialogue": "[friendly] Hey!",
                    "duration": 5,
                    "video_prompt": "SCENE: Guy talks at coffee shop.",
                },
            ],
            "aspect_ratio": "9:16",
            "output": {"dir": "outputs/test", "final_filename": "final.mp4"},
        }

    def test_elements_in_video_config(self, th_spec_with_refs):
        dag = _dag(talking_head,th_spec_with_refs)
        shot = dag.get_step("video_gen.shot_1")
        assert "elements" in shot.config
        assert shot.config["elements"][0]["frontal_image_path"] == "/tmp/frontal.png"
        assert shot.config["elements"][0]["reference_image_paths"] == ["/tmp/side.png"]

    def test_no_refs_uses_anchor_frame_as_fallback(self):
        """Without reference_photos, the anchor frame auto-becomes the reference on supported adapters."""
        spec = {
            "video_type": "talking_head",
            "models": {
                "image_gen": {"adapter": "test_image_adapter"},
                "image_upscale": {"adapter": ""},
                "video_gen": {"adapter": "fal_kling_v3"},
                "upscale": {"adapter": ""},
            },
            "character": {
                "name": "Guy",
                "description": "Mid-twenties male",
            },
            "shots": [
                {
                    "scene": "coffee shop",
                    "subject": "Guy",
                    "action": "talks",
                    "camera": "medium close-up",
                    "lighting": "warm daylight",
                    "color_grade": "warm filmic",
                    "style": "phone camera UGC",
                    "dialogue": "[friendly] Hey!",
                    "duration": 5,
                    "video_prompt": "SCENE: Guy talks.",
                },
            ],
            "aspect_ratio": "9:16",
            "output": {"dir": "outputs/test", "final_filename": "final.mp4"},
        }
        dag = _dag(talking_head,spec)
        shot = dag.get_step("video_gen.shot_1")
        # Kling v3 supports refs — template emits a _from ref, engine resolves at runtime
        assert shot.config["character_ref_frame_from"] == "image_gen.anchor"

    def test_no_refs_no_elements_on_unsupported_adapter(self):
        """Without reference_photos, unsupported adapters get no elements."""
        spec = {
            "video_type": "talking_head",
            "models": {
                "image_gen": {"adapter": "test_image_adapter"},
                "video_gen": {"adapter": "fal_veo_v3_flf"},
                "upscale": {"adapter": ""},
            },
            "character": {
                "name": "Guy",
                "description": "Mid-twenties male",
            },
            "shots": [
                {
                    "scene": "coffee shop",
                    "subject": "Guy",
                    "action": "talks",
                    "camera": "medium close-up",
                    "lighting": "warm daylight",
                    "color_grade": "warm filmic",
                    "style": "phone camera UGC",
                    "dialogue": "[friendly] Hey!",
                    "duration": 5,
                    "video_prompt": "SCENE: Guy talks.",
                },
            ],
            "aspect_ratio": "9:16",
            "output": {"dir": "outputs/test", "final_filename": "final.mp4"},
        }
        dag = _dag(talking_head,spec)
        shot = dag.get_step("video_gen.shot_1")
        assert "elements" not in shot.config


class TestBrollCharacterRefWiring:
    """Verify character reference_photos reach broll video gen configs."""

    def test_elements_in_broll_video_config(self):
        spec = {
            "video_type": "broll",
            "models": {
                "image_gen": {"adapter": "test_image_adapter"},
                "video_gen": {"adapter": "fal_kling_v3"},
                "upscale": {"adapter": ""},
                "tts": {"adapter": "test_tts"},
                "music": {"adapter": "test_music"},
            },
            "character": {
                "name": "Guy",
                "description": "Mid-twenties male",
                "reference_photos": ["/tmp/frontal.png", "/tmp/side.png"],
            },
            "shots": [
                {
                    "shot_id": "shot_1",
                    "scene": "park bench",
                    "subject": "Guy",
                    "action": "sits",
                    "lighting": "golden hour",
                    "camera": "wide shot, 24mm",
                    "color_grade": "warm",
                    "style": "cinematic 35mm",
                    "video_prompt": "SCENE: Guy sits on park bench.",
                },
            ],
            "narration": {"script": "Hello world", "voice_description": "Warm female"},
            "music": {"mood": "calm"},
            "output": {"dir": "outputs/test", "final_filename": "final.mp4"},
        }
        dag = _dag(broll,spec)
        shot = dag.get_step("video_gen_shot_1")
        assert "elements" in shot.config
        assert shot.config["elements"][0]["frontal_image_path"] == "/tmp/frontal.png"


class TestBehaviorCreativeFieldsReachAdapterConfig:
    """Verify creative fields from shots propagate to adapter configs."""

    def test_lighting_reaches_nano_banana_spec(self):
        spec = {
            "video_type": "broll",
            "models": {
                "image_gen": {"adapter": "test"},
                "video_gen": {"adapter": "test"},
                "upscale": {"adapter": ""},
                "tts": {"adapter": "test"},
                "music": {"adapter": "test"},
            },
            "shots": [
                {
                    "shot_id": "shot_1",
                    "scene": "gym",
                    "subject": "woman",
                    "action": "stretching",
                    "lighting": "overhead fluorescent gym lighting",
                    "camera": "wide shot, 24mm, deep focus",
                    "color_grade": "cool desaturated",
                    "style": "documentary handheld",
                    "video_prompt": "SCENE: test",
                },
            ],
            "narration": {"script": "Hello world", "voice_description": "Warm female"},
            "music": {"mood": "energetic"},
            "output": {"dir": "out", "final_filename": "final.mp4"},
        }
        dag = _dag(broll,spec)
        image_step = dag.get_step("image_gen_shot_1")
        nano_spec = image_step.config.get("nano_banana_spec", {})
        prompt = nano_spec.get("prompt", {})
        # The specific lighting from the shot must appear, not a default
        assert "overhead fluorescent gym lighting" == prompt.get("lighting")
        assert "cool desaturated" == prompt.get("color_and_grading")
        assert "documentary handheld" in prompt.get("overall_style", "")
        assert "24mm" in prompt.get("camera_and_framing", "")


# ── Compile tests (pipeline JSON output) ───────────────────────────────────


class TestBrollCompile:
    def test_compile_returns_pipeline_json(self, broll_spec_3_shots):
        pipeline = broll.compile(broll_spec_3_shots)
        assert pipeline["pipeline_version"] == 1
        assert isinstance(pipeline["nodes"], list)
        assert len(pipeline["nodes"]) > 0

    def test_compile_round_trips_through_dag(self, broll_spec_3_shots):
        """compile() → DAG.from_json() → to_json() produces equivalent pipeline."""
        from workflow.dag import DAG
        pipeline = broll.compile(broll_spec_3_shots)
        dag = DAG.from_json(pipeline)
        pipeline2 = dag.to_json()
        # Same nodes (order may differ, compare as sets)
        ids1 = {n["id"] for n in pipeline["nodes"]}
        ids2 = {n["id"] for n in pipeline2["nodes"]}
        assert ids1 == ids2

    def test_compile_uses_split_ffmpeg_adapters(self, broll_spec_3_shots):
        pipeline = broll.compile(broll_spec_3_shots)
        adapters = {n["adapter"] for n in pipeline["nodes"]}
        assert "ffmpeg_concat" in adapters
        assert "ffmpeg_mix_audio" in adapters
        # No raw local_ffmpeg with operation key
        for node in pipeline["nodes"]:
            assert "operation" not in node.get("config", {})

    def test_compile_preserves_from_refs(self, broll_spec_3_shots):
        """*_from references are preserved as data in compiled output."""
        pipeline = broll.compile(broll_spec_3_shots)
        # B-roll doesn't use *_from refs (uses direct paths), so just verify structure
        for node in pipeline["nodes"]:
            assert "id" in node
            assert "adapter" in node
            assert "config" in node
            assert "depends_on" in node


class TestTalkingHeadCompile:
    def test_compile_returns_pipeline_json(self, talking_head_spec_3_shots):
        pipeline = talking_head.compile(talking_head_spec_3_shots)
        assert pipeline["pipeline_version"] == 1
        assert len(pipeline["nodes"]) == 8  # anchor + 3 video + 3 extract + merge

    def test_compile_uses_split_ffmpeg_adapters(self, talking_head_spec_3_shots):
        pipeline = talking_head.compile(talking_head_spec_3_shots)
        adapters = {n["adapter"] for n in pipeline["nodes"]}
        assert "ffmpeg_extract_last_frame" in adapters
        assert "ffmpeg_concat" in adapters

    def test_compile_preserves_start_frame_from(self, talking_head_spec_3_shots):
        pipeline = talking_head.compile(talking_head_spec_3_shots)
        shot_nodes = [n for n in pipeline["nodes"] if n["id"].startswith("video_gen.shot")]
        assert shot_nodes[0]["config"]["start_frame_from"] == "image_gen.anchor"
        assert shot_nodes[1]["config"]["start_frame_from"] == "extract_last_frame.shot_1"


class TestSlideshowCompile:
    def test_compile_returns_pipeline_json(self, slideshow_spec_4_slides):
        pipeline = slideshow.compile(slideshow_spec_4_slides)
        assert pipeline["pipeline_version"] == 1
        assert len(pipeline["nodes"]) == 6

class TestMotionControlCompile:
    def test_compile_returns_pipeline_json(self, motion_control_spec):
        pipeline = motion_control.compile(motion_control_spec)
        assert pipeline["pipeline_version"] == 1
        assert len(pipeline["nodes"]) == 4

    def test_compile_preserves_from_refs(self, motion_control_spec):
        pipeline = motion_control.compile(motion_control_spec)
        vid_node = [n for n in pipeline["nodes"] if n["id"] == "video_gen.motion_control"][0]
        assert vid_node["config"]["start_frame_from"] == "image_gen.character_frame"
        assert vid_node["config"]["motion_reference_from"] == "download_clip"


# ── Unified video template tests ──────────────────────────────────────────


def _shot(shot_id, **overrides):
    """Helper to build a minimal shot dict for video template tests."""
    base = {
        "shot_id": shot_id,
        "scene": f"scene for {shot_id}",
        "subject": f"subject in {shot_id}",
        "action": f"action in {shot_id}",
        "lighting": "warm daylight",
        "camera": "medium shot, 50mm",
        "color_grade": "warm filmic",
        "style": "phone camera UGC",
        "video_prompt": f"SCENE: test prompt for {shot_id}",
        "duration": 8,
    }
    base.update(overrides)
    return base


@pytest.fixture
def video_spec_3_shots():
    """3 independent shots, no audio overlay."""
    return {
        "video_type": "video",
        "run_name": "test-video",
        "version": "1",
        "models": {
            "image_gen": {"adapter": "test_image_adapter"},
            "video_gen": {"adapter": "test_video_adapter"},
            "upscale": {"adapter": ""},
        },
        "shots": [_shot("confession"), _shot("cityscape"), _shot("reaction")],
        "output": {"dir": "outputs/runs/test-video", "final_filename": "final.mp4"},
    }


@pytest.fixture
def video_spec_with_audio():
    """3 shots with narration + music overlay."""
    return {
        "video_type": "video",
        "run_name": "test-video-audio",
        "version": "1",
        "models": {
            "image_gen": {"adapter": "test_image_adapter"},
            "video_gen": {"adapter": "test_video_adapter"},
            "upscale": {"adapter": ""},
            "tts": {"adapter": "test_tts_adapter"},
            "music": {"adapter": "test_music_adapter"},
        },
        "shots": [_shot("hook"), _shot("build"), _shot("resolve")],
        "narration": {"script": "Here's the story...", "voice_description": "Warm female narrator"},
        "music": {"mood": "contemplative"},
        "output": {"dir": "outputs/runs/test-video-audio", "final_filename": "final.mp4"},
    }


@pytest.fixture
def video_spec_chained():
    """Shot 2 chains from shot 1, shot 3 is independent."""
    return {
        "video_type": "video",
        "run_name": "test-video-chain",
        "version": "1",
        "models": {
            "image_gen": {"adapter": "test_image_adapter"},
            "video_gen": {"adapter": "test_video_adapter"},
            "upscale": {"adapter": ""},
        },
        "shots": [
            _shot("opener"),
            _shot("continuation", chain_from="opener"),
            _shot("cutaway"),
        ],
        "output": {"dir": "outputs/runs/test-video-chain", "final_filename": "final.mp4"},
    }


class TestVideoTemplate:
    """Core tests for the unified video template."""

    def test_parallel_shots_step_count(self, video_spec_3_shots):
        """3 independent shots (no chain_from): 3 image_gen + 3 video_gen + merge = 7."""
        dag = _dag(video, video_spec_3_shots)
        assert len(dag.steps) == 7

    def test_all_image_gens_run_in_parallel(self, video_spec_3_shots):
        """All image_gen steps have no dependencies."""
        dag = _dag(video, video_spec_3_shots)
        for shot_id in ("confession", "cityscape", "reaction"):
            step = dag.get_step(f"image_gen_{shot_id}")
            assert step.depends_on == []

    def test_video_gen_depends_on_its_image_gen(self, video_spec_3_shots):
        dag = _dag(video, video_spec_3_shots)
        for shot_id in ("confession", "cityscape", "reaction"):
            vid = dag.get_step(f"video_gen_{shot_id}")
            assert vid.depends_on == [f"image_gen_{shot_id}"]

    def test_merge_depends_on_all_video_gen(self, video_spec_3_shots):
        dag = _dag(video, video_spec_3_shots)
        merge = dag.get_step("merge_videos")
        expected = ["video_gen_confession", "video_gen_cityscape", "video_gen_reaction"]
        assert merge.depends_on == expected

    def test_no_tts_or_music_without_audio(self, video_spec_3_shots):
        """Without narration/music in spec, no audio steps exist."""
        dag = _dag(video, video_spec_3_shots)
        step_ids = list(dag.steps.keys())
        assert "tts" not in step_ids
        assert "music" not in step_ids
        assert "mix_audio" not in step_ids

    def test_merge_output_is_final_without_audio(self, video_spec_3_shots):
        """Without audio layers, merge output is the final filename."""
        dag = _dag(video, video_spec_3_shots)
        merge = dag.get_step("merge_videos")
        assert merge.config["output_filename"] == "final.mp4"

    def test_native_audio_included_in_concat(self, video_spec_3_shots):
        """Concat includes native audio from clips."""
        dag = _dag(video, video_spec_3_shots)
        merge = dag.get_step("merge_videos")
        assert merge.config["include_audio"] is True

    def test_no_extract_last_frame_without_chain_from(self, video_spec_3_shots):
        """No extract_last_frame steps when no shot uses chain_from."""
        dag = _dag(video, video_spec_3_shots)
        for shot_id in ("confession", "cityscape", "reaction"):
            assert f"extract_last_frame_{shot_id}" not in dag.steps


class TestVideoTemplateWithAudio:
    """Tests for video template with narration and/or music."""

    def test_step_count_with_audio(self, video_spec_with_audio):
        """3 shots (no chain) + tts + music + merge + mix = 10."""
        dag = _dag(video, video_spec_with_audio)
        # 3 image_gen + 3 video_gen + tts + music + merge + mix = 10
        assert len(dag.steps) == 10

    def test_tts_has_no_dependencies(self, video_spec_with_audio):
        dag = _dag(video, video_spec_with_audio)
        tts = dag.get_step("tts")
        assert tts.depends_on == []

    def test_music_has_no_dependencies(self, video_spec_with_audio):
        dag = _dag(video, video_spec_with_audio)
        music = dag.get_step("music")
        assert music.depends_on == []

    def test_mix_audio_depends_on_merge_tts_music(self, video_spec_with_audio):
        dag = _dag(video, video_spec_with_audio)
        mix = dag.get_step("mix_audio")
        assert set(mix.depends_on) == {"merge_videos", "tts", "music"}

    def test_merge_output_is_merged_with_audio(self, video_spec_with_audio):
        """With audio layers, merge outputs merged.mp4, mix_audio outputs final.mp4."""
        dag = _dag(video, video_spec_with_audio)
        merge = dag.get_step("merge_videos")
        assert merge.config["output_filename"] == "merged.mp4"
        mix = dag.get_step("mix_audio")
        assert mix.config["output_filename"] == "final.mp4"

    def test_narration_only_no_music(self):
        """Spec with narration but no music — mix_audio still exists, no music_from."""
        spec = {
            "video_type": "video",
            "run_name": "test",
            "version": "1",
            "models": {
                "image_gen": {"adapter": "test"},
                "video_gen": {"adapter": "test"},
                "upscale": {"adapter": ""},
                "tts": {"adapter": "test_tts"},
            },
            "shots": [_shot("s1"), _shot("s2")],
            "narration": {"script": "Hello", "voice_description": "Warm female"},
            "output": {"dir": "out", "final_filename": "final.mp4"},
        }
        dag = _dag(video, spec)
        assert "tts" in dag.steps
        assert "music" not in dag.steps
        mix = dag.get_step("mix_audio")
        assert "narration_from" in mix.config
        assert "music_from" not in mix.config

    def test_music_only_no_narration(self):
        """Spec with music but no narration — mix_audio has music_from only."""
        spec = {
            "video_type": "video",
            "run_name": "test",
            "version": "1",
            "models": {
                "image_gen": {"adapter": "test"},
                "video_gen": {"adapter": "test"},
                "upscale": {"adapter": ""},
                "music": {"adapter": "test_music"},
            },
            "shots": [_shot("s1"), _shot("s2")],
            "music": {"mood": "calm"},
            "output": {"dir": "out", "final_filename": "final.mp4"},
        }
        dag = _dag(video, spec)
        assert "music" in dag.steps
        assert "tts" not in dag.steps
        mix = dag.get_step("mix_audio")
        assert "music_from" in mix.config
        assert "narration_from" not in mix.config


class TestVideoTemplateChaining:
    """Tests for frame chaining between shots."""

    def test_chained_shot_skips_image_gen(self, video_spec_chained):
        """Shot with chain_from has no image_gen step."""
        dag = _dag(video, video_spec_chained)
        assert "image_gen_continuation" not in dag.steps

    def test_chained_shot_depends_on_extract_last_frame(self, video_spec_chained):
        dag = _dag(video, video_spec_chained)
        cont = dag.get_step("video_gen_continuation")
        assert cont.depends_on == ["extract_last_frame_opener"]

    def test_independent_shot_still_parallel(self, video_spec_chained):
        """The cutaway shot is independent — image_gen has no deps."""
        dag = _dag(video, video_spec_chained)
        img = dag.get_step("image_gen_cutaway")
        assert img.depends_on == []

    def test_chained_step_count(self, video_spec_chained):
        """2 image_gen + 3 video_gen + 1 extract (opener only) + merge = 7."""
        dag = _dag(video, video_spec_chained)
        assert len(dag.steps) == 7

    def test_invalid_chain_from_raises(self):
        """chain_from referencing a non-existent shot raises ValueError."""
        spec = {
            "video_type": "video",
            "run_name": "test",
            "version": "1",
            "models": {
                "image_gen": {"adapter": "test"},
                "video_gen": {"adapter": "test"},
            },
            "shots": [_shot("s1", chain_from="nonexistent")],
            "output": {"dir": "out", "final_filename": "final.mp4"},
        }
        with pytest.raises(ValueError, match="chain_from='nonexistent'"):
            video.compile(spec)


class TestVideoTemplateSingleShot:
    """Single shot optimizations."""

    def test_single_shot_no_audio_no_merge(self):
        """Single shot, no audio — output filename set directly on video_gen."""
        spec = {
            "video_type": "video",
            "run_name": "test",
            "version": "1",
            "models": {
                "image_gen": {"adapter": "test"},
                "video_gen": {"adapter": "test"},
                "upscale": {"adapter": ""},
            },
            "shots": [_shot("solo")],
            "output": {"dir": "out", "final_filename": "final.mp4"},
        }
        dag = _dag(video, spec)
        assert "merge_videos" not in dag.steps
        assert "mix_audio" not in dag.steps
        vid = dag.get_step("video_gen_solo")
        assert vid.config["output_filename"] == "final.mp4"

    def test_single_shot_with_audio_skips_merge(self):
        """Single shot with audio — skip concat, go straight to mix_audio."""
        spec = {
            "video_type": "video",
            "run_name": "test",
            "version": "1",
            "models": {
                "image_gen": {"adapter": "test"},
                "video_gen": {"adapter": "test"},
                "upscale": {"adapter": ""},
                "music": {"adapter": "test_music"},
            },
            "shots": [_shot("solo")],
            "music": {"mood": "calm"},
            "output": {"dir": "out", "final_filename": "final.mp4"},
        }
        dag = _dag(video, spec)
        assert "merge_videos" not in dag.steps
        mix = dag.get_step("mix_audio")
        assert mix.config["video_from"] == "video_gen_solo"
        assert mix.config["output_filename"] == "final.mp4"
