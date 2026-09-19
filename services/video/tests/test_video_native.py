"""Offline contract/budget/identity tests plus real, tiny FFmpeg renditions."""
from contextlib import contextmanager
import asyncio
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from narma_video import video_native as video


def overview(**changes):
    return {"focus_nickname": "papa_prima", "focus_player_confirmed": True,
        "identity_evidence": "В интерфейсе над выбранным героем виден ник papa_prima.",
        "hud_readable": True, "candidates": [], "uncertainty": ["Выборочный просмотр."], **changes}


def episode(**changes):
    return video.Episode(episode_id="e01", start_seconds=100.0, end_seconds=130.0,
        categories=["support"], selection="regular", question="Проверь видимую помощь союзнику.", **changes)


def observations(**changes):
    return {"episode_id": "e01", "focus_nickname": "papa_prima", "focus_player_confirmed": True,
        "identity_evidence": "Ник указан над выбранным героем.", "hud_readable": True,
        "observations": [{"clip_seconds": 12.5, "category": "support", "observation": "Игрок перемещается рядом с союзником.", "confidence": "medium"}],
        "uncertainty": ["События между кадрами не проверены."], **changes}


def usage(**changes):
    return {"total_input_tokens": 100, "total_output_tokens": 20, "total_thought_tokens": 5,
        "total_tokens": 125, "total_tool_use_tokens": 0,
        "input_tokens_by_modality": [{"modality": "video", "tokens": 80}, {"modality": "text", "tokens": 20}], **changes}


def provider_response(output, **changes):
    return {"model": video.MODEL, "status": "completed", "service_tier": "standard", "usage": usage(),
        "steps": [{"type": "thought"}, {"type": "model_output", "content": [{"type": "text", "text": json.dumps(output)}]}], **changes}


@pytest.fixture
def fake_rendition(monkeypatch, tmp_path):
    calls = []
    @contextmanager
    def render(source, metadata, start, end, *, overview=False):
        target = tmp_path / "temporary-sample.mp4"
        target.write_bytes(b"synthetic-video-for-mocked-provider")
        calls.append((start, end, overview))
        try:
            yield target
        finally:
            target.unlink()
    monkeypatch.setattr(video, "render_rendition", render)
    return calls


@pytest.mark.parametrize("position", [1, 2, 3, 4, 5, None])
def test_regular_plan_uses_role_and_survives_no_death_candidates(position):
    planned = video.plan_episodes(overview(), 2400, position)
    assert len(planned) == 4
    assert sum(e.end_seconds - e.start_seconds for e in planned) == 120
    assert all(e.selection == "regular" and e.question == video.ROLE_QUESTIONS[position] for e in planned)
    assert "support" in planned[1].categories if position in (4, 5) else "economy" in planned[1].categories
    assert "низкий" in video.ROLE_QUESTIONS[5].lower()


def test_candidate_context_overlap_dedup_and_total_cap():
    candidates = [{"video_seconds": float(t), "category": "death", "reason": "Проверь эпизод.", "confidence": "high"}
        for t in [192, 193, 194, 300, 350, 600, 700, 800, 900, 1000, 1300, 1400, 1500, 1600, 1700, 1800, 2000, 2050, 2150, 2250, 2300, 2350, 2380, 2395]]
    planned = video.plan_episodes(overview(candidates=candidates), 2400, 5)
    assert len(planned) <= 10
    assert sum(e.end_seconds - e.start_seconds for e in planned) <= 300
    assert all(a.end_seconds < b.start_seconds for a, b in zip(planned, planned[1:]))
    merged = next(e for e in planned if e.start_seconds <= 192 < e.end_seconds)
    assert merged.start_seconds == 182 and merged.end_seconds >= 214 and merged.selection == "mixed"
    assert "lane" in merged.categories and "death" in merged.categories
    assert all(e.end_seconds - e.start_seconds <= 90 for e in planned)


def test_unknown_player_only_regular_identity_recovery_and_no_model_findings():
    value = overview(focus_player_confirmed=False, identity_evidence="", hud_readable=False)
    planned = video.plan_episodes(value, 2400, 4)
    assert len(planned) == 4 and all(e.selection == "regular" for e in planned)
    value["candidates"] = [{"video_seconds": 20.0, "category": "death", "reason": "x", "confidence": "high"}]
    with pytest.raises(ValueError, match="PLAYER_UNCONFIRMED"):
        video.plan_episodes(value, 2400, 4)


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), True, "2400", 7201])
def test_invalid_duration_prevents_planning(duration):
    with pytest.raises(ValueError, match="DURATION"):
        video.plan_episodes(overview(), duration, 1)


@pytest.mark.parametrize("position", [0, 6, "5", True, 3.0])
def test_position_must_be_explicit_valid_int(position):
    with pytest.raises(ValueError, match="POSITION"):
        video.plan_episodes(overview(), 2400, position)


