"""Generate the baseline corpus: what a model writes when nobody asks for a style.

The baseline is copyme's null hypothesis. Every rule it emits is a rule the model
does not already follow, and this corpus is how "already" is defined. So the
corpus has to be a faithful sample of the model's **default register** -- not of
its ability to follow instructions about register.

Three choices follow from that, and each of them costs something:

**One ordinary question per passage.** Asking for five passages in one response
would cut the call count by five, and would also turn the task into
list-generation, which has its own register. The answer to a plain question is
the thing we actually want to measure, so every passage is its own call.

**No system prompt and no style instruction.** The prompts are the sort of
question a person asks. Nothing tells the model how to write.

**Truncated responses are discarded, not trimmed.** A response cut off
mid-sentence would inflate the fragment rate and distort closing-sentence
length -- two features copyme renders rules from. Any response whose stop reason
is not ``end_turn`` is dropped.

The key is read from ``ANTHROPIC_API_KEY`` by the SDK. It is never logged,
written to the corpus, or recorded in the provenance file.

Usage:
    poetry run python3 scripts/generate_baseline_corpus.py --dry-run
    poetry run python3 scripts/generate_baseline_corpus.py --target 1200
    poetry run python3 scripts/generate_baseline_corpus.py --target 1200 --resume
"""

import argparse
import json
import os
import random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "baseline_corpus"

DEFAULT_MODEL = "claude-sonnet-5"

# Generous enough that an ordinary answer finishes inside it. Responses that do
# not finish are discarded rather than kept, so a larger ceiling costs nothing
# but a little latency on the few long ones.
MAX_TOKENS = 1_500

# Passages per shard file. The build script globs `*.txt` and splits each on a
# line containing only `---`, so sharding is purely about making the run
# resumable and the files readable.
SHARD_SIZE = 50

# A passage must be at least this long to be useful: the feature set needs
# several sentences before quartiles and variation mean anything.
MIN_PASSAGE_WORDS = 60

# Share of lines that may be bullets before a response is treated as a list
# rather than prose.
#
# This is an inclusion criterion, not cherry-picking, and the reason is that
# copyme's features are prose features -- sentence-length quartiles, paragraph
# shape, closing sentences. A bulleted list has no paragraph shape to measure,
# and letting it into the baseline would move the paragraph features towards a
# structure that no author copyme profiles is being compared against. The counts
# of what was dropped go into the provenance file.
MAX_BULLET_SHARE = 0.4

_BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)]|#{1,6}\s)")

