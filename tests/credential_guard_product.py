"""The differential product the Bash credential guard's numbers come from.

``mureo/credential_guard.py`` quotes counts — "all N members read the
credentials file, and all N deny". This module is where those come from, so
the claim is a property that can be re-run rather than a number someone
once measured. ``tests/test_credential_guard_product.py`` runs it.

The shape is a cartesian product of the axes that have actually produced
bypasses, because every one of them was a *combination* rather than a
feature:

* how the parent directory is supplied — literal, ``$HOME``, ``"$HOME"``,
  ``$VAR``, ``"$VAR"``, ``${VAR}``, ``$VAR$EMPTY``, ``$1``, ``$(cmd)``,
  backtick;
* how the name is broken up — continuation, quote splits, escapes,
  classes, wildcards, brace forms, sequences;
* what the breaking form *contains* — an alternative carrying its own dot
  is what defeated the fold that replaced a group with one placeholder;
* how deeply the form nests — the expansion budget's cliff was invisible
  while every member sat at depth two or less;
* where in the name it happens.

Each member is checked two ways: run in a real bash against a throwaway
HOME holding a marker credentials file, and put through the real generated
hook command. A member that reads the marker and is not denied is a
bypass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

# These tests execute the attack command in a real shell and check whether it
# reaches the file. That is a statement about POSIX path, glob and quoting
# semantics; under an emulated shell on Windows a "no" would mean "not
# reachable through this translation layer", which is not the property under
# test and is indistinguishable from the guard working.
POSIX_SHELL = os.name == "posix"

Q1, Q2, BS, TICK, NL = chr(39), chr(34), chr(92), chr(96), chr(10)
CONT = BS + NL
NAME = ".mureo"
MARKER = "MUREO-PRODUCT-MARKER-8F31A7"

# (label, prelude, text placed in front of the name)
PARENTS: list[tuple[str, str, str]] = [
    ("literal", "", "~/"),
    ("$HOME", "", "$HOME/"),
    ('"$HOME"', "", Q2 + "$HOME" + Q2 + "/"),
    ("$VAR", "D2=~/; ", "$D2"),
    ('"$VAR"', "D2=~/; ", Q2 + "$D2" + Q2),
    ("${VAR}", "D2=~/; ", "${D2}"),
    ("$VAR$EMPTY", "D2=~/; E2=; ", "$D2$E2"),
    ("$1", "set -- ~/; ", "$1"),
    ("$(cmd)", "", "$(printf " + Q1 + "%s" + Q1 + " ~/)"),
    ("backtick", "", TICK + "printf " + Q1 + "%s" + Q1 + " ~/" + TICK),
]

# (label, the other alternative of a brace group, extra members of a class)
FILLERS: list[tuple[str, str, str]] = [
    ("plain", "z", "z"),
    ("dotted", "x.y", "x"),
    ("dotted twice", "a.b.c", "a"),
    ("backup-looking", "bashrc.bak", "b"),
    ("nested group", "{a,b}.c", "c"),
    ("metachar", "x*", "x"),
    ("leading dot", ".hidden", "h"),
]

NESTINGS = [0, 1, 2, 3, 5, 8, 9, 11, 14, 20]


def breaks(alt: str, cls: str) -> list[tuple[str, object]]:
    """Ways to spell ``NAME`` so the six characters are not consecutive."""
    return [
        ("none", lambda n, i: n),
        ("continuation", lambda n, i: n[:i] + CONT + n[i:]),
        ("two continuations", lambda n, i: n[:i] + CONT + n[i:] + CONT),
        ("single-quote split", lambda n, i: n[:i] + Q1 + Q1 + n[i:]),
        ("single-quoted char", lambda n, i: n[:i] + Q1 + n[i] + Q1 + n[i + 1 :]),
        ("double-quote split", lambda n, i: n[:i] + Q2 + Q2 + n[i:]),
        ("double-quoted char", lambda n, i: n[:i] + Q2 + n[i] + Q2 + n[i + 1 :]),
        ("escaped char", lambda n, i: n[:i] + BS + n[i] + n[i + 1 :]),
        ("class", lambda n, i: n[:i] + "[" + n[i] + cls + "]" + n[i + 1 :]),
        ("wildcard", lambda n, i: n[:i] + "?" + n[i + 1 :]),
        ("brace here", lambda n, i: n[:i] + "{" + n[i] + "," + alt + "}" + n[i + 1 :]),
        ("brace tail", lambda n, i: n[:i] + "{" + n[i:] + "," + alt + "}"),
        ("brace whole", lambda n, i: "{" + n + "," + alt + "}"),
        ("sequence", lambda n, i: n[:i] + "{" + n[i] + ".." + n[i] + "}" + n[i + 1 :]),
        ("star", lambda n, i: n[:i] + "*" + n[i + 1 :]),
    ]


def nest(spelled: str, depth: int) -> str:
    """Bury a spelling inside ``depth`` further brace levels."""
    for level in range(depth):
        spelled = "{z" + str(level) + "," + spelled + "}"
    return spelled


def members() -> list[tuple[str, str]]:
    """Every member of the product, as ``(label, command)``."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for plabel, prelude, prefix in PARENTS:
        for flabel, alt, cls in FILLERS:
            for blabel, spell in breaks(alt, cls):
                # A filling only varies the forms that have one.
                if flabel != "plain" and not (
                    blabel.startswith("brace") or blabel == "class"
                ):
                    continue
                positions = [0] if blabel in ("none", "brace whole") else range(1, 6)
                for i in positions:
                    try:
                        spelled = spell(NAME, i)  # type: ignore[operator]
                    except IndexError:
                        continue
                    depths = (
                        NESTINGS
                        if (flabel == "plain" and plabel in ("literal", "$VAR"))
                        else [0]
                    )
                    for depth in depths:
                        body = nest(spelled, depth)
                        cmd = prelude + "cat " + prefix + body + "/credentials.json"
                        if cmd in seen:
                            continue
                        seen.add(cmd)
                        out.append(
                            (f"{plabel} | {blabel} | {flabel} | @{i} | d{depth}", cmd)
                        )
    return out


def build_home(root: str | os.PathLike[str]) -> Path:
    """A throwaway HOME with a marker credentials file."""
    home = Path(root) / "home"
    shutil.rmtree(home, ignore_errors=True)
    (home / ".mureo").mkdir(parents=True)
    (home / ".mureo" / "credentials.json").write_text(
        json.dumps({"access_token": MARKER}), encoding="utf-8"
    )
    (home / "project").mkdir(exist_ok=True)
    return home


def reads_marker(command: str, home: str | os.PathLike[str], bash: str) -> bool:
    """Does a real shell actually print the credentials file for this?

    ``home`` is coerced here rather than at the call sites. It arrives as a
    ``Path`` from every caller, and ``subprocess`` on POSIX accepts one in
    ``env`` while Windows raises ``TypeError: environment can only contain
    strings`` — so an annotation that disagreed with the argument was not
    cosmetic, it was a failure waiting for the first platform that enforces
    the contract. Coercing at the boundary means the signature and the
    reality agree without every caller having to remember.

    The environment is ``os.environ`` with ``HOME`` overridden, not a
    hand-built pair: a minimal env drops variables a shell needs to start
    at all on some platforms, which fails as "the command did not read the
    file" — indistinguishable from the guard working.
    """
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    try:
        proc = subprocess.run(
            [bash, "-c", command],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(home),
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return False
    return MARKER in proc.stdout
