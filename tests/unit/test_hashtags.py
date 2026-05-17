from app.services.hashtags import MAX_TAGS_PER_WORKSHOP, extract_hashtags


def test_returns_empty_for_blank_input():
    assert extract_hashtags("") == []
    assert extract_hashtags(None) == []
    assert extract_hashtags("nothing to see here") == []


def test_extracts_basic_hashtags_preserving_order():
    assert extract_hashtags("learn #joga and #medytacja today") == ["joga", "medytacja"]


def test_lowercases_normalization():
    assert extract_hashtags("#Joga #JOGA #yoga") == ["joga", "yoga"]


def test_deduplicates_within_input():
    assert extract_hashtags("#joga is great, #joga rules") == ["joga"]


def test_caps_at_five_tags():
    text = "#one #two #three #four #five #six #seven"
    assert extract_hashtags(text) == ["one", "two", "three", "four", "five"]
    assert len(extract_hashtags(text)) == MAX_TAGS_PER_WORKSHOP


def test_supports_polish_characters():
    assert extract_hashtags("#poznań #łódź #medytacja") == [
        "poznań",
        "łódź",
        "medytacja",
    ]


def test_ignores_short_tags():
    assert extract_hashtags("#a #ab #b") == ["ab"]


def test_ignores_tags_longer_than_max():
    too_long = "a" * 31
    assert extract_hashtags(f"#{too_long} #ok") == ["ok"]


def test_adjacent_hashtags_only_first_matches():
    # `#joga#yoga` → only `joga` (the second `#` follows a word char).
    assert extract_hashtags("#joga#yoga") == ["joga"]


def test_ignores_double_hash_prefix():
    # ##joga: leading '#' has no preceding word char so the lookbehind passes,
    # but the second '#' is preceded by '#' (not a word char), so #joga matches.
    assert extract_hashtags("##joga") == ["joga"]


def test_underscore_and_digits_allowed():
    assert extract_hashtags("#yoga_2 #flow1") == ["yoga_2", "flow1"]


def test_hash_in_word_is_not_a_tag():
    assert extract_hashtags("foo#bar") == []
    assert extract_hashtags("email@example.com#anchor") == []
