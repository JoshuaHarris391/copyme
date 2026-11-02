"""The generic-prose baseline: what a model writes when nobody asks it to.

Two jobs depend on this file.

**Rule suppression.** A feature within half a standard deviation of the baseline
produces no rule, because the model's default is already right and every extra
line dilutes the ones that matter.

**Distinctiveness.** A passage far from the baseline shows habits the model would
not otherwise have, which is what makes it worth spending exemplar budget on.

The baseline holds feature means and spreads only -- numbers, feature names and a
version. No text from the corpus ships in the package. It carries a version so a
profile built a year ago can record which baseline it was measured against, and
the corpus it was computed from lives in ``tests/fixtures/baseline_corpus/``
with its own provenance.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .features import FEATURE_NAMES

BASELINE_PATH = Path(__file__).resolve().parent / "data" / "baseline.json"

# Below this many standard deviations from the baseline, a feature is indistinct
# from generic prose and yields no rule.
SUPPRESSION_THRESHOLD = 0.5

# A feature whose baseline spread is zero carries no information about how
# unusual a value is, so it is held out of distance maths rather than dividing
# by a floor and dominating the result.
_MIN_SPREAD = 1e-9

_cache = {}


class BaselineUnavailableError(RuntimeError):
    """Raised when the baseline file is missing or unreadable.

    Distinctiveness and rule suppression both need it at import time, so the
    package ships it. A missing file means a broken installation, not a
    situation to work around silently.
    """


@dataclass(frozen=True)
class Baseline:
    """Feature means and spreads for generic model-written prose.

    Attributes:
        version (str): Monotonic version, recorded in every profile.
        status (str): ``"provisional"`` or ``"measured"``. Provisional means the
            numbers are good enough to rank and suppress, not to publish.
        means (dict): Feature name to mean.
        spreads (dict): Feature name to standard deviation.
        passages (int): How many passages the numbers were computed over.
    """

    version: str
    status: str
    means: dict
    spreads: dict
    passages: int

    def spread(self, name):
        """float: The spread for ``name``, or 0.0 if the feature is unknown."""
        return float(self.spreads.get(name, 0.0))

    def z(self, name, value):
        """How many standard deviations ``value`` sits from the baseline mean.

        Args:
            name (str): A feature name.
            value (float): The author's or the generated text's value.

        Returns:
            float: The signed z-score. 0.0 where the feature has no usable
                spread, which reads as "no evidence this is unusual".
        """
        spread = self.spread(name)
        if spread <= _MIN_SPREAD:
            return 0.0
        return (float(value) - float(self.means.get(name, 0.0))) / spread

    def is_distinct(self, name, value, threshold=SUPPRESSION_THRESHOLD):
        """Whether a value differs from generic prose enough to be worth saying."""
        return abs(self.z(name, value)) >= threshold

    def vector(self):
        """list[float]: The baseline means in :data:`FEATURE_NAMES` order."""
        return [float(self.means.get(name, 0.0)) for name in FEATURE_NAMES]

    def distance_from(self, scalars):
        """Standardised Euclidean distance from the baseline.

        Each feature is divided by its own baseline spread before the distance is
        taken, so a rate measured per 1,000 words cannot outweigh a ratio
        measured between zero and one purely because its numbers are larger.

        Args:
            scalars (dict): Feature name to value.

        Returns:
            float: The distance, in standard deviations, averaged over the
                features that have a usable spread.
        """
        total = 0.0
        counted = 0
        for name in FEATURE_NAMES:
            if name not in scalars:
                continue
            if self.spread(name) <= _MIN_SPREAD:
                continue
            total += self.z(name, scalars[name]) ** 2
            counted += 1
        if not counted:
            return 0.0
        return math.sqrt(total / counted)


def load_baseline(path=None):
    """Load and cache the baseline.

    Args:
        path (str | pathlib.Path, optional): Override the packaged file, for
            tests and for the build script's own verification.

    Returns:
        Baseline: The loaded baseline.

    Raises:
        BaselineUnavailableError: If the file is missing or malformed.
    """
    resolved = Path(path) if path is not None else BASELINE_PATH
    key = str(resolved)
    if key in _cache:
        return _cache[key]

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BaselineUnavailableError(
            f"No baseline at {resolved}. The package ships one; regenerate it "
            f"with 'poetry run python3 scripts/build_baseline.py'."
        ) from error
    except json.JSONDecodeError as error:
        raise BaselineUnavailableError(
            f"The baseline at {resolved} is not valid JSON: {error}"
        ) from error

    baseline = Baseline(
        version=str(payload.get("version", "0")),
        status=str(payload.get("status", "provisional")),
        means=dict(payload.get("means", {})),
        spreads=dict(payload.get("spreads", {})),
        passages=int(payload.get("passages", 0)),
    )
    _cache[key] = baseline
    return baseline
