import struct

from bluetooth import ditoo_commands as cmd
from bluetooth.protocol import ACK, FrameParser, build_frame


def test_matches_captured_alarm_off_packet():
    # Packet logged while talking to a real Ditoo Pro, andreas-mausch README.
    payload = bytes([0x00, 0x00, 13, 37, 0x00, 0x00, 0x00, 0x00, 0x00, 100])
    assert build_frame(0x43, payload).hex() == "010d004300000d25000000000064e60002"


def test_brightness_frame():
    assert cmd.set_brightness(50) == bytes([0x01, 0x04, 0x00, 0x74, 50, 0xAA, 0x00, 0x02])
    assert cmd.set_brightness(500)[4] == 100


def reply_frame(command: int, data: bytes = b"") -> bytes:
    return build_frame(0x04, bytes([command, ACK]) + data)


def test_parser_reads_reply_split_across_reads_and_skips_garbage():
    stream = b"\xff\x00" + reply_frame(0x09, b"\x0a") + reply_frame(0x74)
    parser = FrameParser()
    frames = parser.feed(stream[:5]) + parser.feed(stream[5:])
    replies = [f.as_reply() for f in frames]
    assert [(r.command, r.ack, r.data) for r in replies] == [(0x09, True, b"\x0a"), (0x74, True, b"")]


def test_parser_drops_corrupted_frame():
    bad = bytearray(reply_frame(0x09, b"\x0a"))
    bad[-3] ^= 0xFF  # break checksum
    frames = FrameParser().feed(bytes(bad) + reply_frame(0x74))
    assert [f.as_reply().command for f in frames] == [0x74]


def test_animation_chunking():
    data = bytes(range(256)) * 3 + b"xyz"  # 771 bytes -> 4 chunks
    frames = cmd.send_animation(data)
    assert len(frames) == 5
    parsed = FrameParser().feed(b"".join(frames))
    assert all(f.command == 0x8B for f in parsed)
    assert parsed[0].payload == struct.pack("<BI", 0, len(data))
    rebuilt = b""
    for i, f in enumerate(parsed[1:]):
        control, size, index = struct.unpack_from("<BIH", f.payload)
        assert (control, size, index) == (1, len(data), i)
        rebuilt += f.payload[7:]
    assert rebuilt == data
