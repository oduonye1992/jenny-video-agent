"""Test derive_from in the video template — compile specs and print pipeline JSON."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow.templates.video import compile


def make_shot(shot_id, video_prompt="Test prompt for video generation that is long enough to pass validation checks for the adapter.", **kwargs):
    """Helper to build a minimal shot dict."""
    base = {
        "shot_id": shot_id,
        "video_prompt": video_prompt,
        "scene": "Dark stage with single spotlight",
        "subject": "Woman seated on interview chair",
        "action": "Speaking directly to camera",
        "lighting": "Warm spotlight from above, soft fill from left",
        "camera": "Close-up, 50mm, shallow DOF",
        "color_grade": "Warm filmic, slight grain",
        "style": "Phone camera UGC, naturalistic",
    }
    base.update(kwargs)
    return base


# ── Flow 1: One anchor, derive variations ────────────────────────────────

spec_flow1 = {
    "video_type": "video",
    "profile": "cheap",
    "aspect_ratio": "9:16",
    "character": {
        "name": "Rachel",
        "description": "28-year-old woman, olive skin, dark hair in low bun, sage green linen blouse",
    },
    "shots": [
        make_shot("the_pattern", duration=7),
        make_shot("the_spiral", derive_from="the_pattern", duration=8,
                  image_prompt="Same woman, pull back to medium shot showing torso and hands, frustrated expression, hands mid-gesture"),
        make_shot("the_search", derive_from="the_pattern", duration=8,
                  image_prompt="Same woman, close-up tighter on face, eyes glistening, looking slightly down"),
        make_shot("the_turn", derive_from="the_pattern", duration=7,
                  image_prompt="Same woman, medium shot, slight smile breaking through, shoulders relaxed, hands open on lap"),
    ],
    "models": {},
    "output": {"final_filename": "final.mp4"},
}

# ── Flow 2: Fully independent shots ─────────────────────────────────────

spec_flow2 = {
    "video_type": "video",
    "profile": "cheap",
    "aspect_ratio": "9:16",
    "character": {
        "name": "Rachel",
        "description": "28-year-old woman, olive skin, dark hair in low bun",
    },
    "shots": [
        make_shot("dark_stage", duration=7,
                  reference_image="/tmp/ref_stage.png"),
        make_shot("coffee_shop", duration=8,
                  scene="Bright coffee shop, morning light through window",
                  reference_image="/tmp/ref_coffee.png"),
        make_shot("car_selfie", duration=8,
                  scene="Car interior, dashboard glow, nighttime",
                  reference_image="/tmp/ref_car.png"),
    ],
    "models": {},
    "output": {"final_filename": "final.mp4"},
}

# ── Flow 3: Mixed — two anchors with derivatives ────────────────────────

spec_mixed = {
    "video_type": "video",
    "profile": "cheap",
    "aspect_ratio": "9:16",
    "character": {
        "name": "Rachel",
        "description": "28-year-old woman, olive skin, dark hair in low bun",
    },
    "shots": [
        make_shot("stage_close", duration=7),
        make_shot("stage_medium", derive_from="stage_close", duration=8,
                  image_prompt="Same woman, pull back to medium shot, hands visible, relaxed posture"),
        make_shot("coffee_wide", duration=8,
                  scene="Bright coffee shop, morning light",
                  reference_image="/tmp/ref_coffee.png"),
        make_shot("coffee_close", derive_from="coffee_wide", duration=7,
                  image_prompt="Same woman, tight close-up on face, warm smile, coffee cup near chin"),
    ],
    "models": {},
    "output": {"final_filename": "final.mp4"},
}


# ── Flow 4: start_frame anchor + derive_from (the Rachel flow) ───────

spec_start_frame = {
    "video_type": "video",
    "profile": "cheap",
    "aspect_ratio": "9:16",
    "character": {
        "name": "Rachel",
        "description": "28-year-old woman, olive skin, dark hair in low bun, sage green linen blouse",
    },
    "shots": [
        make_shot("the_pattern", duration=7,
                  start_frame="/outputs/concepts/rachel/frames/anchor.png"),
        make_shot("the_spiral", derive_from="the_pattern", duration=8,
                  image_prompt="Same woman, pull back to medium shot showing torso and hands, frustrated expression, hands mid-gesture"),
        make_shot("the_search", derive_from="the_pattern", duration=8,
                  image_prompt="Same woman, close-up tighter on face, eyes glistening, looking slightly down"),
        make_shot("the_turn", derive_from="the_pattern", duration=7,
                  image_prompt="Same woman, medium shot, slight smile breaking through, shoulders relaxed, hands open on lap"),
    ],
    "models": {},
    "output": {"final_filename": "final.mp4"},
}

# ── Flow 5: start_frame only (all frames pre-generated) ─────────────

spec_all_pregenerated = {
    "video_type": "video",
    "profile": "cheap",
    "aspect_ratio": "9:16",
    "character": {
        "name": "Rachel",
        "description": "28-year-old woman",
    },
    "shots": [
        make_shot("shot_1", duration=7, start_frame="/outputs/frames/shot_1.png"),
        make_shot("shot_2", duration=8, start_frame="/outputs/frames/shot_2.png"),
        make_shot("shot_3", duration=8, start_frame="/outputs/frames/shot_3.png"),
    ],
    "models": {},
    "output": {"final_filename": "final.mp4"},
}


def print_pipeline(name, spec):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    pipeline = compile(spec)
    print(json.dumps(pipeline, indent=2))

    # Print dependency summary
    print(f"\n  DAG Summary:")
    for node in pipeline["nodes"]:
        deps = node["depends_on"]
        dep_str = f" (depends on: {', '.join(deps)})" if deps else " (no deps — parallel)"
        print(f"    {node['id']}: {node['adapter']}{dep_str}")


if __name__ == "__main__":
    print_pipeline("Flow 1: One anchor + derive_from variations", spec_flow1)
    print_pipeline("Flow 2: Fully independent shots", spec_flow2)
    print_pipeline("Flow 3: Mixed — two anchors with derivatives", spec_mixed)
    print_pipeline("Flow 4: start_frame anchor + derive_from (Rachel)", spec_start_frame)
    print_pipeline("Flow 5: All frames pre-generated", spec_all_pregenerated)
