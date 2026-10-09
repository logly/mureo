"""The pieces the credential-guard hook payloads are assembled from.

:mod:`mureo.credential_guard` is the public face: the hook commands, the
PreToolUse entries the installers write, and the module docstring that says
what the guard does, what it refuses that it need not, and what it does not
cover.  Read that docstring first.  Why each step works the way it does is
in the docstring of the module that holds it; the comments in each module
assume its docstring.

The payloads are single-line python programs, and this package holds them in
the order a reader needs them:

* :mod:`.reasons` -- the deny reasons and the expression that prints one;
* :mod:`.path_guard` -- the whole payload of the path guard;
* :mod:`.chars` -- the names the Bash payload gives its metacharacters and
  placeholders;
* :mod:`.quoting` -- the quoting automaton and what each character reads as;
* :mod:`.spans` -- the expansion spans and the readings built from them;
* :mod:`.braces` -- brace expansion and its budget;
* :mod:`.bash_guard` -- rules 1 to 4, and the Bash payload assembled from all
  of the above.

Callers import from :mod:`mureo.credential_guard`, which re-exports the
payloads, the protected filenames and the deny reasons.
"""
