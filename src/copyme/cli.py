"""The command line: ``copyme profile / render / score / card``.

A thin wrapper. No logic lives here -- every subcommand is argument parsing, a
call into the library, and printing. If something in this file looks like a
decision about style, it is in the wrong place.

No subcommand requires an API key. ``--contrastive live`` is the only path that
can use one, and without a key it degrades to the static tier and says why.
"""

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

from .analyser import (
    V2_ANALYSIS_STAGES,
    StyleAnalyser,
    TextTooLongError,
    build_profile,
    memory_for_length,
)
from .contrastive import LiveTierUnavailableError, anthropic_model_call, live_notes
from .exports import FORMATS, build_pre_prompt, sillytavern_card, token_estimates
from .profile import SIZE_PRESETS, Profile
from .scorer import score

DEFAULT_MODEL = "claude-sonnet-5"


def _read_text(path):
    """Read a text file, or stdin when ``path`` is ``-``."""
    if str(path) == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _load_profile(path):
    """Load a profile from JSON.

    Args:
        path (str): Path to a profile written by ``copyme profile``.

    Returns:
        Profile: The profile.

    Raises:
        SystemExit: With a readable message if the file is missing or is not a
            copyme profile, rather than a traceback.
    """
    try:
        payload = json.loads(_read_text(path))
    except FileNotFoundError:
        raise SystemExit(f"No such profile: {path}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path} is not valid JSON: {error}")

    if payload.get("schema") != "copyme/profile/2":
        raise SystemExit(
            f"{path} is not a copyme v2 profile "
            f"(schema {payload.get('schema', 'missing')!r}). "
            f"Rebuild it with 'copyme profile'."
        )
    return Profile.from_dict(payload)


def _progress(label, percent):
    """Print progress to stderr, so stdout stays machine-readable."""
    print(f"\r{percent:5.1f}%  {label:<36}", end="", file=sys.stderr, flush=True)


def command_profile(args):
    """Build a profile from a sample and write it as JSON."""
    text = _read_text(args.sample)
    quiet = args.quiet or args.out is None

    try:
        analyser = StyleAnalyser(
            text,
            memory_gb=args.memory_gb,
            on_progress=None if quiet else _progress,
            stages=V2_ANALYSIS_STAGES,
        )
    except TextTooLongError as error:
        # The limit is a deliberate guard, not a failure: spaCy needs about a
        # gigabyte of temporary memory per 100,000 characters, and a stray paste
        # can ask for tens of gigabytes. Report the budget to raise rather than
        # a traceback through the parser.
        raise SystemExit(
            f"{error}\n\nPass --memory-gb "
            f"{memory_for_length(len(text)):g} to analyse this sample."
        )

    contrastive = args.contrastive
    degraded = None
    model_call = None
    if contrastive == "live":
        try:
            model_call = anthropic_model_call(model=args.model)
        except LiveTierUnavailableError as error:
            # Degrade rather than fail: the static tier is the default for good
            # reasons and the user gets a profile either way, with the reason
            # stated instead of a silent substitution.
            degraded = str(error)
            contrastive = "static"

    profile = build_profile(
        analyser,
        exemplar_budget=args.budget,
        size=args.size,
        mask_names=not args.no_mask_names,
        contrastive=contrastive,
        model=args.model,
    )

    if model_call is not None:
        try:
            notes, record = live_notes(
                profile, model_call, score, model=args.model, count=args.live_drafts
            )
            provenance = dict(
                profile.provenance,
                contrastive="live",
                contrastive_model=record["model"],
                live_drafts_scored=record["drafts_scored"],
                live_mean_in_band=record["mean_in_band"],
            )
            from dataclasses import replace

            profile = replace(
                profile,
                known_failures=profile.known_failures + tuple(notes),
                provenance=provenance,
            )
        except LiveTierUnavailableError as error:
            degraded = str(error)

    if not quiet:
        print(file=sys.stderr)
    if degraded:
        print(f"Using the static contrastive tier: {degraded}", file=sys.stderr)

    payload = profile.to_json()
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(
            f"Wrote {args.out}: {len(profile.rules)} rules, "
            f"{len(profile.exemplars)} exemplars, profile {profile.hash}",
            file=sys.stderr,
        )
    else:
        print(payload)
    return 0


def command_render(args):
    """Render a stored profile to one of the export targets."""
    profile = _load_profile(args.profile)
    output = build_pre_prompt(
        profile,
        size=args.size,
        format=args.format,
        mask_names=None if args.no_mask_names is None else not args.no_mask_names,
    )
    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(output)

    if not args.quiet:
        counts = token_estimates(output)
        print(
            f"About {counts['gpt']:,} tokens for the GPT family and "
            f"{counts['claude']:,} for Claude "
            f"(estimated at {counts['multiplier']}x).",
            file=sys.stderr,
        )
    return 0


def command_score(args):
    """Score a generated text against a stored profile."""
    profile = _load_profile(args.against)
    generated = _read_text(args.generated)
    report = score(generated, profile)

    if args.json:
        # Nothing else may reach stdout in this mode: the point is that the
        # output can be piped into a program.
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.render())
    return 0