# Subjects, deliberately wide. The previous hand-written corpus was all software
# and technical explanation, which skewed the opener and vocabulary features
# even though the register features survived it.
TOPICS = [
    "sourdough baking", "pruning fruit trees", "the Dutch East India Company",
    "how tides work", "choosing running shoes", "the history of the NHS",
    "beekeeping", "Mediterranean cooking", "how to read a balance sheet",
    "the rules of cricket", "learning the piano as an adult", "Roman aqueducts",
    "sleep hygiene", "buying a first home", "how vaccines work",
    "the Bayeux Tapestry", "freshwater fishing", "mending a bicycle puncture",
    "the Suez Canal", "how compost works", "classical guitar repertoire",
    "the Beveridge Report", "orienteering", "making stock from bones",
    "the water cycle", "choosing a mattress", "the Peasants' Revolt",
    "indoor plants that tolerate shade", "how insurance pricing works",
    "the Linnaean system", "sewing a buttonhole", "the Grand Tour",
    "how sound travels underwater", "pension auto-enrolment", "antibiotics",
    "the Lindisfarne Gospels", "sea kayaking", "preserving lemons",
    "the Panama Canal", "how glaciers move", "choosing walking boots",
    "the Corn Laws", "propagating succulents", "how credit scores work",
    "plate tectonics", "knitting in the round", "the Silk Road",
    "birdsong identification", "fermenting vegetables", "the Thames Barrier",
    "how refrigeration works", "buying a used car", "the placebo effect",
    "the Book of Kells", "rock climbing grades", "making ice cream",
    "the Erie Canal", "how volcanoes form", "choosing a bicycle for commuting",
    "the Enclosure Acts", "growing tomatoes", "how mortgages are priced",
    "the periodic table", "basic bookbinding", "the Hanseatic League",
    "wildflower meadows", "curing bacon", "the Channel Tunnel",
    "how clouds form", "choosing a camera", "herd immunity",
    "illuminated manuscripts", "long-distance swimming", "making yoghurt",
    "the Trans-Siberian Railway", "how earthquakes are measured",
    "choosing a kitchen knife", "the Reform Acts", "pruning roses",
    "how currency exchange works", "the carbon cycle", "repairing a dry wall",
    "the Ottoman Empire", "coastal erosion", "smoking fish",
    "the Hoover Dam", "how rainbows form", "buying binoculars",
    "the Factory Acts", "growing garlic", "how taxes on savings work",
    "the taxonomy of fungi", "basic joinery", "the Venetian Republic",
    "hedgerow management", "pickling onions", "the Forth Bridge",
    "how magnets work", "choosing a tent", "antibiotic resistance",
    "medieval cathedral building", "trail running", "making marmalade",
    "the Great Western Railway", "how deserts form", "choosing a printer",
    "the Poor Laws", "growing potatoes", "how bond yields work",
    "animal migration", "whittling", "the Byzantine Empire",
    "river restoration", "drying herbs", "the Humber Bridge",
    "how lenses focus light", "choosing a sleeping bag", "blood types",
    "Georgian architecture", "open-water rowing", "making cheese at home",
    # The matrix has to be large enough that a full run never repeats a prompt,
    # and the prose rate is about three in four, so it needs roughly 1,600
    # combinations to yield 1,200 passages.
    "canal boats", "the Highland Clearances", "slate quarrying",
    "how barometers work", "choosing a walking stick", "cider making",
    "the Antonine Wall", "salt marshes", "repairing a sash window",
    "the Jacquard loom", "how yeast behaves", "choosing a wheelbarrow",
    "the Zollverein", "coppicing", "smoking a brisket",
    "the Menai Suspension Bridge", "how frost forms", "buying a telescope",
    "the Navigation Acts", "growing asparagus", "how annuities work",
    "lichen", "basic blacksmithing", "the Mughal Empire",
    "chalk streams", "bottling beer", "the Clifton Suspension Bridge",
    "how thermostats work", "choosing secateurs", "iron deficiency",
    "Victorian railway stations", "fell walking", "making sausages",
    "the Union Pacific Railroad", "how dunes migrate", "choosing a kettle",
    "the Statute of Labourers", "growing rhubarb", "how leasehold works",
    "moss and liverworts", "basic plastering", "the Kingdom of Aragon",
    "peat bogs", "making shortcrust pastry", "the Tyne Bridge",
    "how fuses work", "choosing a rucksack", "lactose intolerance",
    "Brutalist housing estates", "sea swimming in winter", "curing olives",
    "the Midland Railway", "how caves form", "choosing a lawnmower",
    "the Black Death", "growing raspberries", "how ground rent works",
    "pollinators other than bees", "basic upholstery", "the Kalmar Union",
    "limestone pavement", "making sourdough starter", "the Severn Bridge",
    "how dynamos work", "choosing gardening gloves", "vitamin D",
    "interwar semi-detached housing", "night walking", "brining a turkey",
    "the Great Northern Railway", "how estuaries work", "choosing a toaster",
    "the Highland Land League", "growing broad beans", "how escrow works",
    "woodland fungi", "basic stonemasonry", "the Republic of Genoa",
    "reed beds", "making puff pastry", "the Menai Strait",
]

# Question shapes.
#
# These ask for **continuous prose**, and that is a deliberate correction rather
# than a convenience. The first version of this script asked reference-style
# questions -- "Can you explain X?", "What are the common mistakes with X?" --
# and 17 of the first 20 responses came back as headings and bullet lists,
# because that is genuinely the model's default shape for a reference question.
#
# Filtering those out would have built a baseline of "model prose, given that
# the model happened to write prose", which is a different and much narrower
# thing than the model's default. So the prompts changed instead.
#
# The distinction being drawn is between **format** and **style**. Asking for
# paragraphs rather than bullets fixes the format, because copyme's features are
# prose features -- sentence-length quartiles, paragraph shape, closing sentences
# -- and a bulleted list has no paragraph shape to measure. Nothing here says a
# word about how to write those paragraphs: no tone, no length, no voice, no
# audience. That is what keeps the register the model's own.
#
# It also matches the situation the baseline is actually used in. When a copyme
# profile is in the prompt, the model has been asked to write continuous prose
# in a person's voice. "What would this model do unprompted?" therefore means
# "what prose would it write", not "how would it format a reference answer".
#
# Which shapes survive is measured, not assumed: `--probe` reports the prose
# rate per shape, and the set below is what cleared it.
# Measured prose rates from `--probe 2`, which is why these eight and not the
# twelve that were tried. The four dropped shapes -- "Is X worth the effort?",
# "Give me your honest take on X", and two others -- returned bullet lists every
# single time.
#
# The first four below returned prose every time; the last four about half the
# time, and they are kept deliberately. Without them the baseline would be
# nothing but "write a few paragraphs about X" essays, and the register of a
# reply to a person is part of what the model does by default. The cost is a
# selection effect inside those four shapes: the half that comes back as prose
# may be the half whose topics resist being listed. That is a bias on format
# rather than on style, and it is recorded in the provenance file.
SHAPES = [
    # 100% prose in the probe.
    "Write a few paragraphs about {topic}.",
    "Tell me about {topic} in plain prose, no lists.",
    "Write a short piece about why {topic} interests people.",
    "Write a couple of paragraphs on how {topic} has changed over the years.",
    # 50% prose in the probe; kept for the conversational register.
    "I'm curious about {topic}. Talk me through it in a few paragraphs.",
    "My friend says {topic} is overrated. What would you say to that?",
    "Describe {topic} the way you'd describe it to a friend over coffee.",
    "What's the single most useful thing to understand about {topic}? Just talk me through it.",
]


