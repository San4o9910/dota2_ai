"""Decode every source frame; retain its original PTS. No FPS resampling."""
import hashlib
import io
import json
import math
import os
import select
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path

from PIL import Image
from .config import MAX_DURATION, MAX_FRAMES

def probe(path: Path):
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as diagnostic:
        process = subprocess.Popen(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm",
            "-select_streams", "v:0", "-show_frames", "-show_streams", "-show_entries",
            "stream=width,height,time_base:frame=pts,width,height", "-of", "json", str(path)], stdout=output, stderr=diagnostic, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 180
        try:
            while process.poll() is None:
                if time.monotonic() > deadline or output.tell() > 128*1024**2 or diagnostic.tell() > 1024**2:
                    raise ValueError("VIDEO_PROBE_LIMIT")
                time.sleep(0.05)
            if process.returncode or diagnostic.tell() or output.tell() > 128*1024**2:
                raise ValueError("VIDEO_PROBE_FAILED")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        output.seek(0); metadata = json.load(output)
    streams = metadata.get("streams", []); frames = metadata.get("frames", [])
    if len(streams) != 1 or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError("VIDEO_FRAME_LIMIT")
    width, height = streams[0]["width"], streams[0]["height"]
    if width < 16 or height < 16 or width * height > 3840 * 2160:
        raise ValueError("VIDEO_RESOLUTION_LIMIT")
    time_base = Fraction(streams[0]["time_base"])
    if time_base <= 0:
        raise ValueError("VIDEO_TIMESTAMPS_INVALID")
    timestamps = []
    for frame in frames:
        if frame.get("width") != width or frame.get("height") != height or "pts" not in frame:
            raise ValueError("VIDEO_FRAME_FORMAT_CHANGED")
        timestamps.append(int(frame["pts"]))
    if any(b < a for a,b in zip(timestamps,timestamps[1:])):
        raise ValueError("VIDEO_TIMESTAMPS_INVALID")
    duration = float((timestamps[-1] - timestamps[0]) * time_base)
    if not math.isfinite(duration) or duration > MAX_DURATION:
        raise ValueError("VIDEO_DURATION_LIMIT")
    return {"width": width, "height": height, "time_base": time_base, "timestamps": timestamps,
            "frame_count": len(timestamps), "duration_seconds": duration, "first_pts_seconds": float(timestamps[0]*time_base)}

def decode(path: Path, metadata):
    width, height = metadata["width"], metadata["height"]
    with tempfile.TemporaryFile() as diagnostic:
        process = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "2", "-copyts", "-noautorotate",
            "-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm", "-i", str(path),
            "-map", "0:v:0", "-an", "-sn", "-dn", "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=diagnostic)
        try:
            frame_size = width*height*3
            for frame_id, pts in enumerate(metadata["timestamps"]):
                if diagnostic.tell() > 1024**2:
                    raise ValueError("VIDEO_DECODE_FAILED")
                raw = bytearray()
                while len(raw) < frame_size:
                    if not select.select([process.stdout],[],[],120)[0]:
                        raise ValueError("VIDEO_DECODE_TIMEOUT")
                    piece = os.read(process.stdout.fileno(), min(1024*1024, frame_size-len(raw)))
                    if not piece:
                        raise ValueError("VIDEO_FRAME_COUNT_MISMATCH")
                    raw.extend(piece)
                with Image.frombytes('RGB',(width,height),bytes(raw)) as pixels, io.BytesIO() as encoded:
                    pixels.save(encoded,format='JPEG',quality=94,subsampling=0)
                    image=encoded.getvalue()
                if len(image) > 8*1024**2:
                    raise ValueError("VIDEO_FRAME_TOO_LARGE")
                yield {"frame_id":frame_id, "pts":pts, "time_base":str(metadata["time_base"]),
                    "pts_seconds":float(pts*metadata["time_base"]), "video_seconds":float((pts-metadata["timestamps"][0])*metadata["time_base"]),
                    "sha256":hashlib.sha256(image).hexdigest(), "image":image}
            if not select.select([process.stdout],[],[],30)[0]:
                raise ValueError("VIDEO_DECODE_TIMEOUT")
            if os.read(process.stdout.fileno(),1):
                raise ValueError("VIDEO_FRAME_COUNT_MISMATCH")
            if process.wait(timeout=30) or diagnostic.tell():
                raise ValueError("VIDEO_DECODE_FAILED")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()

def batches(frames, after_frame=-1, max_frames=16, max_bytes=12*1024**2):
    current=[]; size=0
    for frame in frames:
        if frame["frame_id"] <= after_frame:
            continue
        # Bound base64 plus text/schema overhead below the API's 20 MB limit.
        encoded_size = (len(frame["image"])+2)//3*4
        if encoded_size > max_bytes:
            raise ValueError("VIDEO_FRAME_TOO_LARGE")
        if current and (len(current)>=max_frames or size+encoded_size>max_bytes):
            yield current; current=[]; size=0
        current.append(frame); size += encoded_size
    if current:
        yield current
