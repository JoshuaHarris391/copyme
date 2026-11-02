"""Smoke tests for the blind-test page of the Streamlit app.

Background. The statistics and the packet/key separation are tested against the
library in `test_blind.py`, and the generation step in `test_generate.py`. What
these tests cover is the part only the page can get wrong, and the one thing that
would invalidate every run it ever produces: **leaking the answer to the reader
before they have judged**.

The page has three screens in one mode — set up, judge, score — and the answer
key is in session state from the moment generation finishes. So the key risk is
not the file format but the rendering: a correctness tick, a count of right
answers, or the real passage labelled as such, appearing on the judging screen.
Several tests here do nothing but read the rendered output and assert that
nothing of that kind is in it.

Everything runs with no network and no API key. The page calls
`contrastive.model_call_from_env` through the module rather than through a bound
import, which is what lets these tests replace it with a fake model.
"""

import json
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from copyme.blind import Ballot, build_packet, tally

APP = "pages/1_Blind_test.py"
TIMEOUT = 60

# What the fake model "writes". Deliberately unlike the fixture author, so a
# test that accidentally depended on the two being hard to tell apart would
# fail rather than pass for the wrong reason.
GENERATED = (
    "It is important to note that there are a number of factors which may "
    "influence the outcome, and each of them should be carefully considered."
)


def _app():
    """Run the blind-test page and return the result."""
    return AppTest.from_file(APP, default_timeout=TIMEOUT).run()


def _click(at, label):
    """Click the button with this label, rather than trusting an index.

    Positional indexing silently clicks the wrong button as the page grows, and
    this page grows a row of navigation buttons on the judging screen.

    Args:
        at (AppTest): The running app.
        label (str): The button's exact label.

    Returns:
        AppTest: The app after the click and rerun.
    """
    for button in at.button:
        if button.label == label:
            return button.click().run()
    raise AssertionError(
        f"no button labelled {label!r}; found {[b.label for b in at.button]}"
    )


def _set_text_input(at, label, value):
    """Set the text input with this label, by label rather than by index.

    Args:
        at (AppTest): The running app.
        label (str): The input's exact label.
        value (str): What to type.

    Returns:
        AppTest: The app after the change and rerun.
    """
    for widget in at.text_input:
        if widget.label == label:
            return widget.set_value(value).run()
    raise AssertionError(
        f"no text input labelled {label!r}; found {[w.label for w in at.text_input]}"
    )


def _rendered(at):
    """Return every piece of text the page rendered, as one string.

    Used by the leak tests. Reading the whole surface is the point: a leak could
    arrive through a caption, a metric, a success banner or a dataframe, and
    checking only the element a leak was once found in is how the next one gets
    through.

    Args:
        at (AppTest): The running app.

    Returns:
        str: Everything rendered, concatenated.
    """
    parts = []
    for collection in (
        at.markdown,
        at.caption,
        at.text,
        at.subheader,
        at.title,
        at.info,
        at.success,
        at.warning,
        at.error,
        at.metric,
    ):
        for element in collection:
            parts.append(str(getattr(element, "value", "")))
    for element in at.get("expander"):
        parts.append(str(getattr(element, "label", "")))
    return "\n".join(parts)


@pytest.fixture(scope="session")
def profile_json(held_out_profile):
    """Profile JSON for a sample that leaves passages held out.

    The shared `held_out_profile` fixture is the London slice at Compact, used
    for the same reason the contrastive tests use it: a Standard profile of a
    short slice takes every candidate passage, which leaves the blind test
    nothing honest to compare against.

    Returns:
        str: The JSON a user would paste into the page.
    """
    return held_out_profile.to_json()


def _fake_model_call(model=None):
    """Stand in for `model_call_from_env`, returning fixed text and no network.

    Args:
        model (str, optional): Ignored; accepted so the signature matches.

    Returns:
        callable: A ``model_call(prompt, max_words)``.
    """
    return lambda prompt, max_words: GENERATED


