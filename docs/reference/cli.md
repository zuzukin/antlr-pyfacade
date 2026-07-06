# Command line

Installing the package provides the `antlrope` command — a **command group** with the
subcommands `gen`, `regen`, `up-to-date`, `check`, `rules`, and `tokens`. Invoking
`antlrope` with no subcommand prints
help; `antlrope --version` prints the version. See
[Getting started](../getting-started.md) for the full generate → subclass → walk
workflow.

!!! Note ""

    *The reference below is generated from the live `--help` output (by
    `scripts/gen_cli_docs.py` / `pixi run gen-cli-docs`), so it always matches the CLI.*

<!-- gen-cli-help: start (managed by scripts/gen_cli_docs.py — do not edit) -->

## antlrope

```text
usage: antlrope [-h] [--version] <command> ...

Command-line tools for the antlrope ANTLR runtime.
```

### positional arguments

```text
  <command>
    gen (generate)      Generate a <Grammar>EventListener facade from a parser module.
    regen (regenerate)  Regenerate a facade in place from its embedded metadata.
    up-to-date          Check whether a generated facade is current with its inputs.
    check               Check a grammar for semantic predicates / embedded actions.
    rules               List a parser's rule names (for start_rule= and the rule
                        chunkers).
    tokens              List a parser's token types and names (the facade's constants).
```

### options

```text
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```

## antlrope gen

```text
usage: antlrope gen [-h] [--lexer <lexer-module>] [-o <file>] <parser-module> <name>

Generate a <Grammar>EventListener facade from a stock-generated ANTLR Python parser
module.
```

### positional arguments

```text
  <parser-module>       Importable dotted path to the generated parser module (e.g.
                        mypkg.generated.MyParser).
  <name>                Grammar name prefix for the facade class.
```

### options

```text
  -h, --help            show this help message and exit
  --lexer <lexer-module>
                        Importable dotted path to the generated lexer module. Defaults to
                        the parser path with a trailing 'Parser' replaced by 'Lexer' (e.g.
                        mypkg.generated.MyLexer); pass this when the lexer is named
                        differently.
  -o, --output <file>   Write to this file instead of stdout.
```

## antlrope regen

```text
usage: antlrope regen [-h] <file>

Re-run the `gen` command recorded in a generated facade's metadata header, from the
recorded run directory, overwriting the file.
```

### positional arguments

```text
  <file>      A facade previously written by `antlrope gen`.
```

### options

```text
  -h, --help  show this help message and exit
```

## antlrope up-to-date

```text
usage: antlrope up-to-date [-h] <file>

Compare the input SHA256 hashes and antlrope version recorded in a generated facade
against the current files. Zero exit status if up-to-date.
```

### positional arguments

```text
  <file>      A facade previously written by `antlrope gen`.
```

### options

```text
  -h, --help  show this help message and exit
```

## antlrope check

```text
usage: antlrope check [-h] [--lexer <lexer-module>] <parser-module>

Scan a generated parser/lexer pair for semantic predicates and embedded actions, which the
interpreted ATN cannot execute — a grammar whose parse depends on them mis-parses silently
under antlrope. Zero exit status if the grammar is free of them.
```

### positional arguments

```text
  <parser-module>       Importable dotted path to the generated parser module (e.g.
                        mypkg.generated.MyParser).
```

### options

```text
  -h, --help            show this help message and exit
  --lexer <lexer-module>
                        Importable dotted path to the generated lexer module. Defaults to
                        the parser path with a trailing 'Parser' replaced by 'Lexer'.
```

## antlrope rules

```text
usage: antlrope rules [-h] [--json] <parser-module>

List the parser rule names of a generated parser module, as accepted by
walk(start_rule=...), chunk_by_rule, and stream_by_rule.
```

### positional arguments

```text
  <parser-module>  Importable dotted path to the generated parser module (e.g.
                   mypkg.generated.MyParser).
```

### options

```text
  -h, --help       show this help message and exit
  --json           Emit a JSON array of rule names (the index is the position).
```

## antlrope tokens

```text
usage: antlrope tokens [-h] [--json] <parser-module>

List the token type -> name map of a generated parser module: symbolic names plus the
positional T__n names of anonymous literals, matching the generated facade's token-type
constants.
```

### positional arguments

```text
  <parser-module>  Importable dotted path to the generated parser module (e.g.
                   mypkg.generated.MyParser).
```

### options

```text
  -h, --help       show this help message and exit
  --json           Emit a JSON object mapping token name to token type.
```

<!-- gen-cli-help: end -->

## Provenance header

When generating to a file (`-o`), the `gen` subcommand writes a machine-readable comment header
recording the antlrope version, the exact command, the run directory (relative to the
output file), and a base64-encoded SHA256 of each input module:

```text
# GENERATED by antlrope — do not edit by hand.
# antlrope-version: 0.2.25
# command: antlrope gen generated.JSONParser JSON -o json_listener.py
# rundir: .
# input: <base64-sha256>  generated/JSONParser.py
# input: <base64-sha256>  generated/JSONLexer.py
```

Every field is deterministic, so regenerating an unchanged facade is byte-identical.
[`antlrope regen`](#antlrope-regen) re-runs the recorded command (from the recorded
run directory) to regenerate the file in place; [`antlrope
up-to-date`](#antlrope-up-to-date) re-hashes the inputs and checks the version,
exiting non-zero when the file is stale — handy in a `Makefile` or CI.
