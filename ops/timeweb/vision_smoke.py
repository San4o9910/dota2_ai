"""Exactly one Gemini call on four small synthetic frames; no user video."""
import io
import json
import os
import sys
from PIL import Image
from narma_video.gemini import GeminiVision


def main():
    os.environ["GEMINI_MODEL"] = "gemini-3.8-flash"
    frames = []
    for index, color in enumerate(["red", "blue", "green", "yellow"]):
        stream = io.BytesIO()
        Image.new("RGB", (96,96), color).save(stream, format="JPEG", quality=94)
        frames.append({"frame_id":index, "pts":index, "time_base":"1/30",
            "video_seconds":index/30, "image":stream.getvalue()})
    vision = GeminiVision()
    result = vision.analyze(frames, "__synthetic_pipeline_test__")
    if result.focus_player_visible or result.findings:
        raise ValueError("SYNTHETIC_FRAMES_MUST_NOT_INVENT_A_DOTA_PLAYER")
    usage = {}
    for field in ("total_input_tokens", "total_output_tokens", "total_thought_tokens", "total_tokens"):
        value = getattr(vision.last_usage, field, None)
        if type(value) is int and value >= 0:
            usage[field] = value
    print(json.dumps({"event":"gemini_vision_smoke_passed", "model":vision.model,
        "provider_requests":1, "frames_sent":4,
        "reviewed_frame_ids":result.reviewed_frame_ids,
        "invented_player":False, "usage":usage,
        "quality_scope":"synthetic_transport_and_grounding_only_not_dota_coaching"}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        code = getattr(error, "status_code", None)
        print(json.dumps({"event":"gemini_vision_smoke_failed", "http_status":code if type(code) is int else None}), flush=True)
        sys.exit(1)
