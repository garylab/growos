from app.services.content_studio import _parse_json, to_srt


def test_parse_plain_json():
    assert _parse_json('{"title": "A"}')["title"] == "A"


def test_parse_fenced_json():
    assert _parse_json('```json\n{"title": "B"}\n```')["title"] == "B"


def test_parse_json_with_surrounding_text():
    assert _parse_json('Sure!\n{"title": "C"}\nHope that helps')["title"] == "C"


def test_unparsable_text_is_kept_not_lost():
    out = _parse_json("just prose, no json")
    assert out["_unparsed"] and out["body_markdown"] == "just prose, no json"


def test_srt_formatting():
    srt = to_srt([{"start": "00:00:00,000", "end": "00:00:02,500", "text": "Hello"},
                  {"start": "00:00:02,500", "end": "00:00:05,000", "text": "World"}])
    assert srt.splitlines()[0] == "1"
    assert "00:00:00,000 --> 00:00:02,500" in srt and "World" in srt
    assert srt.count("-->") == 2


def test_srt_empty():
    assert to_srt([]) == ""