def _png(width, height, rgb):
    """Build a minimal valid PNG of one colour, using only the standard library.

    A Character Card V2 file is a PNG carrying the character JSON in a ``tEXt``
    chunk, and front ends read the chunk rather than the picture. Generating a
    plain background here means ``copyme card`` works with no image library
    installed; a user who wants real art can replace the image and keep the
    chunk.
    """
    raw = b"".join(
        b"\x00" + bytes(rgb) * width for _ in range(height)
    )

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _png_with_text(png_bytes, keyword, value):
    """Insert a ``tEXt`` chunk into a PNG, immediately before ``IEND``.

    Args:
        png_bytes (bytes): A valid PNG.
        keyword (str): The chunk keyword, ``"chara"`` for a character card.
        value (str): The text to store.

    Returns:
        bytes: The PNG with the chunk added.
    """
    data = keyword.encode("latin-1") + b"\x00" + value.encode("latin-1")
    body = b"tEXt" + data
    text_chunk = (
        struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    )
    marker = png_bytes.rindex(struct.pack(">I", 0) + b"IEND")
    return png_bytes[:marker] + text_chunk + png_bytes[marker:]


def command_card(args):
    """Write a SillyTavern Character Card V2 PNG with the JSON embedded."""
    import base64

    profile = _load_profile(args.profile)
    card = sillytavern_card(profile, name=args.name)
    encoded = base64.b64encode(
        json.dumps(card).encode("utf-8")
    ).decode("latin-1")

    if args.image:
        image = Path(args.image).read_bytes()
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SystemExit(f"{args.image} is not a PNG.")
    else:
        image = _png(400, 600, (34, 34, 40))

    Path(args.out).write_bytes(_png_with_text(image, "chara", encoded))
    print(
        f"Wrote {args.out}: Character Card V2 for profile {profile.hash}",
        file=sys.stderr,
    )
    return 0


def build_parser():
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="copyme",
        description="Build, render and check a writing-voice profile.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_parser = subparsers.add_parser(
        "profile", help="Analyse a sample and write a profile as JSON."
    )
    profile_parser.add_argument("sample", help="Path to the sample text, or - for stdin.")
    profile_parser.add_argument("--out", help="Where to write the profile. Default: stdout.")
    profile_parser.add_argument(
        "--size",
        default="standard",
        choices=sorted(SIZE_PRESETS),
        help="Which preset to build for. Default: standard.",
    )
    profile_parser.add_argument(
        "--budget", type=int, help="Exemplar block budget in tokens, overriding the preset."
    )
    profile_parser.add_argument(
        "--contrastive",
        default="static",
        choices=("static", "live", "none"),
        help=(
            "Where the known-failure notes come from. 'static' needs no API "
            "call. 'live' asks the model to write and scores the result, and "
            "falls back to static with a reason if no key is configured."
        ),
    )
    profile_parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"Model name to record. Default: {DEFAULT_MODEL}."
    )
    profile_parser.add_argument(
        "--live-drafts",
        type=int,
        default=2,
        help="How many held-out passages the live tier tests against. Default: 2.",
    )
    profile_parser.add_argument(
        "--no-mask-names",
        action="store_true",
        help="Keep one-off names in the exemplars instead of masking them.",
    )
    profile_parser.add_argument("--memory-gb", type=float, help="Temporary memory budget.")
    profile_parser.add_argument("--quiet", action="store_true", help="No progress output.")
    profile_parser.set_defaults(func=command_profile)

    render_parser = subparsers.add_parser(
        "render", help="Render a stored profile to a prompt or a card."
    )
    render_parser.add_argument("profile", help="Path to a profile JSON file.")
    render_parser.add_argument(
        "--size", default=None, choices=sorted(SIZE_PRESETS), help="Override the profile's size."
    )
    render_parser.add_argument(
        "--format", default="first_message", choices=FORMATS, help="Export target."
    )
    render_parser.add_argument("--out", help="Where to write it. Default: stdout.")
    render_parser.add_argument(
        "--no-mask-names",
        action="store_const",
        const=True,
        default=None,
        help="Keep one-off names in the exemplars.",
    )
    render_parser.add_argument("--quiet", action="store_true", help="No token-count note.")
    render_parser.set_defaults(func=command_render)

    score_parser = subparsers.add_parser(
        "score", help="Compare a generated text with a profile."
    )
    score_parser.add_argument("generated", help="Path to the model's output, or - for stdin.")
    score_parser.add_argument("--against", required=True, help="Path to a profile JSON file.")
    score_parser.add_argument(
        "--json", action="store_true", help="Emit JSON on stdout and nothing else."
    )
    score_parser.set_defaults(func=command_score)

    card_parser = subparsers.add_parser(
        "card", help="Write a SillyTavern Character Card V2 PNG."
    )
    card_parser.add_argument("profile", help="Path to a profile JSON file.")
    card_parser.add_argument("--out", required=True, help="Where to write the PNG.")
    card_parser.add_argument("--name", default="Voice", help="Character name. Default: Voice.")
    card_parser.add_argument(
        "--image", help="An existing PNG to embed the card into. Default: a plain background."
    )
    card_parser.set_defaults(func=command_card)

    return parser


def main(argv=None):
    """Entry point.

    Args:
        argv (list[str], optional): Arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        int: The exit status.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "contrastive", None) == "none":
        args.contrastive = None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