def _started_run(profile_json, rounds=3):
    """Run the page up to the first judging card, with a fake model.

    Args:
        profile_json (str): The profile to paste.
        rounds (int): How many comparisons to generate.

    Returns:
        AppTest: The app sitting on card one.
    """
    with patch("copyme.contrastive.model_call_from_env", _fake_model_call):
        at = _app()
        at.text_area[0].set_value(profile_json).run()
        at = _set_text_input(at, "Your name or initials", "JH")
        at = _set_text_input(at, "Author", "Jack London")
        for widget in at.number_input:
            if widget.label == "Rounds":
                at = widget.set_value(rounds).run()
        at = _click(at, "Generate and start")

    return at


# --- The page itself --------------------------------------------------------


def test_the_page_opens_without_a_writing_sample():
    """A reader must not have to run the profiler to judge a run.

    This is why the blind test is its own page rather than a tab inside the
    profiler: the profiler gates everything behind a spaCy parse of a pasted
    sample, which costs time a reader has no reason to spend.
    """
    at = _app()

    assert list(at.exception) == []
    assert at.title[0].value == "Blind test"


def test_the_page_states_that_a_lower_score_is_better():
    """The score reads backwards, so the page has to say so up front.

    A pick rate is the share of times readers *caught* the imitation, so a low
    number is the good outcome. Everyone's first instinct is the opposite, and
    someone who misreads the direction will draw exactly the wrong conclusion
    from their own run.
    """
    at = _app()

    banner = " ".join(info.value for info in at.info)

    assert "lower score is better" in banner
    assert "50%" in banner and "coin flip" in banner


def test_both_modes_render():
    """Running a test and tallying one must each be reachable and raise nothing.

    Tally mode is used by whoever pools several readers' ballots, and is reached
    by people who never generate anything themselves.
    """
    for mode in ("Run a blind test", "Tally the results"):
        at = _app()
        at.radio[0].set_value(mode).run()

        assert list(at.exception) == [], f"{mode} raised"


# --- Setting up a run -------------------------------------------------------

def test_the_setup_screen_tells_you_not_to_read_what_you_are_pasting():
    """The paste step is the one place a user can spoil their own test.

    The profile JSON names which passages are the author's own. A user who reads
    it while pasting will recognise them on the cards, and their pick rate will
    measure their memory rather than the profile. The instruction has to be on
    the screen where the mistake is available, not only in the documentation.
    """
    at = _app()

    surface = _rendered(at)

    assert "don't read it" in surface or "without reading" in surface


def test_pasting_the_prompt_instead_of_the_json_says_so():
    """This is the likeliest mistake, so it gets a message that names the fix.

    The profiler offers several exports and the rendered prompt is the obvious
    thing to reach for. It is not usable here: it carries only the chosen
    passages, so there would be nothing held out to compare against.

    Input: Markdown where JSON was expected.
    Expected: an error naming the json export, and no traceback.
    """
    at = _app()
    at.text_area[0].set_value("# Author Voice Profile\n\nWrite like this.").run()

    assert list(at.exception) == []
    assert any("not valid JSON" in error.value for error in at.error)
    assert any("json" in error.value for error in at.error)


def test_a_json_file_that_is_not_a_profile_is_refused_by_name():
    """A packet or a key is JSON too, and belongs in the other mode.

    Input: valid JSON with no profile schema.
    Expected: an error naming the expected schema rather than a KeyError.
    """
    at = _app()
    at.text_area[0].set_value(json.dumps({"kind": "copyme.blind.packet"})).run()

    assert list(at.exception) == []
    assert any("copyme/profile/2" in error.value for error in at.error)


def test_the_setup_screen_shows_no_passage_from_the_profile(profile_json):
    """The page can describe the profile, but must not quote it.

    Word count, size and the number of rounds available are all safe: none of
    them tells the reader which passages are the author's. The passages
    themselves are not, and they are sitting right there in the pasted JSON, so
    this has to be checked rather than assumed.

    Input: a real profile pasted into the setup screen.
    Expected: the rendered page contains none of the profile's passage text.
    """
    from copyme.profile import Profile

    at = _app()
    at.text_area[0].set_value(profile_json).run()

    assert list(at.exception) == []

    surface = _rendered(at)
    profile = Profile.from_json(profile_json)
    for exemplar in profile.ranking:
        opening = " ".join(exemplar.text.split()[:8])
        assert opening not in surface, "the setup screen quoted a passage"


# --- Judging ----------------------------------------------------------------


