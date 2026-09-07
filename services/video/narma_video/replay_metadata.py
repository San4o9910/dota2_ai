"""Read bounded Source 2 CDemoFileInfo metadata without a network service.

Only roster identity is exposed. The footer cannot establish gameplay events,
player slots, camera state, or proof that an uploader owns a Steam account.
Callers must authorize uploads and persist a single selected player atomically.
"""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

MAX_PACKED = 256 * 1024
MAX_DECODED = 1024 * 1024
MAX_FIELDS = 4096
STEAM_ACCOUNT_BASE = 76561197960265728


class ReplayMetadataError(ValueError):
    code = "DOTA_REPLAY_METADATA_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("Invalid Source 2 replay metadata")


class PlayerSelectionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DemoPlayer(TypedDict):
    nickname: str
    account_id: int | None
    hero_name: str
    side: str


class DemoMetadata(TypedDict):
    match_id: str
    players: list[DemoPlayer]


class _Cursor:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0

    def uint(self, maximum: int = (1 << 64) - 1) -> int:
        value = 0
        for index in range(10):
            if self.at >= len(self.data):
                raise ReplayMetadataError()
            byte = self.data[self.at]
            self.at += 1
            if index == 9 and byte > 1:
                raise ReplayMetadataError()
            value |= (byte & 127) << (7 * index)
            if not byte & 128:
                if value > maximum:
                    raise ReplayMetadataError()
                return value
        raise ReplayMetadataError()

    def take(self, count: int) -> bytes:
        if count < 0 or self.at + count > len(self.data):
            raise ReplayMetadataError()
        value = self.data[self.at : self.at + count]
        self.at += count
        return value


def decode_snappy(data: bytes) -> bytes:
    """Decode a raw Snappy block with a strict 1 MiB output ceiling."""
    if len(data) > MAX_PACKED:
        raise ReplayMetadataError()
    cursor = _Cursor(data)
    expected = cursor.uint(MAX_DECODED)
    output = bytearray(expected)
    written = 0
    while cursor.at < len(data):
        tag = cursor.take(1)[0]
        kind = tag & 3
        if kind == 0:
            code = tag >> 2
            length = code + 1 if code < 60 else int.from_bytes(cursor.take(code - 59), "little") + 1
            if written + length > expected:
                raise ReplayMetadataError()
            output[written : written + length] = cursor.take(length)
            written += length
        else:
            length = 4 + ((tag >> 2) & 7) if kind == 1 else 1 + (tag >> 2)
            offset = (((tag & 224) << 3) + cursor.take(1)[0] if kind == 1
                      else int.from_bytes(cursor.take(2 if kind == 2 else 4), "little"))
            if offset == 0 or offset > written or written + length > expected:
                raise ReplayMetadataError()
            # Snappy copies can overlap; slice copying does not implement this.
            for _ in range(length):
                output[written] = output[written - offset]
                written += 1
    if written != expected:
        raise ReplayMetadataError()
    return bytes(output)


def _fields(data: bytes) -> list[tuple[int, int, int | bytes]]:
    if len(data) > MAX_DECODED:
        raise ReplayMetadataError()
    cursor = _Cursor(data)
    rows: list[tuple[int, int, int | bytes]] = []
    while cursor.at < len(data):
        if len(rows) >= MAX_FIELDS:
            raise ReplayMetadataError()
        key = cursor.uint(0xFFFFFFFF)
        wire, number = key & 7, key // 8
        if number == 0:
            raise ReplayMetadataError()
        if wire == 0:
            value: int | bytes = cursor.uint()
        elif wire == 2:
            value = cursor.take(cursor.uint(MAX_DECODED))
        elif wire in (1, 5):
            value = cursor.take(8 if wire == 1 else 4)
        else:
            raise ReplayMetadataError()
        rows.append((number, wire, value))
    return rows


def _one(rows: list[tuple[int, int, int | bytes]], number: int) -> int | bytes | None:
    values = [row for row in rows if row[0] == number]
    if len(values) > 1 or (values and values[0][1] not in (0, 2)):
        raise ReplayMetadataError()
    return values[0][2] if values else None


def _message(value: int | bytes | None) -> bytes:
    if not isinstance(value, bytes):
        raise ReplayMetadataError()
    return value


def _integer(value: int | bytes | None, fallback: int | None = None) -> int:
    if value is None and fallback is not None:
        return fallback
    if type(value) is not int:
        raise ReplayMetadataError()
    return value


def _string(value: int | bytes | None) -> str:
    data = _message(value)
    if len(data) > 512:
        raise ReplayMetadataError()
    try:
        text = data.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ReplayMetadataError() from exc
    # Match the existing JavaScript schema's 128 UTF-16 code unit limit.
    if not text or len(text.encode("utf-16-le")) // 2 > 128 or re.search(r"[\x00-\x1f\x7f]", text):
        raise ReplayMetadataError()
    return text