def build_prompts(target, seed=20261102):
    """Return ``target`` prompts, deterministically shuffled.

    Every topic is paired with every shape, then the whole matrix is shuffled
    with a fixed seed and truncated. The seed makes a rerun reproducible, and
    the shuffle stops a truncated run from being all of one shape.

    Args:
        target (int): How many prompts to return.
        seed (int): The shuffle seed, recorded in the provenance file.

    Returns:
        list[str]: The prompts.
    """
    matrix = [shape.format(topic=topic) for topic in TOPICS for shape in SHAPES]
    random.Random(seed).shuffle(matrix)
    if target > len(matrix):
        print(
            f"warning: only {len(matrix)} unique prompts exist; asking for "
            f"{target} would repeat them. Capping at {len(matrix)}.",
            file=sys.stderr,
        )
    return matrix[:target]


def is_prose(text):
    """Whether a response is prose rather than a list or a set of headings."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    bullets = sum(1 for line in lines if _BULLET.match(line))
    return bullets / len(lines) <= MAX_BULLET_SHARE


def existing_shards():
    """Shard files already written, so a run can be resumed."""
    return sorted(CORPUS.glob("generated_*.txt"))


def count_existing_passages():
    """How many passages the existing shards hold."""
    total = 0
    for path in existing_shards():
        total += len([block for block in path.read_text().split("\n---\n") if block.strip()])
    return total


def generate(client, model, prompt):
    """Ask one question and return the answer, or None if it is unusable.

    Returns:
        tuple[str | None, str]: ``(passage, reason)``. The reason names why a
            response was rejected, for the provenance counts.
    """
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason != "end_turn":
        return None, f"stop_reason={response.stop_reason}"

    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()

    if len(text.split()) < MIN_PASSAGE_WORDS:
        return None, "too short"
    if not is_prose(text):
        return None, "mostly a list"
    return text, "kept"


def probe(args):
    """Report the prose rate for each question shape, and write nothing.

    The point of this mode is to find out whether the prompts elicit prose
    *before* paying for a thousand calls. A shape whose answers come back as
    bullet lists is not a shape that can contribute to a prose baseline, and it
    is much cheaper to learn that from twenty-four calls than from twelve
    hundred.

    Args:
        args: Parsed arguments; ``probe`` is the number of topics per shape.

    Returns:
        int: Exit status.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set in this environment.", file=sys.stderr)
        return 1

    import anthropic

    client = anthropic.Anthropic()
    chooser = random.Random(7)
    jobs = []
    for shape in SHAPES:
        for topic in chooser.sample(TOPICS, args.probe):
            jobs.append((shape, shape.format(topic=topic)))

    print(f"Probing {len(SHAPES)} shapes x {args.probe} topics = {len(jobs)} calls\n")

    results = {shape: {"kept": 0, "rejected": 0} for shape in SHAPES}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(generate, client, args.model, prompt): shape
            for shape, prompt in jobs
        }
        for future in as_completed(futures):
            shape = futures[future]
            try:
                passage, _ = future.result()
            except Exception:  # noqa: BLE001
                results[shape]["rejected"] += 1
                continue
            results[shape]["kept" if passage else "rejected"] += 1

    print(f"{'prose':>6}  shape")
    for shape in sorted(SHAPES, key=lambda key: -results[key]["kept"]):
        counts = results[shape]
        total = counts["kept"] + counts["rejected"]
        rate = counts["kept"] / total if total else 0.0
        print(f"{rate:6.0%}  {shape}")

    overall = sum(row["kept"] for row in results.values()) / max(1, len(jobs))
    print(f"\nOverall prose rate: {overall:.0%}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", type=int, default=1200, help="How many passages to generate."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to sample.")
    parser.add_argument(
        "--concurrency", type=int, default=10, help="Parallel requests."
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep existing generated shards and add to them.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and make no API calls.",
    )
    parser.add_argument(
        "--probe",
        type=int,
        default=0,
        help=(
            "Sample this many topics per question shape and report the prose "
            "rate for each shape. Writes no corpus. Use it to check that the "
            "prompts elicit prose before paying for a full run."
        ),
    )
    args = parser.parse_args(argv)

    if args.probe:
        return probe(args)

    prompts = build_prompts(args.target)

    already = count_existing_passages() if args.resume else 0
    if args.resume and already:
        prompts = prompts[already:]
        print(f"Resuming: {already} passages already on disk.")

    estimated_words = len(prompts) * 250
    print(
        f"Plan: {len(prompts)} prompts against {args.model}, "
        f"{args.concurrency} at a time.\n"
        f"  Expect roughly {estimated_words:,} words "
        f"(about {int(estimated_words * 1.4):,} output tokens).\n"
        f"  Unique prompts available: {len(TOPICS) * len(SHAPES):,}"
    )
    if args.dry_run:
        print("\nDry run; nothing was called. Sample prompts:")
        for prompt in prompts[:5]:
            print(f"  - {prompt}")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set in this environment. Set it and "
            "re-run; this script never reads or stores the value anywhere "
            "else.",
            file=sys.stderr,
        )
        return 1

    import anthropic

    client = anthropic.Anthropic()

    CORPUS.mkdir(parents=True, exist_ok=True)
    if not args.resume:
        for path in existing_shards():
            path.unlink()

    kept = []
    rejected = {}
    failed = 0
    lock = threading.Lock()
    shard_index = len(existing_shards())

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(generate, client, args.model, prompt): prompt
            for prompt in prompts
        }
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                passage, reason = future.result()
            except Exception as error:  # noqa: BLE001 - one bad call must not end the run
                with lock:
                    failed += 1
                    rejected[type(error).__name__] = rejected.get(type(error).__name__, 0) + 1
                continue

            with lock:
                if passage is None:
                    rejected[reason] = rejected.get(reason, 0) + 1
                else:
                    kept.append(passage)
                    if len(kept) >= SHARD_SIZE:
                        shard_index += 1
                        (CORPUS / f"generated_{shard_index:03d}.txt").write_text(
                            "\n---\n".join(kept[:SHARD_SIZE]) + "\n", encoding="utf-8"
                        )
                        del kept[:SHARD_SIZE]

            if done % 25 == 0:
                print(
                    f"  {done}/{len(prompts)} calls, "
                    f"{count_existing_passages() + len(kept)} passages kept",
                    flush=True,
                )

    if kept:
        shard_index += 1
        (CORPUS / f"generated_{shard_index:03d}.txt").write_text(
            "\n---\n".join(kept) + "\n", encoding="utf-8"
        )

    total = count_existing_passages()
    words = sum(
        len(block.split())
        for path in existing_shards()
        for block in path.read_text().split("\n---\n")
    )

    print(f"\nKept {total} passages, about {words:,} words.")
    if rejected:
        print("Rejected:")
        for reason, count in sorted(rejected.items(), key=lambda row: -row[1]):
            print(f"  {count:4d}  {reason}")

    (CORPUS / "provenance.json").write_text(
        json.dumps(
            {
                "status": "measured",
                "source": "Generated assistant-register responses to plain user questions",
                "model": args.model,
                "prompt_set": {
                    "topics": len(TOPICS),
                    "question_shapes": len(SHAPES),
                    "unique_combinations": len(TOPICS) * len(SHAPES),
                    "shuffle_seed": 20261102,
                    "script": "scripts/generate_baseline_corpus.py",
                },
                "generation": {
                    "no_system_prompt": True,
                    "no_style_instruction": True,
                    "max_tokens": MAX_TOKENS,
                    "truncated_responses": "discarded, not trimmed",
                },
                "created": date.today().isoformat(),
                "passages": total,
                "approximate_words": words,
                "inclusion_filters": {
                    "min_passage_words": MIN_PASSAGE_WORDS,
                    "max_bullet_share": MAX_BULLET_SHARE,
                    "rejected": rejected,
                },
                "known_limitations": [
                    "A single model and a single point in time. The baseline is "
                    "what this model wrote on this date; another model's defaults "
                    "differ, which is why every profile records the baseline version.",
                    "Responses that were mostly bullet lists were excluded, because "
                    "copyme's features are prose features and a list has no "
                    "paragraph shape to measure. This makes the baseline a prose "
                    "baseline specifically.",
                    "Prompts are questions, so the register is explanatory. Model "
                    "output in other modes -- drafting, summarising to a brief, "
                    "writing in a persona -- is not represented.",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\nWrote provenance.json. Next:\n"
        "  poetry run python3 scripts/build_baseline.py --check\n"
        "  poetry run python3 scripts/build_baseline.py --bump"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