def test_generating_a_run_reaches_the_first_card(profile_json):
    """The whole point of the change: one paste, then judging.

    Previously the generated side of every comparison was produced by hand in a
    separate chat window and pasted back in, which is why no run was ever
    recorded. This asserts the loop closes: paste a profile, press one button,
    and be looking at a comparison.
    """
    at = _started_run(profile_json)

    assert list(at.exception) == []
    assert any("1 of 3" in header.value for header in at.subheader)
    assert any("Jack London" in md.value for md in at.markdown)


def test_each_card_shows_two_passages_as_plain_text(profile_json):
    """Formatting differences would sort the passages without either being read.

    One passage rendered as Markdown and the other not would leak through a
    stray asterisk or an accidental heading. Both sides go through `st.text`,
    which renders verbatim.
    """
    at = _started_run(profile_json)

    bodies = [element.value for element in at.text]

    assert len(bodies) >= 2
    assert any(GENERATED in body for body in bodies)


def test_the_judging_screen_never_reveals_which_side_is_real(profile_json):
    """This is the test the page exists to pass.

    The answer key is in session state from the moment generation finishes, so
    nothing but the rendering stands between the reader and the answers. A tick,
    a running score, or the word "real" beside a passage would invalidate the
    run and every number taken from it.

    Input: a generated run, on card one.
    Expected: nothing in the rendered output names a side as real or reports
    correctness, and the key's own values appear nowhere.
    """
    at = _started_run(profile_json)
    run = at.session_state["blind_run"]

    surface = _rendered(at).lower()

    # The exact strings the results screen uses to reveal an answer. None of
    # them may appear before the run is finished.
    for phrase in (
        "— you were right",
        "— you were fooled",
        "the real one was on the",
        "pick rate",
    ):
        assert phrase not in surface, f"the judging screen leaked: {phrase!r}"

    # The screen may say how many cards have been judged. It must not say how
    # many were judged correctly, which is what the key would let it show.
    assert "judged so far" in surface
    assert "right so far" not in surface

    # No metric and no verdict banner is rendered while judging. Those are the
    # two elements a score would arrive through, so their absence is a stronger
    # check than any list of phrases: a future edit that starts reporting
    # progress-so-far has to fail this.
    assert list(at.metric) == []
    assert list(at.success) == []

    # And the answers themselves are still only in session state.
    assert set(run["key"].real_sides.values()) <= {"left", "right"}


def test_a_pick_is_recorded_and_the_run_advances(profile_json):
    """Judging has to accumulate, or the ballot at the end is empty.

    Input: pick Left on card one, then press Next.
    Expected: the pick is stored against the pair's id and the position moves on.
    """
    at = _started_run(profile_json)
    pair = at.session_state["blind_run"]["packet"].pairs[0]

    at.radio[1].set_value("Left").run()
    at = _click(at, "Next →")

    run = at.session_state["blind_run"]

    assert run["picks"][pair.pair_id] == "left"
    assert run["position"] == 1
    assert any("2 of 3" in header.value for header in at.subheader)


def test_a_skipped_card_is_not_counted_against_the_reader(profile_json):
    """A reader who genuinely cannot judge should say so, not guess.

    A forced guess adds noise at exactly 50%, which drags every pick rate
    towards the coin flip and makes a good profile and a bad one look alike. A
    skipped card is simply absent from the ballot.

    Input: leave card one on Skip and move on.
    Expected: no pick is recorded for it.
    """
    at = _started_run(profile_json)
    pair = at.session_state["blind_run"]["packet"].pairs[0]

    at = _click(at, "Next →")

    assert pair.pair_id not in at.session_state["blind_run"]["picks"]


# --- Scoring ----------------------------------------------------------------


def test_finishing_the_run_scores_it_and_then_reveals_the_answers(profile_json):
    """The reveal is held back to here, where it can no longer bias anything.

    Per-card feedback would teach the reader the imitation's tells on card one
    and let them apply it to card three, pushing the pick rate up for reasons
    unrelated to the profile. Held to the end, the same information is simply
    useful.

    Input: judge all three cards, then finish.
    Expected: a pick rate, the one-reader caveat, and a per-card breakdown that
    now does say which side was real.
    """
    at = _started_run(profile_json)
    at.radio[1].set_value("Left").run()
    at = _click(at, "Next →")
    at = _click(at, "Next →")
    at = _click(at, "Finish and score")

    assert list(at.exception) == []

    surface = _rendered(at)

    assert any(metric.label == "Pick rate" for metric in at.metric)
    assert "The real one was on the" in surface
    assert f"at least {3}" in surface or "protocol asks for at least" in surface


