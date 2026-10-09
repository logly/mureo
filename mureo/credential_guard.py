"""Shared PreToolUse credential-guard hook templates (#393).

Single source of truth for the guard hooks installed into Claude Code's
``~/.claude/settings.json`` and Codex's ``~/.codex/hooks.json``.  The two
installers previously carried copy-pasted templates, which is how the
non-blocking ``sys.exit(1)`` bug shipped to both hosts.

Blocking contract (identical for Claude Code and Codex): a PreToolUse hook
blocks by printing ``{"hookSpecificOutput": {"permissionDecision": "deny",
...}}`` to stdout and exiting 0, or by exiting 2 with the reason on stderr.
Any other non-zero exit — including 1 — is a *non-blocking* hook error and
the tool call proceeds.  The deny-JSON form is used here because an
interpreter crash (exit 1) can never be mistaken for an intentional block.

Two guards are installed:

* Path guard (``Read|Edit|Write|Grep|Glob|NotebookEdit``): denies when
  *either* the realpath-resolved target (``os.path.realpath`` after
  ``expanduser``) *or* the logical target (``os.path.abspath`` after
  ``expanduser``, no symlink resolution) lands inside ``~/.mureo``. The
  realpath check closes the outside-in evasion (a link outside the dir that
  resolves into it); the logical check closes the inside-out evasion (a
  ``~/.mureo/credentials.json`` that is itself a symlink pointing OUT — its
  realpath escapes the dir, but the requested path is still under it). Both
  cover every file in the directory, not just ``credentials.json``.
* Bash guard: normalizes the command *once* into the text a shell would
  read after quoting, line continuations and expansions are resolved, and
  applies four rules to it.  Any one of them denies.  Rules 1 and 2 read
  the directory name, rules 3 and 4 the two things a search that never
  spells the directory does write down.

  "Once" means one pass producing *sets* of readings — the command with its
  expansions taken out of its structure, the body of each expansion, and
  then every string brace expansion makes of those, read both the way this
  shell reads a quoted metacharacter and the way the next shell along does
  — and every rule runs against every reading it is entitled to.  What is
  forbidden is a rule that owns a string of its own; see below.

  The single reading is the load-bearing part, and it was learned the
  expensive way.  Earlier versions had one rule scanning the raw command
  and another scanning the folded text; every obfuscation one of them
  resolved was invisible to the other, so each new fold opened a new hole
  on the axis the other rule owned.  ``D=~/; cat $D.mu\\<newline>reo/…``
  reads the file: the continuation was folded away in the text the
  pattern rule read, while the rule that knew about ``$D`` was still
  looking at the raw command.  Nothing here may reintroduce a second
  reader.  If a rule needs information the fold destroys, the fold has to
  preserve it — which is what ``_COLLAPSE`` does for expansion
  boundaries — rather than the rule reaching for a different string.

  Rule 3 reads the raw text too, and that is not the thing this paragraph
  forbids — read this before adding another rule that does the same,
  because the difference is the whole point.  The split-brain bug was
  *partition*: each rule owned one string and was blind to the other, so
  an obfuscation resolved on one axis walked past the rule that owned the
  other.  Rule 3 is a *union* — it runs against the readings AND the raw
  command, so nothing is invisible to it and no fold can open a hole
  underneath it.  It also does not want anything the fold destroys: it
  looks for a pattern that a program other than the shell will expand,
  and the fold models the shell alone, so there is nothing for
  ``_COLLAPSE`` to preserve on its behalf.  A rule reading the raw text
  *instead of* the readings would be the old bug returning.

  Rule 1 (the name spelled out) denies when the normalized text contains
  ``.mureo`` where a path component could *start*.  Anchoring on the
  directory name rather than on ``credentials`` also covers a wildcard
  that follows the name (``cat ~/.mureo/cred*``).  Rule 2 below covers a
  metacharacter placed *inside* the name.  Because both read the
  normalized text, a name that only becomes contiguous once the shell has
  worked on it — ``.mure"o"``, ``.mur'e'o``, ``.mu\\<newline>reo``,
  ``$D.mureo`` — is as visible to them as one written out.

  A bare substring test over-blocks badly, because case-folded ``.mureo``
  is also a prefix of things that are emphatically not the directory:
  mureo's own browser globals (``window.MUREO_REPORTS_FORMAT``) and every
  hostname under the project's domain (``pkgs.mureo.jp``,
  ``docs.mureo.jp``).  Naming either one in a commit message, a release
  note or a PR body was denied outright.

  What separates those from a real reference is what comes *before*: a
  path component named ``.mureo`` always starts at a boundary — after
  ``/``, ``~``, a quote, whitespace, or the start of the string — whereas
  the false positives are preceded by an identifier character that belongs
  to a longer name (``window``, ``pkgs``).  So the guard denies when the
  substring is at the start of the command or preceded by a non-identifier
  character.

  That boundary test would be too weak on the raw command, because an
  identifier character can also be the tail of a *substitution* that
  supplies the parent directory: with ``D=~/``, the command ``cat
  $D.mureo/credentials.json`` resolves into the protected directory while
  putting ``D`` immediately before the name.  The same applies one level
  up, to a format specifier a program will fill in (``printf
  '%s.mureo/...' ~/``).

  This is where an earlier design added a *second rule* over the raw text,
  and where the split-brain bugs came from.  Normalization handles it
  instead: an expansion becomes ``*/`` and swallows the identifier run
  that names it, so ``$D.mureo``, ``${D}.mureo``, ``$1.mureo`` and
  ``%s.mureo`` all read as ``*/.mureo``.  The dot then sits after a
  non-identifier character, exactly as it does in ``~/.mureo``, and the
  one boundary test sees every one of them — including when the name is
  *also* broken up, which is what the two-rule version could not do.

  Nothing that names the directory in plain path syntax is admitted by
  this: sibling directories (``~/.mureoX``, ``~/.mureo_backup``) still
  deny, since only the text before the name is consulted.

  Rule 2 (the name written as a pattern).  A metacharacter inside the name
  breaks rule 1's six-character literal while the shell still expands the
  pattern onto the real directory: ``cat ~/.mure?/credentials.json``
  prints the credentials file, and so do ``.[m]ureo``, ``.mur*``,
  ``.m?reo``, ``.?????``, ``.[!.]*`` and the brace form ``.mure{o,x}``
  (each run against bash 5.2 with a throwaway ``HOME``).  No pattern over
  the command text can decide this, because the string that reaches the
  filesystem does not exist yet — so the guard asks the question the other
  way round.  It takes the path components of the normalized command,
  keeps those beginning at a component boundary with a literal ``.`` and
  containing a metacharacter, and denies when ``fnmatch`` says the pattern
  matches ``.mureo``.

  Requiring the literal leading ``.`` is what makes that safe to do.  A
  shell will not let a wildcard match the leading period of a filename
  unless ``dotglob`` is set, so ``ls *``, ``rm -rf build/*`` and
  ``tests/*.py`` cannot reach ``.mureo`` and are never candidates.
  Without that restriction the rule would have to deny every glob anyone
  types, ``fnmatch('.mureo', '*')`` being true.

  Rules 1 and 2 both read the *directory* name, and for a long time that
  was all the guard read.  It meant a command that never spelled the
  directory at all walked straight past: ``find ~ -path '*mureo*' -exec
  cat {} ;`` and ``find ~ -name credentials.json -exec cat {} ;`` both
  printed the credentials, with no obfuscation and no adversarial intent
  required.  "Look for any leftover credential files under my home
  directory" is an ordinary instruction, and it is exactly the accident
  this guard exists for.  Rules 3 and 4 read the two things such a command
  does write down.

  Rule 3 (a pattern reaching into the name without the dot).  Rule 2 only
  considers components that begin with a literal ``.``, so ``*mureo*`` —
  which ``find -path`` happily matches against the full path, leading
  period included — was not a candidate.  Rule 3 denies when a glob
  metacharacter stands immediately before the literal ``mureo``.  It is
  deliberately narrower than "any pattern that could match": ``mureo`` has
  to be written out, so working inside a checkout of this very repository
  (``grep -r foo mureo/``) is untouched, while ``-path '*mureo*'`` and
  ``-name '*mureo*'`` are not.

  Rule 3 reads the raw command text as well as the normalized readings,
  and that is the point of it.  Normalization models what the *shell*
  expands, so it neutralizes a quoted ``*`` — correctly, for the shell.
  But the quotes in ``-path '*mureo*'`` are there precisely to keep the
  shell off the pattern so that ``find`` can expand it itself, and by the
  time the normalized reading exists the pattern has become ``=mureo=``
  and there is nothing left to match.  A pattern meant for a downstream
  program is written literally in the command; that is where rule 3 looks
  for it.  Every other rule stays on the normalized readings, because
  every other rule is about what the shell will do.

  Rule 4 (the protected filenames).  A tree search can name the file
  instead of the directory, so the filenames are candidates in their own
  right — but only where the name stands on its own, with no ``/`` before
  it.  That restriction is the rule.  A name with a path in front of it is
  not a search but a specific file, and which file it is has already been
  settled by rules 1 to 3 from the directory: ``~/.mureo/credentials.json``
  denies on rule 1, while ``~/backups/credentials.json`` is the user's own
  file and refusing it would be the guard overreaching into a directory it
  does not protect.  Without the restriction the rule also contradicted
  three cases this file already reasons about and allows —
  ``cat "$HOME/.mure?/credentials.json"`` and the two fully-quoted paths —
  where the name is written but the shell cannot reach the directory.

  ``config.json`` is deliberately NOT among them.  It is one of the most
  common filenames in software, and denying it would stop ``cat
  config.json`` in every project the agent ever works in — the guard is
  judged by whether it makes the common accident less likely *without
  blocking real work*, and that trade lands the wrong way.  The cost is
  stated rather than hidden: ``find ~ -name config.json -exec cat {} ;``
  still reads that one file.  The names that are matched are specific
  enough that a project file colliding with one is rare, and when it does
  the deny reason says to use the Read tool, which is guarded by path and
  so allows a same-named file anywhere outside ``~/.mureo``.

  Normalization produces those readings, and it is a left fold over the
  characters with a five-state quoting automaton — unquoted, single-quoted,
  double-quoted, and the two escaped states — because that is the only way
  to get quoting right.  An earlier version stripped quoted spans with two
  regex passes and had the defect that shape invites: in ``echo "it's" ;
  cat ~/.mure?/x 'x'`` the single-quote pass read the apostrophe of
  ``it's`` as an opening delimiter, paired it with the unrelated ``'x'``
  at the end of the line, and deleted the real pattern sitting between
  them.  The fold cannot make that mistake, and it also gets ``echo
  it\\'s`` right, where an escaped quote is not a delimiter at all.

  The fold rewrites eight things:

  - quote delimiters are dropped, so the text reads as the shell will read
    it (this is what catches ``~/.mure"o"``);
  - a line continuation — a backslash with a newline after it — is dropped
    whole, both characters, because that is what a shell does with the
    pair before it tokenises anything.  ``cat ~/.mu\\<newline>reo/…``
    prints the credentials file, and so do ``.\\<newline>mureo``,
    ``.mure\\<newline>?`` and the same spellings inside double quotes.
    Keeping the newline was enough to stop the name ever being contiguous.
    Inside *single* quotes a backslash is an ordinary character, so there
    is no continuation there and none is normalized away;
  - a *quoted* metacharacter becomes ``=``, because quoting makes it an
    ordinary character and no ordinary character in ``.mureo`` is a
    metacharacter.  That is why ``sed 's/.*//'`` and ``find . -name '.*'``
    are a regex and a literal rather than globs, and why ``cat
    "$HOME/.mure?/x"`` — which opens nothing — is allowed while the
    unquoted spelling is denied.  The placeholder has to be a character
    that reads as a *boundary*: it was ``_`` once, and since ``_`` is an
    identifier character, ``'{}.mureo'`` folded to ``__.mureo`` and the
    boundary test saw one long name rather than the directory.  This is the
    one rewrite the fold does *twice*, once each way; see the second reading
    below for the question the collapse is the wrong answer to;
  - the start of an expansion (``$``, backtick, ``%``) becomes ``*/`` and
    swallows the identifier run naming it: ``*`` because its text is
    unknown, ``/`` because its extent is unknown too, so what follows
    cannot be assumed to continue the same path component, and swallowing
    ``D`` in ``$D`` so the expansion reads as one unknown thing.  ``%`` is
    an expansion in every state, quoted or not, because the program that
    fills it in is the next one along, not this shell;
  - a quoted span containing ``%`` keeps its metacharacters live, because
    such a span is a template rather than text: ``printf
    '%s.mure?/x'`` builds a name whose ``?`` the shell then globs.  The
    flag resets at the end of the span, so a ``%`` in one argument cannot
    animate the metacharacters of a later one — ``echo "100%" ; sed
    's/.*//'`` is still allowed.
  - from an unquoted ``<<`` to the end of the command, quoting is not
    resolved at all.  Bash resolves none in the body of a here-document: a
    ``'`` or ``"`` there is ordinary body text, so a body containing an
    apostrophe does not open a quoted span, and the text after the body is
    read exactly as unquoted as it is.  The latch is one-way and does not
    look for the delimiter, deliberately.  Erring *long* means the guard
    declines to resolve quoting somewhere bash would have, which can only
    leave more text visible to the rules; erring short means resolving
    quoting bash does not resolve, and the body of a here-document is
    precisely where unbalanced quotes are ordinary.  A here-string
    (``<<<``), a ``<<`` inside a comment and a left shift inside ``$(( ))``
    all match it, and that is intended: what they lose is quote resolution,
    and losing it is the safe direction.  One transition survives inside
    the latch — a backslash still escapes the character after it, so a line
    continuation is still removed as a pair.  Bash removes it in an
    unquoted body, and in a quoted one the pair reaches whatever program
    consumes the body, which removes it then; either way the two characters
    are not part of a name.
  - a separator the shell is allowed to act on becomes a placeholder, and
    two of them: one for whitespace, one for ``;`` ``|`` ``&`` ``(`` ``)``
    ``<`` ``>``.  Where one word ends and the next begins is a question
    about *quoting*, not about which characters are present — a quoted
    space is ordinary text in the middle of a word, an unquoted one ends
    it — so it is the fold that answers it, once, and the brace step reads
    the answer off the placeholders instead of asking again.  The two kinds
    are kept apart because the brace step treats them differently; see
    below.  Nothing else in the text means anything but itself, so the
    placeholders are control characters, and any of them arriving in the
    command is replaced on the way in: a command must not be able to write
    one and claim a boundary the shell would not make.  The same goes for
    the two the brace step uses for the braces of a span the shell leaves
    literal — chr(1) to chr(4), four in all, none writable by the command;
  - inside the body of a here-document the second kind is not a separator
    at all.  Bash reads no operator in a body, so ``(`` ``)`` ``;`` ``|``
    ``&`` ``<`` ``>`` there are ordinary characters in the middle of
    whatever language the body is written in, exactly as a quoted one is on
    a command line.  Whitespace stays a separator, because a body is still a
    run of lines and two braces on different lines of one are not a group.
    Reading a body's punctuation as a command line's made an everyday short
    script — a dict holding a call, an SQL statement, a javascript object —
    into contents the guard could not account for, and refused it;

  An *expansion* is one indivisible token, and the fold treats it as one.
  ``$( ... )``, ``${ ... }``, ``$(( ... ))``, a backtick pair and
  ``<( ... )`` are single words to bash: the parentheses, braces, spaces and
  ``;`` ``|`` ``&`` inside one belong to the expansion, not to the command,
  and bash splits neither a word nor a brace group on them.  So the fold
  takes each expansion out of the command's structure — the span reads as
  ``*/`` followed by the boundary placeholder — and keeps its body as a
  reading of its own.  A nested expansion is simply another reading, so
  nothing has to recurse.  Both halves of that are load-bearing.  Without
  the first, a group whose alternatives are themselves spans loses its
  closing brace to a span and disappears, although bash keeps the word
  whole and expands it.  Without the second, a name written only inside an
  expansion's body is not read at all.  Replacing a span with a placeholder
  and dropping its text would trade one for the other.

  An expansion whose extent cannot be decided — one that never closes, or
  one whose closer does not match its opener — is refused rather than
  guessed at, on the same principle the brace budget refuses on: whatever
  the guard concluded about the structure around it would be a guess.  Bash
  cannot run such a command either.  It says that in its *own* reason, and
  not the budget's: no budget is spent deciding an extent and no brace
  expansion is attempted, so "use fewer brace groups" sent the agent to
  count groups when what the command needs is a closing delimiter.

  Where the expansion *does* close, what it produces is still unknown — and
  unknown in extent as well as in text, because the shell splices the result
  into the middle of a word and the characters after the closer belong to the
  same path component.  So the reading holding an expansion's body ends in a
  wildcard, which is what puts "the body wrote part of a name and the command
  wrote the rest" to rule 2.  Without it each reading dropped that question
  for its own reason: the body reading ended on a name that merely resembled
  the directory's, and the command reading, where the whole expansion is one
  unknown token, had no dot in it to judge.

  There is a *second* set of readings, built the same way over the same spans,
  differing in one rewrite: a quoted metacharacter is left live instead of
  collapsing to the placeholder.  Collapsing it is the right answer to "what
  will this shell expand", and that is the only question the first set is
  asked.  It is the wrong answer to "what will the next program along do with
  this string", and a quoted string is exactly how a command hands text to a
  program that starts a shell of its own: a command that a shell re-reads.
  That shell sees the metacharacters as written, and the brace step over the
  second reading produces what it would produce.  Two readings of the one question is *not* the split-brain bug the
  top of this docstring forbids: that bug was partition, each rule owning one
  string and blind to the other.  Here every rule that reads a name written
  out sees both sets, so neither can hide anything from it.

  What the second set must not answer is rule 2, the one that asks whether a
  *pattern* matches.  A quoted pattern is text the shell will not act on —
  that is why the first reading collapses it — so letting the second reading
  judge it as a pattern refuses every quoted glob and regex anyone writes:
  ``sed 's/.*//'``, ``find . -name '.*'``, ``ls '.*'``, ``tar -czf a.tgz
  '*.py'``.  It answers rules 1 and 4, which read something spelled out, and
  it carries no wildcard for the same reason: a wildcard is a pattern.  Nor
  does it produce a refusal of its own.  The structure it could not resolve is
  the same structure the first set could not, and refusing twice over would
  deny ``jq '{a: 1, b: $x}'`` for a group bash never expands.

  Brace groups are then *expanded*, not approximated: each reading becomes
  the list of strings the shell would produce, and every rule runs against
  all of them.  ``~/.mure{o,x}`` and ``~/{.,z}mureo`` are caught because
  ``.mureo`` is literally among the results.

  An earlier version folded each group to one placeholder and guessed
  which — ``.*`` if the group held a dot anywhere, ``*`` otherwise — and
  the guess is what broke.  ``~/.{mureo,x.y}`` has a dot before the group
  and a dot inside an alternative that has nothing to do with the
  directory; the fold read them as one, produced ``..*``, which requires
  two leading dots, and meanwhile the literal ``.mureo`` that rule 1 would
  have matched had already been replaced.  Both rules passed and the file
  was read.  Expanding removes the guess instead of refining it.

  A brace group is part of one word, so what counts as its contents is
  decided by the separator placeholders and not by the characters
  themselves.  A group whose contents hold a placeholder is not a group:
  bash does not expand a brace group across a separator it is allowed to
  act on, and neither does this.  A separator the shell may *not* act on is
  ordinary text in the middle of the word, so a group holding one is still
  a group and is expanded like any other — which is the whole reason the
  question is asked of the fold rather than of the finished text.
  ``{"a": 1, "b": 2}`` is therefore not brace expansion and costs nothing,
  while a group whose alternatives are spelled with quoted separators is.

  Ignoring such a ``{...}`` is only safe where the guard can see that
  nothing was lost by doing so, so the ignoring is conditional and fails
  closed.  A ``{...}`` the shell would expand — one with a comma or a
  ``..`` — whose contents hold either an expansion placeholder or a
  separator from the second kind is *refused* as structure that did not
  resolve, rather than ignored.  The reasoning is the same as the budget's:
  if an expansion form the span fold does not recognise were to slip
  through, its insides would read as separators, and ignoring the group on
  that basis would be a guess in the fail-open direction.  Spelled this
  way, any such slip lands on deny.  The condition is restricted to
  expandable groups because a brace span without a comma or a ``..`` is not
  brace expansion to any shell, so there is nothing about it to get wrong;
  and bash's own separating comma is always at the group's top level, so it
  is always visible in the reading when the group is real.

  Two groups are not lists of alternatives and cannot be enumerated this
  way: a sequence (``.{l..n}ureo`` covers ``m`` without the letter
  appearing anywhere) and one with absurdly many alternatives.  Those fall
  back to *both* coarse readings, ``*`` and ``.*``, which between them
  cover "supplies a leading dot" and "does not" — the pair the single
  guess was missing.  A group with neither a comma nor a ``..`` is not
  brace expansion at all; bash leaves ``{eo}`` literal, so the guard does
  too, and ``~/.mur{eo}`` is allowed because it opens nothing.

  Being literal is not the same as being absent, and that distinction is the
  whole of the next step.  Nesting resolves by expanding the innermost group
  first, so that the one around it becomes innermost in its turn — but an
  inert span never goes away, because nothing expands it, and for as long as
  it is there the span around it holds a brace and is not a group to this
  reading at all.  Bash has no such order to wait on: it expands braces over
  the raw text, before every other expansion, so an alternative carrying an
  inert ``{...}`` is just an alternative.  The guard agrees with it by
  writing an inert span's braces as placeholders of their own, which leaves
  the enclosing span readable, and by putting them back before any rule runs,
  which keeps the candidate strings the strings the shell produces.  Only
  inert spans are mapped: one with a comma or a ``..`` is the expansion
  step's, and mapping it would resolve the inside before the outside; one
  holding a separator is not kept in a single word by bash either.  The
  mapping needs a pass per level of nesting and is bounded like everything
  else here, and a text still changing when the bound is reached is refused
  with the rest of the structure the budget did not finish.

  Expansion has a budget — eight passes, 100,000 bytes of candidate text
  per reading set — so a pathological command cannot explode the hook.
  **Whatever the budget does not resolve is refused.**  Anything still
  holding an expandable group after the passes denies on that ground alone.

  That rule replaced a fallback that collapsed leftovers coarsely, and it
  is worth saying plainly why, because the docstring claimed the fallback
  "over-approximates rather than dropping candidates" and that was false.
  Past ten levels of nesting the collapse left literal ``{`` and ``}`` in
  the candidates, which ``fnmatch`` reads as ordinary characters, so
  *neither* rule fired: ``cat ~/.{z11,{z10,…{z1,mureo}}}/…`` — ninety
  characters, no exotic syntax — was allowed while bash read the file.  A
  budget that shrugs is a bypass with a length requirement.  The general
  form of the rule is: when the guard cannot compute what the shell would
  produce, it denies.

  What that refuses in practice is a command with more than eight brace
  groups, or one whose expansion exceeds 100,000 bytes.  Of twenty-one
  brace-using everyday commands — ``awk '{print $1}'``, ``find . -exec rm
  {} ;``, ``mkdir -p build/{lib,bin,share}``, ``mv file{1..10}.txt``,
  ``jq '{name: .name}'``, eight groups on one line — exactly one is
  refused: nine groups on one line.  Quoted braces never reach this step,
  and a group with no comma and no ``..`` is literal to bash and to ``fe``.

  Deliberate over-blocks, all in the safe direction:

  - anything unquoted that really does glob dotfiles: ``ls .*``, ``ls -d
    .??*``, ``rm -rf .[!.]*`` all reach ``~/.mureo`` from ``$HOME`` and
    all deny;
  - a component holding an expansion is unknown text, so ``ls .$X`` and
    ``cat .$(cmd)`` deny.  An arithmetic expansion is not treated any
    differently, so ``echo .$((1+1))`` and ``cat ~/.mure$((0))?/x`` deny
    too, though neither can reach the directory;
  - a format string that builds ``<something>.<something>`` is the shape
    of ``printf '%s.mureo/…' ~/``, and nothing in the text distinguishes
    them, so ``printf '%s.%s' a b`` denies.  Of twenty ``%``-heavy
    everyday commands (``date +%Y-%m-%d``, ``git log --format=%h``,
    ``awk '{printf "%.2f", $1}'``, ``grep '100%'``, a commit message
    reading ``30% faster``) that is the only one that does;
  - brace structure the expansion budget could not resolve: more than
    eight groups in one command, an inert span nested past the passes the
    mapping is given, or an expansion whose normalized text exceeds the
    budget.  The budget is a fixed total split between the two reading sets,
    so adding the second set did not raise the work the hook can be made to
    do;
  - an expansion whose body *ends* on a prefix of the directory's name,
    which is what reading the result as text of unknown extent costs.  A
    bare ``.`` is such a prefix, so ``echo $(ls .)`` denies although what it
    produces is a listing.  The expansion's result is not in the text, and a
    guard that cannot tell has to answer on the deny side; the bound on the
    cost is that the body has to end there — ``echo $(ls -a)``, ``echo
    $(basename a.txt)``, ``cd $(dirname a/b.txt)`` and ``diff <(sort a)
    <(sort b)`` are all allowed;
  - brace structure whose contents did not resolve: a ``{...}`` the shell
    would expand whose contents hold both a separator and an expansion
    (``echo {a, $(date)}``, ``echo {a, $x}``), or a separator of the second
    kind.  Bash expands neither, so nothing real is refused by the first
    half; the second half costs a comma-bearing group written around text
    in another language, measured with the here-document bullet below.
    Both are the price of failing closed on contents the guard cannot
    account for rather than ignoring them, and both say so in their own
    reason rather than borrowing the budget's;
  - structure the span fold could not pair up: ``cat ~/x$(``, an unclosed
    backtick, and an unquoted ``{`` with no ``}`` after it (``echo a{b``,
    which bash does print).  The last is the price of refusing a brace group
    left open around an expansion, where the group's closing brace is the
    one the expansion took: the two are the same shape, and the guard cannot
    tell them apart without deciding the extent it just failed to decide.  A
    *closing* brace with nothing to close is not refused — ``echo a}b`` is
    allowed — because a stray closer hides nothing;
  - after an unquoted ``<<``, whatever a quote used to neutralise is live.
    An unmatched ``(`` or ``{`` in a body is structure the span fold cannot
    pair up, so ``print("{")`` and ``print("(")`` as the body of a python
    here-document are refused on the unresolved-structure ground above;
    and a quoted pattern written after a body is read as a pattern, so
    ``ls '.*'``, ``sed 's/.*//'`` and ``find . -name '.*'`` deny on the
    line after a terminator although the bullet above allows all three on
    their own.  A body holding a comma-bearing brace group around a call
    (``d = {"n": len([1, 2])}``) was on this list until a body's
    punctuation stopped being read as a command line's; it is an everyday
    script, and refusing it was the kind of cost that teaches people to turn
    a guard off.  What is left is the price of reading a body the way bash
    reads it, and the alternative, resolving quoting inside a body, is not
    something bash does, and a guard that has to agree with bash about where
    the shell text is cannot do it either.  Within the latch a refusal from rules 1 to 3 cannot
    claim the reference is live, because the guard has read text without
    resolving quoting and does not know; it says that instead of claiming
    the command can reach the directory;
  - a command longer than 64 KB, which is refused unread (see below);
  - sequence syntax this does not recognise — a three-part ``{a..z..2}``,
    an endpoint that is neither an integer nor a single letter — which is
    refused rather than reasoned about.  Bash expands a sequence only for
    those two endpoint kinds, so ``{-..0}`` is not a sequence at all and
    stays literal; the refusal costs nothing real.  Sequences that *are*
    recognised are read exactly, so ``echo {1..100}``, ``for i in
    {1..5}``, ``printf '%s' {A..Z}`` and ``touch file{1..20}.log`` are
    allowed — every one of them denied until the endpoints were consulted,
    which is the kind of over-block that teaches people to turn a guard
    off.

  Brace expansion itself used to be on this list — ``mv .{foo,bar}`` and
  ``rm .{a,b,c}`` denied although neither can name the directory.
  Expanding the alternatives exactly, rather than folding them to a
  placeholder, removed those: each alternative is judged on its own, and
  both are allowed.  That is the shape of the right fix for the remaining
  entries — compute what the shell would produce instead of approximating
  it — and where that is impossible, refuse rather than approximate.

  The coarse approximations that are left: an expansion's *text*
  (unknowable, so ``*`` in the command reading and a trailing wildcard on the
  body's), an expansion's *extent* (unknowable, so ``/``), and a ``%``
  template's result.  Two more — a sequence group and a group
  with more than 64 alternatives — still take both coarse readings rather
  than being enumerated; enumerating them is a contained change and the
  place to start if this list is ever shortened again.

  What the guard does not cover — measured, not assumed, and pinned by
  ``test_known_open_bypasses``:

  - the shell's own options.  ``shopt -s dotglob; cat ~/*/x`` reads the
    file; the command text says nothing about whether ``dotglob`` is set,
    and it can have been set in an earlier call on the same persistent
    shell or in the user's rc file.  Denying every ``*`` instead is not an
    option;
  - anything whose text the command does not contain: a name taken from a
    variable set elsewhere (``cat ~/$P/x``), or one written in a notation
    that has to be decoded first (``cat ~/$'\\x2emureo'/x``).  Every rule
    can only read what is written down.  Where the text *is* written down
    the guard does see it, which is why ``P=.mure?; cat ~/$P/x`` denies —
    and why a name an expansion assembles out of text its own body spells
    out is now decided, since a body's reading ends in a wildcard.  That
    narrows this entry rather than closing it: a body that spells none of
    the name is still a body with nothing in it to read;
  - extended globs (``.mure@(o|x)``), which bash parses only with
    ``extglob`` set, and which ``fnmatch`` does not implement;
  - patterns for *sibling* names (``~/.mur*_backup``): rule 2 asks only
    whether a pattern matches ``.mureo`` itself, whereas rule 1 does deny
    literal siblings such as ``~/.mureo_backup``;
  - ``config.json`` reached by a filename search, for the reason given
    with rule 4: the name is too common to deny;
  - a symlink into the directory under a name that mentions neither the
    directory nor a protected filename (``cat ~/notes/backup.json`` where
    that path is a link to the credentials file).  The *path* guard
    resolves symlinks in both directions and closes this; the Bash guard
    never touches the filesystem, so it cannot.  The two guards protect
    the same directory with different reach, and this is where they
    differ.

  The first two are not closable by inspecting command text, and no
  further rule should be added pretending otherwise.

  What is actually checked, and where — every number below is produced by
  committed code, not by a measurement someone once took:

  - ``tests/credential_guard_product.py`` builds a product of {how the
    parent directory is supplied: literal, ``$HOME``, ``"$HOME"``,
    ``$VAR``, ``"$VAR"``, ``${VAR}``, ``$VAR$EMPTY``, ``$1``, ``$(cmd)``,
    backtick} x {how the name is broken: not at all, continuation, two
    continuations, single-quote split, single-quoted character,
    double-quote split, double-quoted character, escaped character, class,
    wildcard, brace here, brace tail, brace whole, sequence, star} x {what
    the breaking form contains: plain, an alternative with its own dot,
    with two, a backup-looking name, a nested group, a metacharacter, a
    leading dot, a substitution, a substitution holding a space, a
    backtick substitution, an arithmetic expansion} x {how deeply it
    nests: 0, 1, 2, 3, 5, 8, 9, 11, 14, 20} x {where}.  3098 members.
    ``pytest -m slow`` runs all of them, executing each in a throwaway
    ``HOME`` to confirm it really does read the marker file and then
    asking the guard: all 3098 read it, all 3098 deny.  The default run
    checks an evenly-strided sample of 135, so every commit defends the
    property even without the slow pass;
  - the nesting cliff has its own table: every depth from 1 to 20 with
    two, three and five alternatives per level, 60 cells, run by default.
    Each asserts that the command really reads the marker file *and* that
    the guard denies it.  Against the commit before the refusal rule the
    deeper cells were allowed while bash read the file, the cliff falling
    at depth 11 for two alternatives per level and earlier for more;
  - the resource bounds have their own tests: expansion bombs up to
    multi-megabyte commands must still answer, and the 64 KB boundary must
    refuse on one side and not the other.

  Older figures that once appeared here — a random single-character fuzz —
  are gone rather than restated, because nothing in the repository
  reproduces them.  A number in a docstring with no committed artifact is
  a claim about the past, not a property of the code; if a measurement is
  worth quoting it is worth committing the thing that produces it.

  Each round of bugs here has been a product of axes the generator only
  walked the margins of.  It emitted continuations and it emitted
  substitutions, but never a continuation *inside* a substituted parent.
  Then it emitted brace groups, but every alternative was inert filler, so
  a group holding an unrelated dot could not be produced.  Then it had a
  "nested group" filler at one fixed depth, so 1510 members all sat at
  depth two or less and the cliff at eleven was invisible.  Each time the
  missing dimension was one level *inside* the last one added.

  Take the pattern rather than the instances: a form the generator cannot
  produce is a form nothing here has checked, and that applies to the
  insides of forms, to how deeply they nest, and to combinations of them,
  not only to the list of features.  Before trusting a number in this
  docstring, look at whether the generator can express the shape it claims
  to cover — and prefer a rule that fails closed on what it cannot resolve
  over a measurement that says the gap is not reachable.

Both comparisons are case-folded: macOS and Windows filesystems are
case-insensitive by default, so ``~/.MUREO/credentials.json`` opens the
real file.  On case-sensitive filesystems this can only over-block (a
genuinely distinct ``~/.MUREO`` directory), never under-block — the right
direction for a guard.

Both payloads fail closed.  A hook that exits non-zero for any reason
other than the documented block is a *non-blocking* error and the tool
call proceeds, so an exception escaping the payload is a bypass, not a
crash: ``sys.excepthook`` is set to print the deny JSON and exit 0.  This
was not academic — malformed stdin made both payloads exit 1 and let the
call through, as did a path with an embedded NUL, which makes
``os.path.realpath`` raise.

Failing closed is about time as well as exceptions.  ``sys.excepthook``
catches what Python raises; it cannot catch the host killing a hook that
overruns, and that process exits non-zero *without* printing the deny
JSON — which is precisely the non-blocking case where the tool call
proceeds.  A guard that is merely slow is a guard that is bypassed, and a
4 MB command of nested brace groups used to take it there: no answer in
45 seconds, 1.95 GB resident.  Three bounds keep that shut, all of them
cheap: the command is refused unread above 64 KB, expansion is budgeted on
total normalized bytes rather than on how many candidates there are, and a
pass that has to revert stops the loop instead of letting the remaining
seven recompute and discard the same expansion.  Multi-megabyte bombs now
answer in about a fifth of a second.  Nothing legitimate comes near 64 KB;
if that ever stops being true, raise the bound deliberately rather than
letting the work grow to fit.

The payloads run under whatever ``python3`` the host finds on PATH, which
need not be the interpreter mureo itself was installed with.  The Bash
payload needs **Python 3.8 or newer** for ``itertools.accumulate(...,
initial=...)``; on anything older it raises, which fails closed — it
denies every Bash call rather than letting any through, so the symptom is
loud and safe rather than silent.  Keep it that way: a rewrite of the fold
that avoids ``initial=`` is fine, one that swallows the error is not.

WHAT THIS GUARD IS.  It is a deterrent against an agent reading the
credentials by accident or on a careless instruction — the cases that
actually happen.  It is not a security boundary and cannot be made into
one.  The agent runs as the user who owns the file, so it can read it
through any construction the text does not reveal: a variable, a
substitution, an encoding, a helper script, a language runtime.  The
earlier claim here that "real safety comes from filesystem permissions"
was wrong in the same direction: permissions do not stop a process running
as the owner either.  What actually limits the damage is not keeping
long-lived credentials where an autonomous agent runs, scoping and
rotating them, and the audit trail — not this hook.  Judge changes to it
by whether they make the common accident less likely without blocking real
work, and do not describe it as more than that.

NOTE: the python payloads run inside double quotes on a shell command line
(``python3 -c "..."``), so they must not contain double quotes, ``$``,
backticks, backslashes, newlines, or ``!`` — the last because a shell with
history expansion enabled rewrites ``!`` sequences inside double quotes.
Every one of those characters is also *data* the Bash guard needs, since
they are exactly the characters a shell treats as special, so each arrives
by ``chr()``: 33 ``!``, 34 ``"``, 36 ``$``, 39 ``'``, 92 backslash, 96
backtick.  ``tests/test_credential_guard.py`` enforces the prohibition, and
``TestGuardThroughARealShell`` runs the generated command through a real
bash so the wrapper's own quoting is exercised rather than assumed.
"""

