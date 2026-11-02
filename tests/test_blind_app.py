"""Smoke tests for the blind-test page of the Streamlit app.

The statistics and the blindness guarantee are tested against the library in
`test_blind.py`, which is where they belong. What these tests cover is the part
only the page can get wrong: that a reader can reach the rating screen without
going through the profiler, that the organiser's two downloads are offered
separately, and above all that nothing on the rating screen leaks the answer.
"""

import json

from streamlit.testing.v1 import AppTest

from copyme.blind import build_packet

APP = "pages/1_Blind_test.py"
TIMEOUT = 60


def _app():
    """Run the blind-test page and return the result."""
    return AppTest.from_file(APP, default_timeout=TIMEOUT).run()


def _click(at, label):
    """Click the button with this label, rather than trusting an index.

    The build screen grows buttons as pairs are added, so positional indexing
    silently clicks the wrong one -- which is how the first version of these
    tests "added a pair" twice instead of building the packet.

    Args:
        at (AppTest): The running app.
        label (str): The button's exact label.

    Returns:
        AppTest: The app after the click and rerun.
    """
    for button in at.button:
        if button.label == label:
            return button.click().run()
    raise AssertionError(f"no button labelled {label!r}; found {[b.label for b in at.button]}")


def test_the_page_opens_without_a_writing_sample():
    """A reader must not have to run the profiler to rate a packet.

    This is why the blind test is its own page rather than a tab inside the
    profiler: the profiler gates everything behind a spaCy parse of a pasted
    sample, which a reader has no reason to supply and no sample to supply.
    """
    at = _app()

    assert list(at.exception) == []
    assert at.title[0].value == "Blind test"


def test_the_page_states_that_a_lower_score_is_better():
    """The score reads backwards, so the page has to say so up front.

    A pick rate is the share of times readers *caught* the imitation, so a low
    number is the good outcome. Everyone's first instinct is the opposite, and
    an organiser who misreads the direction will draw exactly the wrong
    conclusion from their own run.
    """
    at = _app()

    banner = " ".join(info.value for info in at.info)

    assert "lower score is better" in banner
    assert "50%" in banner and "coin flip" in banner


def test_all_three_modes_render():
    """Build, rate and tally must each be reachable and raise nothing.

    The three map onto the three roles in the protocol, and two of them are
    used by people who will never touch the rest of copyme.
    """
    for mode in ("Build a packet", "Rate a packet", "Tally the results"):
        at = _app()
        at.radio[0].set_value(mode).run()

        assert list(at.exception) == [], f"{mode} raised"


def test_rating_mode_asks_for_the_packet_and_nothing_else():
    """A reader arrives with one file and should be asked for exactly that.

    If the rating screen asked for the key as well, the reader would hold the
    answers and the test would not be blind.
    """
    at = _app()
    at.radio[0].set_value("Rate a packet").run()

    assert list(at.exception) == []
    labels = [uploader.label for uploader in at.get("file_uploader")]
    assert labels == ["The packet file you were sent"]


def test_the_rendered_packet_file_contains_no_answers():
    """The file a reader is sent must not contain the key in any form.

    `test_blind.py` asserts this of the serialised packet. This asserts it of
    the bytes the page actually hands over, because the page is free to add
    fields to a download and a leak there would be just as fatal.
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


def test_building_a_pair_offers_a_packet_and_a_key_separately():
    """The organiser gets two downloads, because the files have different homes.

    One goes to readers and one must not. A single combined download would
    make that impossible to get right, so the page offers them as two buttons
    with the warning attached to the key.
    """
    at = _app()
    at.radio[0].set_value("Build a packet").run()

    at.text_input[0].set_value("London")              # author
    at.text_area[0].set_value("A real passage.")      # real
    at.text_area[1].set_value("A generated passage.") # generated
    at = _click(at, "Add this pair")

    assert list(at.exception) == []

    # The pair is listed, so the run summary appeared.
    assert any("Build the two files" in header.value for header in at.subheader)

    at = _click(at, "Build packet and key")

    assert list(at.exception) == []
    downloads = [button.label for button in at.get("download_button")]
    assert any("Packet" in label for label in downloads)
    assert any("Answer key" in label for label in downloads)
    assert any("Do not send this to a reader" in c.value for c in at.caption)


def test_a_pair_missing_a_passage_is_refused_with_a_reason():
    """Half a comparison is not a comparison, and the page says which half.

    The form is the normal place for this mistake, so the message names what
    is missing rather than reporting a validation failure.
    """
    at = _app()
    at.radio[0].set_value("Build a packet").run()

    at.text_input[0].set_value("London")
    at.text_area[0].set_value("Only the real passage.")
    at = _click(at, "Add this pair")

    assert list(at.exception) == []
    assert any("needs both passages" in warning.value for warning in at.warning)
