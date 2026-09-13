# Driving SQL*Plus from a script or an agent

SQL*Plus is the lowest common denominator for reaching a database — it is in every
container image and needs no driver. It was designed for a human at a terminal, though,
and three of its behaviours turn a non-interactive script into a silent wrong answer
rather than an error. Each was measured against a live `docker exec sqlplus` session.

## Turn substitution off before printing anything you did not write

In SQL*Plus, an ampersand (&) inside a value returned by a query (e.g. an Oracle-folded
identifier printed back by a script) triggers substitution-variable prompting mid-run,
which consumes the NEXT LINE of the script as the substitution value and executes
whatever statement follows as if the user had typed it. Because substitution happens
before SQL parsing, neither alternate literal quoting (q'[...]') nor escaping inside the
literal prevents it — SET DEFINE OFF is the only guard.

So `SET DEFINE OFF` belongs at the top of any script that echoes a value back — an
identifier read from the data dictionary, a filename, a user-supplied string. The failure
is quiet: the script runs to completion, one statement short and one substitution long,
and the exit status is 0.

## CSV markup cannot carry a LONG column

SQL*Plus SET MARKUP CSV cannot render a LONG column (e.g.
USER_IND_EXPRESSIONS.COLUMN_EXPRESSION): it opens the quoted CSV field, doubles the
inner quotes, and never closes it, silently swallowing every subsequent row in the
result set rather than erroring. SET LONG does not fix it, and a LONG value cannot be
passed as a function argument to work around it either — the only escape is a PL/SQL
block that reads the LONG and prints it with dbms_output.

Index expressions are the usual way to meet this — `USER_IND_EXPRESSIONS.COLUMN_EXPRESSION`
is a LONG, so a script that dumps index metadata as CSV loses every row after the first
index that has an expression. Read LONGs in a PL/SQL block and print them with
`dbms_output` instead of asking markup to format them.

## Write stdin on its own thread

A subprocess wrapper around sqlplus that writes the whole script to stdin before reading
stdout can deadlock, but the trigger is SCRIPT size, not response size: a large query
RESPONSE never blocks the writer, but a large SCRIPT does, because the OS pipe buffer
fills while sqlplus is still consuming stdin and nothing is draining stdout yet.
Measured against a live `docker exec sqlplus` session: a 444 KB script completes
normally; a 592 KB script hangs forever after exactly one pipe-buffer's worth is read.
Fix: write stdin on its own thread instead of sequentially before reading stdout.

The intuition to unlearn is that big *results* are the risk; they are not. A wrapper that
streams a large query back works fine, and the same wrapper hangs forever on a long script
of small statements. If a session hangs with no output at all, look at the size of what you
wrote in, not what you expected back.

## Sources
- Measured on `adb-free:latest-26ai` and Oracle Database 26ai Free via `docker exec`,
  2026-08-12/13; captured through mneme.
