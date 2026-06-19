# Command line

Installing the package provides the `antlr-pyfacade` command, which generates a
grammar-specific event-listener **facade** from an already-generated ANTLR Python
parser module. (It reads the parser's `ruleNames` and token-name metadata — no
annotated grammar or other input.)

```text
antlr-pyfacade PARSER_MODULE GRAMMAR [-o OUTPUT]
```

## Arguments

| Argument | Description |
| --- | --- |
| `PARSER_MODULE` | Importable dotted path to the generated parser module, e.g. `generated.JSONParser` or `mypkg.generated.MyParser`. It must be importable on `sys.path`. |
| `GRAMMAR` | Grammar-name prefix for the generated class, which is named `<Grammar.capitalize()>EventListener` (e.g. `JSON` → `JsonEventListener`). |

## Options

| Option | Description |
| --- | --- |
| `-o`, `--output FILE` | Write the facade to `FILE` instead of stdout. |
| `--version` | Print the version and exit. |
| `-h`, `--help` | Show usage and exit. |

## Example

```sh
antlr-pyfacade generated.JSONParser JSON -o json_listener.py
```

emits `json_listener.py` with a `JsonEventListener` base class: an `enter<Rule>` /
`exit<Rule>` pair per grammar rule, `visitTerminal` / `visitError`, the token-type
constants, and a `walk(text, LexerCls, ParserCls)` method. You subclass it — you do
not edit the generated file. See [Getting started](../getting-started.md) for the
full workflow.
