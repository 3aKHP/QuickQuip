from __future__ import annotations

from pathlib import Path

from quickquip.common.sensitive_filter import (
    SCRUB_PLACEHOLDER,
    SensitiveFilter,
    _normalize,
    _word_hash,
)


def _write_toml(tmp_path: Path, content: str) -> Path:
    target = tmp_path / "sensitive_words.toml"
    target.write_text(content, encoding="utf-8")
    return target


def test_empty_filter_passes_everything():
    sf = SensitiveFilter.empty()
    assert sf.is_loaded is False
    result = sf.scan("anything goes here")
    assert result.hits == []
    assert result.blocked is False


def test_block_word_hits_input(tmp_path):
    path = _write_toml(tmp_path, """
[block.fraud]
words = ["杀猪盘"]
""")
    sf = SensitiveFilter.from_toml(path)
    assert sf.is_loaded
    assert sf.stats == {"total": 1, "block": 1, "soft": 0}

    result = sf.scan("我朋友被杀猪盘骗了三万")
    assert result.blocked
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.category == "fraud"
    assert hit.severity == "block"
    assert hit.word_hash == _word_hash("杀猪盘")


def test_soft_word_logs_but_does_not_block(tmp_path):
    path = _write_toml(tmp_path, """
[soft.spam]
words = ["加微信领取"]
""")
    sf = SensitiveFilter.from_toml(path)
    result = sf.scan("加微信领取免费教程")
    assert result.has_soft
    assert result.blocked is False
    assert result.hits[0].severity == "soft"


def test_normalization_strips_zero_width_and_whitespace(tmp_path):
    path = _write_toml(tmp_path, """
[block.test]
words = ["六四"]
""")
    sf = SensitiveFilter.from_toml(path)
    # zero-width joiner inserted between characters
    obfuscated = "六​四"
    assert sf.scan(obfuscated).blocked
    # whitespace insertion
    assert sf.scan("六 四").blocked
    # both
    assert sf.scan("六​ 四").blocked


def test_normalization_lowercases(tmp_path):
    path = _write_toml(tmp_path, """
[block.test]
words = ["sensitive"]
""")
    sf = SensitiveFilter.from_toml(path)
    assert sf.scan("This Is SENSITIVE content").blocked


def test_block_categories_dedup(tmp_path):
    path = _write_toml(tmp_path, """
[block.fraud]
words = ["杀猪盘", "跑分平台"]

[block.gambling]
words = ["私彩"]
""")
    sf = SensitiveFilter.from_toml(path)
    result = sf.scan("杀猪盘和跑分平台都涉及私彩")
    assert result.blocked
    cats = result.block_categories()
    # both fraud hits collapse to one category entry, ordered by first hit
    assert cats == ["fraud", "gambling"]


def test_scrub_replaces_block_hits(tmp_path):
    path = _write_toml(tmp_path, """
[block.fraud]
words = ["杀猪盘"]

[soft.noise]
words = ["免费教程"]
""")
    sf = SensitiveFilter.from_toml(path)
    scrubbed = sf.scrub("我朋友被杀猪盘骗了，找了免费教程")
    # block hit replaced
    assert "杀猪盘" not in scrubbed
    assert SCRUB_PLACEHOLDER in scrubbed
    # soft hit preserved (scrub only handles block tier)
    assert "免费教程" in scrubbed


def test_scrub_merges_overlapping_hits(tmp_path):
    path = _write_toml(tmp_path, """
[block.test]
words = ["abc", "bcd"]
""")
    sf = SensitiveFilter.from_toml(path)
    # "abcd" contains both "abc" (0-3) and "bcd" (1-4); they should merge into
    # one placeholder rather than producing two adjacent placeholders.
    result = sf.scrub("xabcdy")
    assert result.count(SCRUB_PLACEHOLDER) == 1


def test_scrub_returns_text_unchanged_when_no_hits(tmp_path):
    path = _write_toml(tmp_path, """
[block.test]
words = ["nope"]
""")
    sf = SensitiveFilter.from_toml(path)
    original = "this is harmless"
    assert sf.scrub(original) == original