def parse_demo_file_info(data: bytes) -> DemoMetadata:
    game = _fields(_message(_one(_fields(data), 4)))
    dota = _fields(_message(_one(game, 4)))
    match_id = str(_integer(_one(dota, 1)))
    if re.fullmatch(r"[1-9][0-9]{7,11}", match_id) is None:
        raise ReplayMetadataError()
    players: list[DemoPlayer] = []
    for number, wire, value in dota:
        if number != 4:
            continue
        if wire != 2:
            raise ReplayMetadataError()
        row = _fields(_message(value))
        fake = _integer(_one(row, 3), 0)
        if fake > 1:
            raise ReplayMetadataError()
        if fake:
            continue
        team = _integer(_one(row, 5))
        if team not in (2, 3):
            raise ReplayMetadataError()
        account_id = _integer(_one(row, 4), 0) - STEAM_ACCOUNT_BASE
        hero_name = _string(_one(row, 1))
        if re.fullmatch(r"npc_dota_hero_[a-z0-9_]+", hero_name) is None:
            raise ReplayMetadataError()
        players.append({
            "nickname": _string(_one(row, 2)),
            "account_id": account_id if 0 < account_id < 4294967295 else None,
            "hero_name": hero_name,
            "side": "radiant" if team == 2 else "dire",
        })
    if len(players) != 10 or sum(player["side"] == "radiant" for player in players) != 5:
        raise ReplayMetadataError()
    account_ids = [player["account_id"] for player in players if player["account_id"] is not None]
    if len(set(account_ids)) != len(account_ids):
        raise ReplayMetadataError()
    return {"match_id": match_id, "players": players}


def read_demo_metadata_ranges(size: int, read_range: Callable[[int, int], bytes]) -> DemoMetadata:
    """Read header and footer in exactly three bounded reads, never the replay."""
    if type(size) is not int or size < 20:
        raise ReplayMetadataError()

    def read(offset: int, length: int) -> bytes:
        if offset < 0 or length < 1 or offset + length > size or length > MAX_PACKED:
            raise ReplayMetadataError()
        data = read_range(offset, length)
        if not isinstance(data, bytes) or len(data) != length:
            raise ReplayMetadataError()
        return data

    header = read(0, 16)
    if header[:8] != b"PBDEMS2\x00":
        raise ReplayMetadataError()
    offset = int.from_bytes(header[8:12], "little")
    if offset < 16 or offset >= size:
        raise ReplayMetadataError()
    cursor = _Cursor(read(offset, min(30, size - offset)))
    command = cursor.uint(0xFFFFFFFF)
    cursor.uint(0xFFFFFFFF)  # Tick is framing, not an identity or player slot.
    length = cursor.uint(MAX_PACKED)
    if command not in (2, 66):
        raise ReplayMetadataError()
    packed = read(offset + cursor.at, length)
    return parse_demo_file_info(decode_snappy(packed) if command == 66 else packed)


def parse_demo_metadata(path: str | Path) -> DemoMetadata:
    """Parse an authorized immutable upload from disk; reject nonregular files."""
    try:
        with open(path, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ReplayMetadataError()

            def read(offset: int, length: int) -> bytes:
                handle.seek(offset)
                return handle.read(length)

            result = read_demo_metadata_ranges(before.st_size, read)
            after = os.fstat(handle.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns
            ):
                raise ReplayMetadataError()
            return result
    except OSError as exc:
        raise ReplayMetadataError() from exc


read_demo_metadata = parse_demo_metadata


def nickname_key(nickname: str) -> str:
    return unicodedata.normalize("NFC", nickname.strip()).lower()


def resolve_player(metadata: DemoMetadata, nickname: str, locked_account_id: int | None = None) -> DemoPlayer:
    """Resolve one exact normalized nickname, preserving an existing ID binding.

    Return only the selected identity. Binding itself must be enforced in the
    database transaction, since two uploads can race each other's first bind.
    """
    if not isinstance(nickname, str) or not nickname.strip() or len(nickname) > 128 or re.search(r"[\x00-\x1f\x7f]", nickname):
        raise PlayerSelectionError("DOTA_NICKNAME_INVALID")
    key = nickname_key(nickname)
    matches = [player for player in metadata["players"] if nickname_key(player["nickname"]) == key]
    if len(matches) > 1:
        raise PlayerSelectionError("DOTA_PLAYER_AMBIGUOUS")
    if not matches:
        raise PlayerSelectionError("DOTA_PLAYER_NOT_FOUND")
    selected = matches[0]
    if selected["account_id"] is None:
        raise PlayerSelectionError("DOTA_IDENTITY_UNAVAILABLE")
    if locked_account_id is not None and selected["account_id"] != locked_account_id:
        raise PlayerSelectionError("DOTA_PROFILE_LOCKED")
    return dict(selected)  # A caller cannot mutate the parsed roster through this value.
