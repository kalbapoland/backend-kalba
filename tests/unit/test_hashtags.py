from app.services.hashtags import (
    MAX_TAGS_PER_WORKSHOP,
    extract_hashtags,
    normalize_tag_input,
)


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


def test_normalize_tag_input_strips_leading_hash():
    assert normalize_tag_input("#Joga") == "joga"
    assert normalize_tag_input("Joga") == "joga"
    assert normalize_tag_input("##JOGA") == "joga"


def test_normalize_tag_input_handles_polish_chars():
    assert normalize_tag_input("Poznań") == "poznań"
    assert normalize_tag_input("#Łódź") == "łódź"


def test_normalize_tag_input_empty():
    assert normalize_tag_input("") == ""
    assert normalize_tag_input("#") == ""


def test_normalize_tag_input_truncates_at_first_non_word_char():
    # LIKE wildcards and whitespace get dropped at truncation — the leading
    # run of word chars is the canonical prefix to match against `tag.name`.
    assert normalize_tag_input("abc%def") == "abc"
    assert normalize_tag_input("foo bar") == "foo"
    assert normalize_tag_input("abc_def") == "abc_def"  # underscore is a word char


def test_normalize_tag_input_wildcard_only_returns_empty():
    # `%abc` does not start with a word char, so the leading run is empty.
    assert normalize_tag_input("%abc") == ""
    assert normalize_tag_input("_abc") == "_abc"  # underscore IS a word char
    assert normalize_tag_input("!@#") == ""