def test_short_source_bounds_and_low_confidence_hints_not_used():
    value = overview(candidates=[{"video_seconds": 0.5, "category": "death", "reason": "Неразборчиво.", "confidence": "low"}])
    planned = video.plan_episodes(value, 1.0, 5)
    assert len(planned) == 1 and planned[0].start_seconds == 0 and planned[0].end_seconds == 1
    assert "death" not in planned[0].categories


def test_boundary_time_and_unknown_identity_fail_closed():
    value = overview(candidates=[{"video_seconds": 100.0, "category": "lane", "reason": "x", "confidence": "high"}])
    with pytest.raises(ValueError, match="OUTSIDE_SOURCE"):
        video.validate_overview(value, "papa_prima", 100)
    with pytest.raises(ValueError, match="FOCUS_MISMATCH"):
        video.validate_overview(overview(focus_nickname="another_player"), "papa_prima", 100)
    with pytest.raises(ValueError, match="IDENTITY_EVIDENCE"):
        video.validate_overview(overview(identity_evidence="  "), "papa_prima", 100)


def test_clip_timestamp_conversion_uses_server_offset():
    result = video.validate_episode(observations(), "papa_prima", episode())
    assert result.observations[0].video_seconds == 112.5
    assert result.observations[0].observation_id == "e01-o01"
    with pytest.raises(ValueError, match="OUTSIDE_CLIP"):
        video.validate_episode(observations(observations=[{"clip_seconds": 30.0, "category": "support", "observation": "x", "confidence": "low"}]), "papa_prima", episode())
    with pytest.raises(ValueError, match="FOCUS_OR_EPISODE"):
        video.validate_episode(observations(episode_id="e02"), "papa_prima", episode())
    with pytest.raises(ValueError, match="UNCONFIRMED"):
        video.validate_episode(observations(focus_player_confirmed=False, identity_evidence=""), "papa_prima", episode())


def test_non_readable_hud_does_not_force_fabricated_observations():
    result = video.validate_episode(observations(focus_player_confirmed=False, identity_evidence="", hud_readable=False, observations=[]), "papa_prima", episode())
    assert result.observations == [] and result.hud_readable is False


def test_stateless_native_request_contract_and_usage(fake_rendition):
    requests = []
    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert str(request.url) == video.ENDPOINT
        assert request.headers["x-goog-api-key"] == "test-key"
        return httpx.Response(200, json=provider_response(overview()))
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(transport))
    result = client.analyze_overview(Path("source.mp4"), "papa_prima", "Dazzle", 5, {"duration_seconds": 2400})
    assert result.focus_nickname == "papa_prima"
    assert client.last_usage == usage() and client.request_started
    assert len(requests) == 1 and requests[0]["store"] is False
    assert requests[0]["tools"] == [] and requests[0]["generation_config"]["tool_choice"] == "none"
    assert "previous_interaction_id" not in requests[0]
    content = requests[0]["input"][1]
    assert content["type"] == "video" and content["processing"] == {"type": "static", "fps": 0.2}
    assert content["resolution"] == "low" and "uri" not in content
    assert fake_rendition == [(0.0, 2400.0, True)]


def test_detail_high_resolution_and_exact_identity(fake_rendition):
    def transport(request):
        body = json.loads(request.content)
        context = json.loads(body["input"][0]["text"])
        assert context["clock"] == "clip_seconds_starting_at_zero"
        assert context["focus_nickname"] == "papa_prima" and context["user_provided_position"] == 5
        assert body["input"][1]["resolution"] == "high"
        assert body["input"][1]["processing"]["fps"] == 2
        return httpx.Response(200, json=provider_response(observations()))
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(transport))
    result = client.analyze_episode(Path("source.mp4"), "papa_prima", "Dazzle", 5, {"duration_seconds": 2400}, episode())
    assert result.observations[0].video_seconds == 112.5
    assert fake_rendition == [(100.0, 130.0, False)]


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_errors_never_retry_or_redirect(status, fake_rendition):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://other.invalid"})
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(transport))
    with pytest.raises(ValueError, match=f"HTTP_{status}"):
        client.analyze_overview(Path("source.mp4"), "papa_prima", metadata={"duration_seconds": 2400})
    assert len(calls) == 1 and client.request_started and client.last_usage is None


@pytest.mark.parametrize("changed", [
    {"status": "incomplete"}, {"model": "different"}, {"service_tier": "priority"},
    {"steps": [{"type": "processing_call"}]}, {"steps": [{"type": "function_call"}]},
    {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "not json"}]}]},
])
def test_usage_retained_when_output_or_processing_invalid(changed, fake_rendition):
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=provider_response(overview(), **changed))))
    with pytest.raises(ValueError):
        client.analyze_overview(Path("source.mp4"), "papa_prima", metadata={"duration_seconds": 2400})
    assert client.last_usage == usage()