from __future__ import annotations

from typing import Any

# The payloads are assembled in mureo._credential_guard, one module per
# step.  What callers and tests import is re-exported here: the payloads,
# the protected filenames, and the deny reasons with the check on them --
# re-exports nothing here uses, hence the blanket noqa.
from mureo._credential_guard.bash_guard import (  # noqa: F401
    _BASH_GUARD_CODE,
    GUARDED_FILENAMES,
)
from mureo._credential_guard.path_guard import _PATH_GUARD_CODE
from mureo._credential_guard.reasons import (  # noqa: F401
    _BASH_REASON,
    _BUDGET_REASON,
    _FILENAME_REASON,
    _HEREDOC_REASON,
    _OVERSIZE_REASON,
    _PATH_REASON,
    _SAFE_REASON_CHARS,
    _SPAN_REASON,
    _UNRESOLVED_REASON,
    _deny_expr,
)

# Unique identifier used to detect (and upgrade/remove) mureo-installed hooks.
GUARD_TAG = "[mureo-credential-guard]"

# Matchers are regexes over the tool name. PATH_TOOLS_MATCHER lists the
# Claude Code tools that receive a filesystem path; entries for tools a host
# does not expose (e.g. Codex has no Read tool) simply never fire.
PATH_TOOLS_MATCHER = "Read|Edit|Write|Grep|Glob|NotebookEdit"
BASH_MATCHER = "Bash"


