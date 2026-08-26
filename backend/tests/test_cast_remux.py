import json

from app.routers.streaming import (
    _parse_cast_probe,
    _resolve_cast_audio_map,
    _build_cast_remux_cmd,
)


def _ffprobe(audio_langs, sub_codec=None, duration="60.0"):
    """Build a minimal ffprobe JSON dict for testing."""
    streams = []
    for i, lang in enumerate(audio_langs):
        streams.append({
            "index": i,
            "codec_type": "audio",
            "tags": {"language": lang},
        })
    if sub_codec:
        streams.append({
            "index": len(streams),
            "codec_type": "subtitle",
            "codec_name": sub_codec,
        })
    return {"streams": streams, "format": {"duration": duration}}


def test_parse_cast_probe_keeps_mov_text_subtitles():
    # Regression: MP4 stores every text subtitle as `mov_text`; an allowlist that
    # omitted it would drop subtitles on every MP4 cast. It must be kept.
    data = _ffprobe(["eng", "hin"], sub_codec="mov_text")
    probe = _parse_cast_probe(data)
    assert probe["has_text_subs"] is True
    assert probe["audio_count"] == 2
    assert probe["audio_langs"] == ["eng", "hin"]


def test_parse_cast_probe_keeps_ass_and_webvtt():
    for codec in ("ass", "ssa", "srt", "subrip", "webvtt", "text", "tx3g"):
        probe = _parse_cast_probe(_ffprobe(["eng"], sub_codec=codec))
        assert probe["has_text_subs"] is True, codec


def test_parse_cast_probe_skips_bitmap_subtitles():
    # Bitmap subs cannot be carried into MP4 via -c:s mov_text; they must be skipped
    # (not mapped) so they don't break the whole remux.
    for codec in ("hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle",
                  "dvb_teletext", "eia_608", "eia_708", "arib_caption"):
        probe = _parse_cast_probe(_ffprobe(["eng"], sub_codec=codec))
        assert probe["has_text_subs"] is False, codec


def test_resolve_audio_map_by_language():
    probe = {"audio_count": 2, "audio_langs": ["eng", "hin"]}
    assert _resolve_cast_audio_map(probe, None, "hin") == "0:a:1?"
    assert _resolve_cast_audio_map(probe, None, "en") == "0:a:0?"
    assert _resolve_cast_audio_map(probe, None, "english") == "0:a:0?"
    # matched by prefix: 'hi' matches 'hin'
    assert _resolve_cast_audio_map(probe, None, "hi") == "0:a:1?"


def test_resolve_audio_map_language_not_found_falls_back():
    probe = {"audio_count": 2, "audio_langs": ["eng", "hin"]}
    assert _resolve_cast_audio_map(probe, None, "fra") == "0:a?"


def test_resolve_audio_map_by_index_and_clamp():
    probe = {"audio_count": 2, "audio_langs": ["eng", "hin"]}
    assert _resolve_cast_audio_map(probe, 1, None) == "0:a:1?"
    # out-of-range index -> all audio
    assert _resolve_cast_audio_map(probe, 5, None) == "0:a?"
    # no selection -> all audio
    assert _resolve_cast_audio_map(probe, None, None) == "0:a?"
    # none probe safe
    assert _resolve_cast_audio_map(None, None, "hin") == "0:a?"


def test_build_remux_cmd_maps_subs_when_text():
    cmd = _build_cast_remux_cmd("0:a:1?", map_subs=True, seek_time=None)
    assert "-map" in cmd and "0:v:0?" in cmd
    assert "0:a:1?" in cmd
    # text subs mapped + transcoded to mov_text
    assert "-map" in cmd and "0:s?" in cmd
    assert "-c:s" in cmd and "mov_text" in cmd
    assert "pipe:1" in cmd


def test_build_remux_cmd_skips_subs_for_bitmap():
    cmd = _build_cast_remux_cmd("0:a?", map_subs=False, seek_time=None)
    assert "0:s?" not in cmd
    assert "mov_text" not in cmd


def test_build_remux_cmd_seek():
    cmd = _build_cast_remux_cmd("0:a?", map_subs=True, seek_time=1.5)
    assert "-ss" in cmd
    ss_idx = cmd.index("-ss")
    assert cmd[ss_idx + 1] == "1.500"


def test_end_to_end_mp4_mov_text_is_carried():
    # The original regression: an MP4 with mov_text subs must produce a remux
    # command that keeps the subtitle track.
    data = _ffprobe(["eng", "hin"], sub_codec="mov_text", duration="60.0")
    probe = _parse_cast_probe(data)
    audio_map = _resolve_cast_audio_map(probe, None, "hin")
    cmd = _build_cast_remux_cmd(audio_map, probe["has_text_subs"], seek_time=None)
    assert audio_map == "0:a:1?"
    assert "0:s?" in cmd and "mov_text" in cmd