@pytest.mark.parametrize("changed", [
    {"total_tokens": 999}, {"total_input_tokens": True}, {"unknown_cost": 1},
    {"total_tool_use_tokens": 1}, {"total_cached_tokens": 101},
    {"input_tokens_by_modality": [{"modality": "audio", "tokens": 10}]},
])
def test_unsupported_usage_does_not_disappear(changed, fake_rendition):
    raw_usage = usage(**changed)
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=provider_response(overview(), usage=raw_usage))))
    with pytest.raises(ValueError, match="USAGE_UNSUPPORTED"):
        client.analyze_overview(Path("source.mp4"), "papa_prima", metadata={"duration_seconds": 2400})
    assert client.last_usage == {"unrecognized_interaction_usage": raw_usage}


@pytest.mark.parametrize("nickname", ["", "   ", "other\nplayer", "x" * 129, None])
def test_invalid_identity_prevents_media_or_dispatch(nickname, fake_rendition):
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(lambda request: pytest.fail("must not dispatch")))
    with pytest.raises(ValueError, match="NICKNAME"):
        client.analyze_overview(Path("source.mp4"), nickname, metadata={"duration_seconds": 2400})
    assert not client.request_started and not fake_rendition


def test_profile_nickname_length_128_accepted_by_request_and_both_result_schemas(fake_rendition):
    nickname = "n" * 128
    received = []
    def transport(request):
        body = json.loads(request.content)
        context = json.loads(body["input"][0]["text"])
        received.append(context["focus_nickname"])
        value = overview(focus_nickname=nickname) if context["phase"] == "overview" else observations(focus_nickname=nickname)
        return httpx.Response(200, json=provider_response(value))
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(transport))
    summary = client.analyze_overview(Path("source.mp4"), nickname, metadata={"duration_seconds": 2400})
    detail = client.analyze_episode(Path("source.mp4"), nickname, metadata={"duration_seconds": 2400}, episode=episode())
    assert summary.focus_nickname == detail.focus_nickname == nickname
    assert received == [nickname, nickname]
    for schema, value in ((video.OverviewResult, overview(focus_nickname="n" * 129)),
            (video.ClipResult, observations(focus_nickname="n" * 129)),
            (video.EpisodeResult, {**detail.model_dump(), "focus_nickname": "n" * 129})):
        with pytest.raises(ValueError):
            schema.model_validate(value)


def test_worker_result_guard_revalidates_mutated_or_fake_provider_objects():
    summary = video.OverviewResult.model_validate(overview())
    summary.focus_nickname = "different"
    with pytest.raises(ValueError, match="FOCUS_MISMATCH"):
        video.validate_overview(summary, "papa_prima", 2400)
    detail = video.validate_episode(observations(), "papa_prima", episode())
    assert video.validate_episode_result(detail, "papa_prima", episode()) == detail
    detail.observations[0].video_seconds = 130.0
    with pytest.raises(ValueError, match="OUTSIDE_CLIP"):
        video.validate_episode_result(detail, "papa_prima", episode())
    detail = video.validate_episode(observations(), "papa_prima", episode())
    detail.focus_player_confirmed = False
    with pytest.raises(ValueError, match="UNCONFIRMED"):
        video.validate_episode_result(detail, "papa_prima", episode())


def test_before_request_runs_after_media_preparation_and_before_dispatch(fake_rendition):
    order = []
    client = None
    def guard():
        assert fake_rendition == [(0.0, 2400.0, True)]
        assert client.request_started is False and client.last_usage is None
        order.append("guard")
    def transport(request):
        assert client.request_started is True and order == ["guard"]
        order.append("dispatch")
        return httpx.Response(200, json=provider_response(overview()))
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(transport), before_request=guard)
    client.analyze_overview(Path("source.mp4"), "papa_prima", metadata={"duration_seconds": 2400})
    assert order == ["guard", "dispatch"]


def test_before_request_lease_rejection_stays_unsubmitted(fake_rendition, tmp_path):
    def guard():
        raise ValueError("VIDEO_LEASE_EXPIRED")
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(lambda request: pytest.fail("must not dispatch")))
    client.before_request = guard
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        client.analyze_overview(Path("source.mp4"), "papa_prima", metadata={"duration_seconds": 2400})
    assert client.request_started is False and client.last_usage is None
    assert not (tmp_path / "temporary-sample.mp4").exists()


def test_request_wallclock_deadline_cancels_and_retains_unknown_attempt(fake_rendition, monkeypatch):
    attempts = []
    async def transport(request):
        attempts.append(request)
        await asyncio.sleep(1)
        return httpx.Response(200, json=provider_response(overview()))
    monkeypatch.setattr(video, "REQUEST_TIMEOUT_SECONDS", 0.02)
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(transport))
    with pytest.raises(ValueError, match="REQUEST_TIMEOUT"):
        client.analyze_overview(Path("source.mp4"), "papa_prima", metadata={"duration_seconds": 2400})
    assert len(attempts) == 1 and client.request_started is True and client.last_usage is None