def path_guard_command() -> str:
    """The shell command for the path-based guard (Read/Edit/Write/Grep/Glob)."""
    return f'python3 -c "{_PATH_GUARD_CODE}" # {GUARD_TAG}'


def bash_guard_command() -> str:
    """The shell command for the Bash command-text guard."""
    return f'python3 -c "{_BASH_GUARD_CODE}" # {GUARD_TAG}'


def path_guard_entry() -> dict[str, Any]:
    """A fresh PreToolUse entry for the path guard."""
    return {
        "matcher": PATH_TOOLS_MATCHER,
        "hooks": [{"type": "command", "command": path_guard_command()}],
    }


def bash_guard_entry() -> dict[str, Any]:
    """A fresh PreToolUse entry for the Bash guard."""
    return {
        "matcher": BASH_MATCHER,
        "hooks": [{"type": "command", "command": bash_guard_command()}],
    }


def guard_entries() -> list[dict[str, Any]]:
    """Fresh copies of both guard entries, in install order.

    Fresh so that callers merging them into parsed user config never alias
    dicts across two install targets.
    """
    return [path_guard_entry(), bash_guard_entry()]


def is_guard_entry(entry: Any) -> bool:
    """True when ``entry`` is a mureo-tagged PreToolUse entry.

    Detection is scoped to the inner ``command`` field so a user's own entry
    whose matcher happens to contain the tag literal is never claimed.

    Matching is entry-level: installers drop the whole entry when any inner
    hook carries the tag. mureo only ever writes single-hook entries, so
    this is equivalent to the finer hook-level stripping that
    ``mureo.cli.settings_remove`` performs — it differs only on a
    hand-merged config where a user appended their own hook to a mureo
    entry.
    """
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(hook, dict) and GUARD_TAG in str(hook.get("command", ""))
        for hook in hooks
    )