def test_missing_file_loads_empty(tmp_path):
    missing = tmp_path / "does_not_exist.toml"
    sf = SensitiveFilter.from_toml(missing)
    assert sf.is_loaded is False
    assert sf.scan("anything").hits == []


def test_malformed_toml_keeps_previous_state(tmp_path):
    good = _write_toml(tmp_path, """
[block.test]
words = ["target"]
""")
    sf = SensitiveFilter.from_toml(good)
    assert sf.is_loaded

    bad = tmp_path / "broken.toml"
    bad.write_text("[block.test\nwords = [", encoding="utf-8")
    sf.load_toml(bad)
    # parse failure must not wipe the existing automaton
    assert sf.is_loaded
    assert sf.scan("hit target now").blocked


def test_reload_replaces_word_list(tmp_path):
    path = _write_toml(tmp_path, """
[block.v1]
words = ["alpha"]
""")
    sf = SensitiveFilter.from_toml(path)
    assert sf.scan("alpha").blocked
    assert sf.scan("beta").blocked is False

    path.write_text("""
[block.v2]
words = ["beta"]
""", encoding="utf-8")
    sf.load_toml(path)
    # old word released, new word picked up
    assert sf.scan("alpha").blocked is False
    assert sf.scan("beta").blocked


def test_block_takes_precedence_over_soft_for_same_word(tmp_path):
    # If a word appears in both block and soft (deployer mistake or migration),
    # the first-seen entry wins. Block sections are loaded first, so block
    # severity should be preserved.
    path = _write_toml(tmp_path, """
[block.priority]
words = ["overlap"]

[soft.priority]
words = ["overlap"]
""")
    sf = SensitiveFilter.from_toml(path)
    result = sf.scan("text with overlap inside")
    assert result.blocked
    assert sf.stats["total"] == 1  # dedup honored


def test_normalize_helper():
    assert _normalize("Hello​World") == "helloworld"
    assert _normalize("a b\tc") == "abc"
    assert _normalize("") == ""


def test_word_hash_is_deterministic():
    assert _word_hash("test") == _word_hash("test")
    assert _word_hash("a") != _word_hash("b")
    assert len(_word_hash("anything")) == 12


def test_dedup_preserves_distinct_overlapping_matches(tmp_path):
    # Regression: an earlier dedup key of (category, severity, start)
    # collapsed two same-category words sharing a start position into
    # one hit, dropping the wider match. Use prefix-overlapping words
    # in the SAME category to force that collision and verify both
    # survive.
    path = _write_toml(tmp_path, """
[block.t]
words = ["abcd", "abcde"]
""")
    sf = SensitiveFilter.from_toml(path)
    result = sf.scan("abcde")
    matched_hashes = {h.word_hash for h in result.hits}
    assert _word_hash("abcd") in matched_hashes
    assert _word_hash("abcde") in matched_hashes


def test_aho_corasick_finds_all_overlapping_matches(tmp_path):
    # Sanity check the classic AC overlap case.
    path = _write_toml(tmp_path, """
[block.t]
words = ["he", "she", "his", "hers"]
""")
    sf = SensitiveFilter.from_toml(path)
    result = sf.scan("ushers")
    matched_hashes = {h.word_hash for h in result.hits}
    # "she" (1-4), "he" (2-4), "hers" (2-6) all overlap inside "ushers"
    assert _word_hash("she") in matched_hashes
    assert _word_hash("he") in matched_hashes
    assert _word_hash("hers") in matched_hashes


def test_long_text_scan_completes_quickly(tmp_path):
    # Smoke test: ~10k char input shouldn't choke. Not a benchmark, just a
    # ceiling check that the pure-Python AC isn't pathological.
    import time

    words = [f"word{i}" for i in range(500)]
    words_str = ", ".join(f'"{w}"' for w in words)
    path = _write_toml(tmp_path, f"""
[block.bulk]
words = [{words_str}]
""")
    sf = SensitiveFilter.from_toml(path)

    text = "harmless text " * 700  # ~10k chars
    start = time.perf_counter()
    sf.scan(text)
    elapsed = time.perf_counter() - start
    # Generous upper bound; on a normal machine this should be < 50ms even on
    # CI runners. If this fails we have a perf regression worth investigating.
    assert elapsed < 1.0, f"scan took {elapsed:.3f}s, expected < 1s"