def test_planning_cost_includes_all_detail_responses_and_no_audio():
    estimate = video.estimate_video_budget(2400)
    assert estimate["overview_frames"] == 480 and estimate["detail_frames_cap"] == 600
    assert estimate["provider_calls_cap"] == 11 and estimate["output_tokens_cap"] == 11 * 4096
    assert estimate["audio_included"] is False and estimate["coverage"] == "sampled"


def test_failed_next_preflight_cannot_reuse_previous_billing_metadata(fake_rendition):
    client = video.GeminiVideo(api_key="test-key", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=provider_response(overview()))))
    client.analyze_overview(Path("source.mp4"), "papa_prima", metadata={"duration_seconds": 2400})
    assert client.last_usage
    with pytest.raises(ValueError):
        client.analyze_episode(Path("source.mp4"), "papa_prima", metadata={"duration_seconds": 2400}, episode={})
    assert client.last_usage is None and client.request_started is False


def test_local_media_process_stderr_is_bounded_before_dispatch():
    with pytest.raises(ValueError, match="MEDIA_OUTPUT_LIMIT"):
        video._run_media([sys.executable, "-c", "import sys;sys.stderr.write('x'*100000)"], timeout=5)


def test_local_media_process_timeout_kills_process():
    with pytest.raises(ValueError, match="MEDIA_TIMEOUT"):
        video._run_media([sys.executable, "-c", "import time;time.sleep(10)"], timeout=0.02)


@pytest.fixture
def real_clip(tmp_path):
    path = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=10:duration=12",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-threads", "1", "-c:a", "aac", str(path)],
        check=True, timeout=30)
    return path


@pytest.mark.parametrize("overview_mode", [True, False])
def test_real_rendition_silent_capped_and_cleaned(real_clip, overview_mode):
    metadata = video.probe_native(real_clip)
    start = 0 if overview_mode else 3
    with video.render_rendition(real_clip, metadata, start, 12, overview=overview_mode) as rendered:
        path = rendered
        streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(rendered)],
            check=True, capture_output=True, timeout=10).stdout)["streams"]
        assert len(streams) == 1 and streams[0]["codec_type"] == "video"
        assert streams[0]["avg_frame_rate"] == ("1/5" if overview_mode else "2/1")
        assert rendered.stat().st_size <= video.MAX_INLINE_BYTES
        assert rendered.stat().st_mode & 0o777 == 0o600
    assert not path.exists() and real_clip.exists()


def test_corrupt_or_url_sources_fail_before_provider(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="PROBE"):
        video.probe_native(bad)
    with pytest.raises(ValueError, match="SOURCE"):
        video.probe_native("https://localhost/file.mp4")


def test_inline_size_failure_is_local_and_cleans_output(real_clip, monkeypatch):
    monkeypatch.setattr(video, "MAX_INLINE_BYTES", 100)
    with pytest.raises(ValueError, match="INLINE_SIZE"):
        with video.render_rendition(real_clip, video.probe_native(real_clip), 0, 12, overview=True):
            pytest.fail("oversize media must not leave the local worker")


def test_sub_sampling_period_source_still_has_one_overview_frame(real_clip):
    metadata = video.probe_native(real_clip)
    metadata["duration_seconds"] = 1.0
    with video.render_rendition(real_clip, metadata, 0, 1, overview=True) as rendered:
        # A single 0.2 FPS frame lasts five seconds. Provider context/validator
        # still bound candidate offsets to the actual one second recording.
        assert video.probe_native(rendered)["duration_seconds"] == 5.0


def test_nonzero_source_pts_not_added_to_recording_duration_or_clip_clock(tmp_path):
    source = tmp_path / "offset.mkv"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=red:size=160x96:rate=10:duration=6",
        "-f", "lavfi", "-i", "color=blue:size=160x96:rate=10:duration=6", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,setpts=PTS+20/TB[v]",
        "-map", "[v]", "-fps_mode", "passthrough", "-c:v", "ffv1", "-threads", "1", str(source)], check=True, timeout=30)
    metadata = video.probe_native(source)
    assert metadata["duration_seconds"] == 12 and metadata["first_pts_seconds"] == 20
    with video.render_rendition(source, metadata, 3, 9) as rendered:
        assert video.probe_native(rendered)["duration_seconds"] == 6
        for clip_time, expected_channel in ((0, 0), (4, 2)):
            frame = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(clip_time), "-i", str(rendered), "-frames:v", "1",
                "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], check=True, capture_output=True, timeout=10).stdout
            assert len(frame) == 3 and frame[expected_channel] > 200