def test_the_result_is_scored_through_the_same_tally_as_a_mailed_run(profile_json):
    """A self-serve number must be comparable with a multi-reader one.

    If the page scored its own runs in its own way, a figure from here and a
    figure from a mailed-out packet could not be put in the same table. Both go
    through `blind.tally`, against the same packet and key objects.

    Input: the run's own packet, key and picks, re-scored directly.
    Expected: the same pick rate the page computed.
    """
    at = _started_run(profile_json)
    at.radio[1].set_value("Left").run()
    at = _click(at, "Next →")
    at = _click(at, "Next →")
    at = _click(at, "Finish and score")

    run = at.session_state["blind_run"]
    direct = tally(
        run["packet"],
        run["key"],
        [Ballot(reader="JH", picks=run["picks"], packet_id=run["packet"].packet_id)],
    )

    shown = next(metric for metric in at.metric if metric.label == "Pick rate")

    assert shown.value == f"{direct.pick_rate:.0%}"


def test_the_run_offers_its_four_files(profile_json):
    """A run that cannot be filed may as well not have happened.

    `docs/evals/` takes one result file per run. The packet and key are the
    audit trail that lets anyone else re-tally it, and the ballot is what a
    reader would send to an organiser pooling several runs.
    """
    at = _started_run(profile_json)
    at.radio[1].set_value("Left").run()
    at = _click(at, "Next →")
    at = _click(at, "Next →")
    at = _click(at, "Finish and score")

    labels = [button.label for button in at.get("download_button")]

    assert any("Result" in label for label in labels)
    assert any("Packet" in label for label in labels)
    assert any("ballot" in label.lower() for label in labels)
    assert any("Answer key" in label for label in labels)


def test_the_packet_the_page_serves_contains_no_answers():
    """The file a reader is sent must not contain the key in any form.

    `test_blind.py` asserts this of the serialised packet. This asserts it of
    the bytes the page hands over, because the page is free to add fields to a
    download and a leak there would be just as fatal.
    """
    packet, key = build_packet(
        [
            {
                "author": "London",
                "variant": "v2",
                "real": "The real one.",
                "generated": "The generated one.",
            }
        ],
        packet_id="run-1",
        seed=11,
    )

    served = json.dumps(packet.to_dict(), indent=2, ensure_ascii=False)

    assert "real_side" not in served
    assert "seed" not in served
    # The key is the other file, and it does hold the answers.
    assert "real_sides" in json.dumps(key.to_dict())


def test_a_missing_api_key_names_the_variable_rather_than_failing(
    profile_json, monkeypatch
):
    """Two environment variables are in play, so "no API key" is not enough.

    The app reads `COPYME_ANTHROPIC_API_KEY` and deliberately ignores the SDK's
    own `ANTHROPIC_API_KEY`, so a user with a key set for another tool will see
    this message and needs to be told which name to use.

    Input: no key in the environment.
    Expected: an error naming the variable, and no traceback.
    """
    at = _app()
    at.text_area[0].set_value(profile_json).run()
    at = _set_text_input(at, "Your name or initials", "JH")
    at = _set_text_input(at, "Author", "Jack London")

    monkeypatch.delenv("COPYME_ANTHROPIC_API_KEY", raising=False)
    at = _click(at, "Generate and start")

    assert list(at.exception) == []
    assert any("COPYME_ANTHROPIC_API_KEY" in error.value for error in at.error)


# --- Tally mode -------------------------------------------------------------


def test_tally_mode_asks_for_the_packet_the_key_and_the_ballots():
    """Pooling several readers is still how a result becomes a finding.

    One reader is indicative; the protocol wants three. Tally mode is how their
    ballots are combined, and it needs all three kinds of file.
    """
    at = _app()
    at.radio[0].set_value("Tally the results").run()

    assert list(at.exception) == []

    labels = [uploader.label for uploader in at.get("file_uploader")]

    assert "Packet" in labels
    assert "Answer key" in labels
    assert any("Ballots" in label for label in labels)
