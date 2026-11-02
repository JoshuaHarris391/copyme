"""The command line, end to end.

Four subcommands, and one rule that matters more than any of them: **none of
them needs an API key.** Asking for the live contrastive tier without one
degrades to the static tier and says why, because the static tier is the default
for good reasons and a user should get a profile either way.

The other property worth protecting is that ``score --json`` emits JSON and
nothing else, so it can be piped into a program.
"""

import json

import pytest

from copyme.cli import main


@pytest.fixture(scope="module")
def sample_file(tmp_path_factory):
    """A real sample on disk, large enough to produce exemplars.

    The CLI reads from the filesystem, so these tests go through a file rather
    than passing text in -- that is the path users take, and it is where a path
    or encoding mistake would show up.
    """
    from pathlib import Path

    source = Path("tests/fixtures/london.txt").read_text(encoding="utf-8")[:25_000]
    path = tmp_path_factory.mktemp("cli") / "sample.txt"
    path.write_text(source[: source.rfind("\n\n")], encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def profile_file(sample_file, tmp_path_factory):
    """A profile written by the CLI itself, for the other subcommands to read."""
    path = tmp_path_factory.mktemp("cli") / "profile.json"
    assert main(["profile", str(sample_file), "--out", str(path), "--quiet"]) == 0
    return path


def test_profile_writes_a_loadable_profile(profile_file):
    """The first subcommand has to produce what the other three consume.

    If the written file did not round trip, every later command would fail with
    a confusing error about the file rather than about the write.
    """
    from copyme import Profile

    payload = json.loads(profile_file.read_text())
    assert payload["schema"] == "copyme/profile/2"

    profile = Profile.from_dict(payload)
    assert profile.rules
    assert profile.exemplars
    assert profile.provenance["copyme_version"]


def test_profile_needs_no_api_key(monkeypatch, sample_file, tmp_path):
    """Nothing in the default path may require a credential.

    copyme's whole static design exists so that profiling works offline. A
    subcommand that quietly needed a key would only fail for the users who do
    not have one.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "p.json"

    assert main(["profile", str(sample_file), "--out", str(out), "--quiet"]) == 0
    assert out.exists()


def test_asking_for_the_live_tier_without_a_key_degrades_with_a_reason(
    monkeypatch, sample_file, tmp_path, capsys
):
    """Degrading is correct; degrading silently is not.

    The user asked for measured drift and got predicted drift. That is a
    perfectly good profile, but they need to know which one they have -- the two
    tiers carry different confidence, and only one of them is tied to a
    particular model.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "live.json"

    assert (
        main(
            [
                "profile",
                str(sample_file),
                "--out",
                str(out),
                "--contrastive",
                "live",
                "--quiet",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "static contrastive tier" in captured.err
    assert "ANTHROPIC_API_KEY" in captured.err or "anthropic" in captured.err

    # And the profile records which tier it actually used.
    assert json.loads(out.read_text())["provenance"]["contrastive"] == "static"


def test_render_produces_each_format(profile_file, capsys):
    """Every format offered on the command line has to work from a stored file.

    ``render`` is the subcommand that proves a profile is self-sufficient: no
    sample, no parse, no analyser, just the JSON.
    """
    from copyme.exports import FORMATS

    for export_format in FORMATS:
        assert main(["render", str(profile_file), "--format", export_format]) == 0
        assert capsys.readouterr().out.strip(), f"{export_format} printed nothing"


def test_render_can_resize_a_stored_profile(profile_file, capsys):
    """Re-sizing from disk is the point of storing the full ranking.

    Without it, changing size would mean going back to the original sample,
    which the user may no longer have.
    """
    main(["render", str(profile_file), "--size", "compact", "--quiet"])
    compact = capsys.readouterr().out

    main(["render", str(profile_file), "--size", "full", "--quiet"])
    full = capsys.readouterr().out

    assert len(full) > len(compact)


def test_score_json_emits_only_json(profile_file, sample_file, capsys):
    """Mixing a log line into stdout breaks every caller that pipes it.

    Progress and warnings go to stderr throughout for exactly this reason. The
    test parses stdout strictly, so a stray print would fail it.
    """
    assert (
        main(["score", str(sample_file), "--against", str(profile_file), "--json"]) == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["in_band"] == 1.0, "the sample should be in band against itself"
    assert "footer" in payload


def test_score_without_json_prints_a_readable_report(
    profile_file, sample_file, capsys
):
    """The default output is for a person, and must carry the caveat.

    A score read as a verdict is worse than no score, so the footer appears in
    every render rather than only in the JSON.
    """
    assert main(["score", str(sample_file), "--against", str(profile_file)]) == 0

    out = capsys.readouterr().out
    assert "blind read" in out
    assert "rules met" in out


def test_card_writes_a_png_with_the_character_json_embedded(profile_file, tmp_path):
    """A Character Card V2 file is a PNG carrying the card in a text chunk.

    Front ends read the chunk, not the picture, so the image is generated with
    the standard library and no image dependency. This checks the file really is
    a PNG and that the chunk round trips back to a valid card.
    """
    import base64

    out = tmp_path / "card.png"
    assert main(["card", str(profile_file), "--out", str(out), "--name", "London"]) == 0

    data = out.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IEND" in data, "the PNG must be terminated properly"

    marker = data.index(b"tEXtchara\x00") + len(b"tEXtchara\x00")
    end = data.index(b"IEND") - 4
    card = json.loads(base64.b64decode(data[marker:end]))

    assert card["spec"] == "chara_card_v2"
    assert card["data"]["name"] == "London"


def test_a_missing_profile_reports_the_path_rather_than_a_traceback(tmp_path):
    """A wrong path is the most common command-line mistake there is.

    It deserves one line naming the file, not a stack trace through the JSON
    parser.
    """
    with pytest.raises(SystemExit) as error:
        main(["render", str(tmp_path / "nope.json")])

    assert "nope.json" in str(error.value)


def test_a_file_that_is_not_a_copyme_profile_is_refused_clearly(tmp_path):
    """Valid JSON that is not a profile has to be caught at the boundary.

    Otherwise it fails somewhere inside ``from_dict`` with a KeyError, which
    tells the user nothing about what was actually wrong with their file.
    """
    wrong = tmp_path / "wrong.json"
    wrong.write_text('{"hello": "world"}')

    with pytest.raises(SystemExit) as error:
        main(["score", "-", "--against", str(wrong)])

    message = str(error.value)
    assert "not a copyme v2 profile" in message
    assert "copyme profile" in message
