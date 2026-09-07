"""Synthetic regression fixtures; no user replay or full roster is committed."""

import os
import tempfile
import unittest
from pathlib import Path

from narma_video.replay_metadata import (
    MAX_DECODED,
    MAX_PACKED,
    PlayerSelectionError,
    ReplayMetadataError,
    decode_snappy,
    parse_demo_file_info,
    parse_demo_metadata,
    read_demo_metadata_ranges,
    resolve_player,
)


def varint(value):
    result = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        result.append(byte | (128 if value else 0))
        if not value:
            return bytes(result)


def integer(field, value):
    return varint(field * 8) + varint(value)


def message(field, value):
    return varint(field * 8 + 2) + varint(len(value)) + value


def metadata_fixture(compressed=True, mutate=None):
    players = [dict(nickname=f"Player_{i}", account_id=1000 + i, team=2 if i < 5 else 3) for i in range(10)]
    if mutate:
        mutate(players)
    dota = integer(1, 8963624400)
    for player in players:
        dota += message(4, b"".join([
            message(1, b"npc_dota_hero_necrolyte"),
            message(2, player["nickname"].encode()),
            integer(3, 0),
            integer(4, 0 if player["account_id"] is None else 76561197960265728 + player["account_id"]),
            integer(5, player["team"]),
        ]))
    info = message(4, message(4, dota))
    packed = varint(len(info)) + bytes([244]) + (len(info) - 1).to_bytes(2, "little") + info if compressed else info
    prefix = b"PBDEMS2\0" + (64).to_bytes(4, "little") + bytes(52)
    return prefix + varint(66 if compressed else 2) + varint(152653) + varint(len(packed)) + packed, info


class ReplayMetadataTests(unittest.TestCase):
    def read(self, data):
        return read_demo_metadata_ranges(len(data), lambda offset, length: data[offset:offset + length])

    def test_bounded_three_reads_and_integer_precision(self):
        for compressed in (True, False):
            data, _ = metadata_fixture(compressed, lambda rows: rows[0].update(account_id=3000000001, nickname="Игрок"))
            calls = []

            def reader(offset, length):
                calls.append((offset, length))
                return data[offset:offset + length]

            result = read_demo_metadata_ranges(len(data), reader)
            self.assertEqual(result["match_id"], "8963624400")
            self.assertEqual(result["players"][0]["account_id"], 3000000001)
            self.assertEqual(result["players"][0]["nickname"], "Игрок")
            self.assertEqual(result["players"][5]["side"], "dire")
            self.assertTrue(all("player_slot" not in player for player in result["players"]))
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0], (0, 16))
            self.assertTrue(all(length < 1024 for _, length in calls))

    def test_snappy_overlap_all_copy_encodings_and_rejections(self):
        for encoded, expected in [("0908414243160300", b"ABCABCABC"), ("0500410101", b"AAAAA"), ("0500410f01000000", b"AAAAA")]:
            self.assertEqual(decode_snappy(bytes.fromhex(encoded)), expected)
        for encoded in ("0500410100", "0500410102", "05004101", "020041", "0108414243", "000041"):
            with self.assertRaises(ReplayMetadataError):
                decode_snappy(bytes.fromhex(encoded))
        with self.assertRaises(ReplayMetadataError):
            decode_snappy(varint(MAX_DECODED + 1))
        with self.assertRaises(ReplayMetadataError):
            decode_snappy(bytes(MAX_PACKED + 1))

    def test_invalid_header_offset_command_and_truncation(self):
        data, _ = metadata_fixture()
        invalid = [bytes(8) + data[8:], data[:8] + bytes(4) + data[12:],
                   data[:8] + (len(data) + 1).to_bytes(4, "little") + data[12:],
                   data[:64] + b"\x03" + data[65:], data[:-1]]
        for item in invalid:
            with self.assertRaises(ReplayMetadataError):
                self.read(item)
        with self.assertRaises(ReplayMetadataError):
            read_demo_metadata_ranges(len(data), lambda *_: b"")
        with self.assertRaises(ReplayMetadataError):
            self.read(data[:64] + varint(2) + varint(10) + varint(MAX_PACKED + 1))

    def test_bad_varints_and_unsupported_protobuf_fields(self):
        for data in (b"\x80" * 10, b"\xff" * 9 + b"\x02", b"\x00", b"\x23"):
            with self.assertRaises(ReplayMetadataError):
                parse_demo_file_info(data)

    def test_malformed_roster_and_duplicate_singular_fields(self):
        for change in (lambda rows: rows[1].update(account_id=rows[0]["account_id"]),
                       lambda rows: rows[0].update(team=3),
                       lambda rows: rows[0].update(nickname="\0")):
            with self.assertRaises(ReplayMetadataError):
                parse_demo_file_info(metadata_fixture(mutate=change)[1])
        _, info = metadata_fixture()
        for invalid in (info + info, info + b"\x25\0\0\0\0", info.replace(b"Player_0", b"\xfflayer_0")):
            with self.assertRaises(ReplayMetadataError):
                parse_demo_file_info(invalid)

    def test_file_round_trip_and_missing_file(self):
        data, _ = metadata_fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.dem"
            path.write_bytes(data)
            self.assertEqual(parse_demo_metadata(path), self.read(data))
            with self.assertRaises(ReplayMetadataError):
                parse_demo_metadata(path.with_suffix(".missing"))

    def test_resolve_one_player_by_exact_normalized_nickname(self):
        data, _ = metadata_fixture(mutate=lambda rows: rows[0].update(nickname="Équipe"))
        metadata = self.read(data)
        selected = resolve_player(metadata, " E\u0301QUIPE ")
        self.assertEqual(selected["account_id"], 1000)
        self.assertNotIn("players", selected)
        selected["nickname"] = "Changed"
        self.assertEqual(metadata["players"][0]["nickname"], "Équipe")
        for nickname in ("équi", "", "X\0"):
            with self.assertRaises(PlayerSelectionError):
                resolve_player(metadata, nickname)

    def test_duplicate_nickname_unavailable_id_and_immutable_binding(self):
        for change, code in [(lambda rows: rows[1].update(nickname="PLAYER_0"), "DOTA_PLAYER_AMBIGUOUS"),
                             (lambda rows: rows[0].update(account_id=None), "DOTA_IDENTITY_UNAVAILABLE")]:
            metadata = self.read(metadata_fixture(mutate=change)[0])
            with self.assertRaises(PlayerSelectionError) as caught:
                resolve_player(metadata, "Player_0")
            self.assertEqual(caught.exception.code, code)
        metadata = self.read(metadata_fixture()[0])
        self.assertEqual(resolve_player(metadata, "Player_0", 1000)["account_id"], 1000)
        with self.assertRaises(PlayerSelectionError) as caught:
            resolve_player(metadata, "Player_1", 1000)
        self.assertEqual(caught.exception.code, "DOTA_PROFILE_LOCKED")

    @unittest.skipUnless(os.environ.get("NARMA_TEST_DEM_PATH"), "Optional local user replay not distributed with tests")
    def test_actual_user_replay_metadata(self):
        metadata = parse_demo_metadata(os.environ["NARMA_TEST_DEM_PATH"])
        self.assertEqual(metadata["match_id"], "8984479726")
        selected = resolve_player(metadata, "papa_prima")
        self.assertEqual(selected["account_id"], 435842051)
        self.assertEqual(len(metadata["players"]), 10)


if __name__ == "__main__":
    unittest.main()
