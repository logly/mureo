"""The dashboard's display contract models (#706).

Split out of :mod:`mureo.context.models` for the reason
:mod:`mureo.context.display_codec` was split out of the codec: that file is
at the repo's size limit. :mod:`mureo.context.models` re-exports every class
here, so ``from mureo.context.models import DisplayContract`` keeps working
and is still the path the codecs import from.

Dependency-free like the rest of the models: nothing from
:mod:`mureo.context` or :mod:`mureo.core` is imported at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DisplayHighlight:
    """One chip on a client's card (#706).

    ``tone`` is a closed vocabulary
    (:data:`~mureo.core.display_contract.HIGHLIGHT_TONES`) because it is
    rendered as a colour, and a tone no view knows is a chip no view draws.
    """

    tone: str
    text: str


@dataclass(frozen=True)
class DisplayProposal:
    """One thing mureo proposes doing, or has done (#706).

    Only ``title`` is required — a proposal with nothing but a title is a
    real proposal, while a body, a status or a date can each legitimately be
    absent. ``status`` is closed
    (:data:`~mureo.core.display_contract.PROPOSAL_STATUSES`); ``date`` is
    displayed and never parsed, so no format is imposed on it.
    """

    title: str
    body: str | None = None
    status: str | None = None
    date: str | None = None


@dataclass(frozen=True)
class DisplayBreakdownRow:
    """One row of a campaign / ad-group breakdown table (#706).

    ``name`` is required and everything else is optional, because a row for
    an entity with no conversions honestly has no ``mcpa`` and a platform
    with no target has no ``target_cpa`` — and a missing figure must stay
    distinguishable from a zero. The three figures are numbers, never
    formatted strings: the table renders them, so a string is rendered as
    nothing.
    """

    name: str
    spend: float | None = None
    mcpa: float | None = None
    target_cpa: float | None = None
    state: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class DisplayBreakdown:
    """The two breakdown tables a report may state (#706).

    A pair rather than one list keyed by level: the two are shown as two
    tables, an ad group's name means nothing without knowing it is an ad
    group, and a caller cannot forget to say which it wrote.
    """

    campaigns: tuple[DisplayBreakdownRow, ...] = ()
    adgroups: tuple[DisplayBreakdownRow, ...] = ()

    def __post_init__(self) -> None:
        """Ensure both tables are tuples (defensive copies)."""
        if not isinstance(self.campaigns, tuple):
            object.__setattr__(self, "campaigns", tuple(self.campaigns))
        if not isinstance(self.adgroups, tuple):
            object.__setattr__(self, "adgroups", tuple(self.adgroups))

    def __bool__(self) -> bool:
        """Empty when neither table has a row.

        Used by the codec to decide whether ``breakdown`` is emitted at all,
        so a contract that states no table gains no key.
        """
        return bool(self.campaigns or self.adgroups)


@dataclass(frozen=True)
class DisplayStatedValue:
    """One labelled figure in the chip row (#706).

    ``value`` is a number or a SHORT string — see
    :func:`~mureo.core.display_contract.validate_display_contract`, which
    refuses prose here. Both types are kept as written: mureo does not know
    the unit, so re-deriving the figure would print a different number from
    the one the report stated.
    """

    label: str
    value: float | int | str


@dataclass(frozen=True)
class DisplayContract:
    """What the dashboard reads for one client (#706).

    STATE.json is the agent's working memory and is prose-heavy by design.
    This section is the other audience: a small, strictly structured surface
    written under the bounds in :mod:`mureo.core.display_contract`, which
    refuse an over-long or off-vocabulary write rather than truncating it.

    Every field is optional, and the whole section is optional on the
    document — so a STATE.json written before this existed parses unchanged
    and gains no key on the next write.

    Deliberately NOT here: the KPI funnel (spend → impressions → clicks →
    conversions, with CPM / CPC / CPA) and the daily chart. Both are
    computed from the canonical totals and ``PlatformState.daily`` (#690),
    so no agent writes them and no agent can state them wrongly.
    """

    nav_message: str | None = None
    highlights: tuple[DisplayHighlight, ...] = ()
    proposals: tuple[DisplayProposal, ...] = ()
    breakdown: DisplayBreakdown = field(default_factory=DisplayBreakdown)
    stated_values: tuple[DisplayStatedValue, ...] = ()
    # Who wrote this screen, and when. Appended after every pre-attribution
    # field, the positional-compatibility rule ``ActionLogEntry`` follows.
    #
    # The contract is replaced wholesale by whoever writes it last — a screen
    # is one moment, and merging two runs produces a moment that never
    # happened. The cost of that is that a reader cannot tell whose answer
    # survived, and these two fields are that cost paid off: the card names
    # its author and its age, so a section a later run replaced is still
    # attributable rather than merely gone.
    #
    # ``source`` is required alongside any section that renders (see
    # :func:`~mureo.core.display_contract.validate_display_contract`);
    # ``generated_at`` is stamped SERVER-side (the #460 rule), so a drifted
    # client clock can never be persisted and read back as when the screen
    # was written. Both are ``None`` on a contract written before they
    # existed, which is why neither is enforced on READ.
    source: str | None = None
    generated_at: str | None = None

    def __post_init__(self) -> None:
        """Ensure every collection is a tuple (defensive copies)."""
        for name in ("highlights", "proposals", "stated_values"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def __bool__(self) -> bool:
        """Empty when the contract states nothing.

        The codec emits ``display`` only for a non-empty contract, so a
        document that has never had one stays byte-stable on round-trip and
        a cleared contract leaves no key behind to be read as a live one.

        ``source`` / ``generated_at`` deliberately do NOT count: they say who
        drew a screen, and there is no screen without a section. Counting
        them would let a cleared contract survive as an attributed blank.
        """
        return bool(
            self.nav_message
            or self.highlights
            or self.proposals
            or self.breakdown
            or self.stated_values
        )


__all__ = [
    "DisplayBreakdown",
    "DisplayBreakdownRow",
    "DisplayContract",
    "DisplayHighlight",
    "DisplayProposal",
    "DisplayStatedValue",
]
