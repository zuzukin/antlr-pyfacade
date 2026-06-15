// Copyright 2026 Christopher Barber
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <nanobind/nanobind.h>
#include <nanobind/trampoline.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include "ANTLRInputStream.h"
#include "BaseErrorListener.h"
#include "CommonTokenStream.h"
#include "ParserInterpreter.h"
#include "LexerInterpreter.h"
#include "ParserRuleContext.h"
#include "Recognizer.h"
#include "RuleContext.h"
#include "Token.h"
#include "Vocabulary.h"
#include "atn/ATN.h"
#include "atn/ATNDeserializer.h"
#include "atn/ATNType.h"
#include "atn/SerializedATNView.h"
#include "tree/ErrorNode.h"
#include "tree/ParseTree.h"
#include "tree/ParseTreeListener.h"
#include "tree/ParseTreeWalker.h"
#include "tree/TerminalNode.h"

#include "events.h"

namespace nb = nanobind;
using namespace antlr4;
using namespace antlr_pyfacade_events;

// ---------------------------------------------------------------------------
// ATN shape report (kept for the ATN-transfer / spec-load gate).
// ---------------------------------------------------------------------------
struct AtnShape {
    int grammar_type;
    size_t num_states;
    size_t num_decisions;
    size_t num_rules;
    size_t max_token_type;
};

static AtnShape atn_shape(const std::vector<int32_t> &serialized) {
    atn::ATNDeserializer deserializer;
    std::unique_ptr<atn::ATN> atn =
        deserializer.deserialize(atn::SerializedATNView(serialized));
    AtnShape s;
    s.grammar_type = static_cast<int>(atn->grammarType);
    s.num_states = atn->states.size();
    s.num_decisions = atn->decisionToState.size();
    s.num_rules = atn->ruleToStartState.size();
    s.max_token_type = atn->maxTokenType;
    return s;
}

// ---------------------------------------------------------------------------
// Grammar-agnostic parse pipeline driven by the serialized ATN + name lists the
// stock Python3-target ANTLR tool already emits. Specs own the deserialized ATN;
// interpreters hold references into it and are created per parse call.
// ---------------------------------------------------------------------------
struct LexerSpec {
    std::string grammar_file_name;
    dfa::Vocabulary vocabulary;
    std::vector<std::string> rule_names;
    std::vector<std::string> channel_names;
    std::vector<std::string> mode_names;
    std::unique_ptr<atn::ATN> atn;

    LexerSpec(std::string grammar_file_name,
              std::vector<std::string> literal_names,
              std::vector<std::string> symbolic_names,
              std::vector<std::string> rule_names,
              std::vector<std::string> channel_names,
              std::vector<std::string> mode_names,
              const std::vector<int32_t> &serialized)
        : grammar_file_name(std::move(grammar_file_name)),
          vocabulary(std::move(literal_names), std::move(symbolic_names)),
          rule_names(std::move(rule_names)),
          channel_names(std::move(channel_names)),
          mode_names(std::move(mode_names)) {
        atn::ATNDeserializer deserializer;
        atn = deserializer.deserialize(atn::SerializedATNView(serialized));
    }
};

struct ParserSpec {
    std::string grammar_file_name;
    dfa::Vocabulary vocabulary;
    std::vector<std::string> rule_names;
    std::unique_ptr<atn::ATN> atn;

    ParserSpec(std::string grammar_file_name,
               std::vector<std::string> literal_names,
               std::vector<std::string> symbolic_names,
               std::vector<std::string> rule_names,
               const std::vector<int32_t> &serialized)
        : grammar_file_name(std::move(grammar_file_name)),
          vocabulary(std::move(literal_names), std::move(symbolic_names)),
          rule_names(std::move(rule_names)) {
        atn::ATNDeserializer deserializer;
        atn = deserializer.deserialize(atn::SerializedATNView(serialized));
    }
};

// Native baseline listener: counts events without crossing into Python. The
// accumulation keeps the optimizer from eliding the walk.
struct CountingListener : public tree::ParseTreeListener {
    size_t terminals = 0;
    size_t errors = 0;
    size_t enters = 0;
    size_t exits = 0;
    size_t text_bytes = 0;

    void visitTerminal(tree::TerminalNode *node) override {
        terminals++;
        text_bytes += node->getSymbol()->getText().size();
    }
    void visitErrorNode(tree::ErrorNode * /*node*/) override { errors++; }
    void enterEveryRule(ParserRuleContext *ctx) override {
        enters++;
        text_bytes += ctx->getRuleIndex();
    }
    void exitEveryRule(ParserRuleContext * /*ctx*/) override { exits++; }
};

// A collected parse diagnostic. `start`/`stop` are the codepoint span of the
// offending token (matching the event-stream offsets), or -1 when there is no
// token (e.g. a lexer error). `line` is 1-based, `column` 0-based.
struct SyntaxError {
    size_t line;
    size_t column;
    int32_t start;
    int32_t stop;
    std::string message;
};

// Replaces ANTLR's default ConsoleErrorListener (which writes to stderr). It
// captures each syntaxError into a structured list the caller hands to Python,
// so the consumer — not the library — decides how parse errors are reported.
class CollectingErrorListener : public BaseErrorListener {
public:
    std::vector<SyntaxError> errors;

    void syntaxError(Recognizer * /*recognizer*/, Token *offendingSymbol,
                     size_t line, size_t charPositionInLine,
                     const std::string &msg,
                     std::exception_ptr /*e*/) override {
        int32_t start = -1;
        int32_t stop = -1;
        if (offendingSymbol != nullptr) {
            start = static_cast<int32_t>(offendingSymbol->getStartIndex());
            stop = static_cast<int32_t>(offendingSymbol->getStopIndex());
        }
        errors.push_back({line, charPositionInLine, start, stop, msg});
    }
};

// Run lexer + parser to a full tree. Returns the root; tree memory is owned by
// the ParserInterpreter, so the caller must keep both alive while walking. The
// default console error listeners are removed so parsing never writes to stderr;
// pass `err_listener` to collect diagnostics instead.
static ParserRuleContext *run_parse(ParserSpec &pspec, LexerSpec &lspec,
                                    ANTLRInputStream &input,
                                    LexerInterpreter &lexer,
                                    CommonTokenStream &tokens,
                                    ParserInterpreter &parser,
                                    size_t start_rule,
                                    BaseErrorListener *err_listener = nullptr) {
    (void)input;
    (void)lspec;
    (void)pspec;
    lexer.removeErrorListeners();
    parser.removeErrorListeners();
    if (err_listener != nullptr) {
        lexer.addErrorListener(err_listener);
        parser.addErrorListener(err_listener);
    }
    tokens.fill();
    return parser.parse(start_rule);
}

// Diagnostic: pure native cost — parse + walk with a C++ listener.
static nb::dict parse_count(ParserSpec &pspec, LexerSpec &lspec,
                            const std::string &text, size_t start_rule) {
    CountingListener listener;
    size_t num_tokens;
    {
        // Pure native: the counting listener never crosses into Python, so the
        // whole parse + walk runs without the GIL.
        nb::gil_scoped_release release;

        ANTLRInputStream input(text);
        LexerInterpreter lexer(lspec.grammar_file_name, lspec.vocabulary,
                               lspec.rule_names, lspec.channel_names,
                               lspec.mode_names, *lspec.atn, &input);
        CommonTokenStream tokens(&lexer);
        ParserInterpreter parser(pspec.grammar_file_name, pspec.vocabulary,
                                 pspec.rule_names, *pspec.atn, &tokens);
        ParserRuleContext *tree =
            run_parse(pspec, lspec, input, lexer, tokens, parser, start_rule);

        tree::ParseTreeWalker::DEFAULT.walk(&listener, tree);
        num_tokens = tokens.size();
    }

    nb::dict d;
    d["terminals"] = listener.terminals;
    d["errors"] = listener.errors;
    d["enters"] = listener.enters;
    d["exits"] = listener.exits;
    d["num_tokens"] = num_tokens;
    return d;
}

// Diagnostic escape hatch: parse + walk crossing into a Python
// ParseTreeListener subclass (the slow per-node FFI path).
static void parse_walk(ParserSpec &pspec, LexerSpec &lspec,
                       const std::string &text, size_t start_rule,
                       tree::ParseTreeListener *listener) {
    ANTLRInputStream input(text);
    LexerInterpreter lexer(lspec.grammar_file_name, lspec.vocabulary,
                           lspec.rule_names, lspec.channel_names,
                           lspec.mode_names, *lspec.atn, &input);
    CommonTokenStream tokens(&lexer);
    ParserInterpreter parser(pspec.grammar_file_name, pspec.vocabulary,
                             pspec.rule_names, *pspec.atn, &tokens);
    ParserRuleContext *tree;
    {
        // Release the GIL for the native parse; the walk below re-acquires it
        // because it dispatches into the Python ParseTreeListener per node.
        // (input/lexer/tokens/parser stay alive in this scope for the walk.)
        nb::gil_scoped_release release;
        tree = run_parse(pspec, lspec, input, lexer, tokens, parser, start_rule);
    }
    tree::ParseTreeWalker::DEFAULT.walk(listener, tree);
}

// ---------------------------------------------------------------------------
// Bulk event stream: a native iterative DFS over the finished parse tree emits
// a flat (kind, payload, start, stop) int32 record per visited item into one
// contiguous buffer, handed to Python in a single transfer. Optional rule/token
// masks let the consumer drop events it does not care about *in C++*, cutting
// the number of records Python must iterate. This replaces ~#nodes per-node FFI
// callbacks with one crossing. The DFS lives in events.h.
//
// Returned as a flat little-endian int32 buffer of 4*N values (N event rows of
// (kind, payload, start, stop)). Python wraps it with memoryview(...).cast("i")
// — no numpy dependency.
static nb::object parse_events(ParserSpec &pspec, LexerSpec &lspec,
                               const std::string &text, size_t start_rule,
                               std::optional<std::vector<int32_t>> rule_mask,
                               std::optional<std::vector<int32_t>> token_mask) {
    std::vector<int32_t> buf;
    CollectingErrorListener err_listener;
    {
        // Everything in this block is pure C++ (nanobind converted the
        // arguments before entry), so release the GIL: other Python threads
        // keep running, and N threads can parse N documents in parallel.
        nb::gil_scoped_release release;

        ANTLRInputStream input(text);
        LexerInterpreter lexer(lspec.grammar_file_name, lspec.vocabulary,
                               lspec.rule_names, lspec.channel_names,
                               lspec.mode_names, *lspec.atn, &input);
        CommonTokenStream tokens(&lexer);
        ParserInterpreter parser(pspec.grammar_file_name, pspec.vocabulary,
                                 pspec.rule_names, *pspec.atn, &tokens);
        ParserRuleContext *tree = run_parse(pspec, lspec, input, lexer, tokens,
                                            parser, start_rule, &err_listener);

        size_t n_rules = pspec.atn->ruleToStartState.size();
        size_t n_toks = pspec.atn->maxTokenType + 1;
        std::vector<char> rule_keep =
            rule_mask ? make_mask(rule_mask, n_rules) : std::vector<char>();
        std::vector<char> tok_keep =
            token_mask ? make_mask(token_mask, n_toks) : std::vector<char>();

        buf.reserve(1u << 20);
        collect_events(tree, buf, rule_mask ? rule_keep.data() : nullptr,
                       n_rules, token_mask ? tok_keep.data() : nullptr, n_toks);
    }

    nb::bytes events(reinterpret_cast<const char *>(buf.data()),
                     buf.size() * sizeof(int32_t));
    return nb::make_tuple(std::move(events), std::move(err_listener.errors));
}

// Diagnostic: time each stage of the native pipeline separately so the parse
// gap can be decomposed (input UTF-32 decode / lex+fill / parse-to-tree / DFS
// walk). Returns seconds per stage plus token and event counts.
static nb::dict parse_stage_times(ParserSpec &pspec, LexerSpec &lspec,
                                  const std::string &text, size_t start_rule) {
    using clk = std::chrono::steady_clock;
    auto secs = [](clk::time_point a, clk::time_point b) {
        return std::chrono::duration<double>(b - a).count();
    };

    auto t0 = clk::now();
    ANTLRInputStream input(text);
    auto t1 = clk::now();

    LexerInterpreter lexer(lspec.grammar_file_name, lspec.vocabulary,
                           lspec.rule_names, lspec.channel_names,
                           lspec.mode_names, *lspec.atn, &input);
    lexer.removeErrorListeners();
    CommonTokenStream tokens(&lexer);
    tokens.fill();
    auto t2 = clk::now();

    ParserInterpreter parser(pspec.grammar_file_name, pspec.vocabulary,
                             pspec.rule_names, *pspec.atn, &tokens);
    parser.removeErrorListeners();
    ParserRuleContext *tree = parser.parse(start_rule);
    auto t3 = clk::now();

    size_t n_rules = pspec.atn->ruleToStartState.size();
    size_t n_toks = pspec.atn->maxTokenType + 1;
    std::vector<int32_t> buf;
    buf.reserve(1u << 20);
    collect_events(tree, buf, nullptr, n_rules, nullptr, n_toks);
    auto t4 = clk::now();

    nb::dict d;
    d["input_decode"] = secs(t0, t1);
    d["lex_fill"] = secs(t1, t2);
    d["parse_tree"] = secs(t2, t3);
    d["walk"] = secs(t3, t4);
    d["num_tokens"] = tokens.size();
    d["num_events"] = buf.size() / 4;
    d["input_codepoints"] = input.size();
    return d;
}

// ---------------------------------------------------------------------------
// Lexer-only pass: run just the LexerInterpreter + token fill (no parser, no ATN
// prediction — the cheap stage) and return one record per token,
// (type, channel, start, stop), as a flat int32 buffer. Used to split input into
// chunks for walk_parallel without a full parse. `start`/`stop` are codepoint
// offsets matching the event-stream / SourceMap convention (line/column are left
// to the caller's SourceMap). The EOF sentinel token is omitted. An optional
// token_mask (list of token types to keep) drops the rest in C++ — chunkers ask
// only for their boundary tokens, so little crosses into Python.
// ---------------------------------------------------------------------------
static nb::object lex(LexerSpec &lspec, const std::string &text,
                      std::optional<std::vector<int32_t>> token_mask) {
    std::vector<int32_t> buf;
    CollectingErrorListener err_listener;
    {
        // Pure C++ (arguments already converted): release the GIL so lexing of
        // independent inputs can overlap, like the parse functions.
        nb::gil_scoped_release release;

        ANTLRInputStream input(text);
        LexerInterpreter lexer(lspec.grammar_file_name, lspec.vocabulary,
                               lspec.rule_names, lspec.channel_names,
                               lspec.mode_names, *lspec.atn, &input);
        lexer.removeErrorListeners();
        lexer.addErrorListener(&err_listener);
        CommonTokenStream tokens(&lexer);
        tokens.fill();

        size_t n_toks = lspec.atn->maxTokenType + 1;
        std::vector<char> keep =
            token_mask ? make_mask(token_mask, n_toks) : std::vector<char>();
        const char *keepp = token_mask ? keep.data() : nullptr;

        size_t n = tokens.size();
        buf.reserve(n * 4);
        for (size_t i = 0; i < n; i++) {
            Token *tok = tokens.get(i);
            size_t type = tok->getType();
            if (type == Token::EOF) {
                continue;
            }
            if (keepp != nullptr && (type >= n_toks || keepp[type] == 0)) {
                continue;
            }
            buf.push_back(static_cast<int32_t>(type));
            buf.push_back(static_cast<int32_t>(tok->getChannel()));
            buf.push_back(static_cast<int32_t>(tok->getStartIndex()));
            buf.push_back(static_cast<int32_t>(tok->getStopIndex()));
        }
    }

    nb::bytes toks(reinterpret_cast<const char *>(buf.data()),
                   buf.size() * sizeof(int32_t));
    return nb::make_tuple(std::move(toks), std::move(err_listener.errors));
}

// ---------------------------------------------------------------------------
// Rule-span pass: parse (entirely in C++, GIL released) and return the
// (rule_index, start, stop) character span of each parse-tree node whose rule is
// kept by rule_mask (nullptr = all). With outermost=true a matched rule's subtree
// is skipped, so only top-level occurrences are returned. This is the building
// block for rule-based chunking: the first, structural parse stays in C++ and
// only the spans cross into Python. Empty rules with no consumed token yield -1.
// ---------------------------------------------------------------------------
static nb::object rule_spans(ParserSpec &pspec, LexerSpec &lspec,
                             const std::string &text, size_t start_rule,
                             std::optional<std::vector<int32_t>> rule_mask,
                             bool outermost) {
    std::vector<int32_t> buf;
    CollectingErrorListener err_listener;
    {
        // Pure C++ parse + tree walk: release the GIL so independent inputs can
        // be scanned for rule spans in parallel.
        nb::gil_scoped_release release;

        ANTLRInputStream input(text);
        LexerInterpreter lexer(lspec.grammar_file_name, lspec.vocabulary,
                               lspec.rule_names, lspec.channel_names,
                               lspec.mode_names, *lspec.atn, &input);
        CommonTokenStream tokens(&lexer);
        ParserInterpreter parser(pspec.grammar_file_name, pspec.vocabulary,
                                 pspec.rule_names, *pspec.atn, &tokens);
        ParserRuleContext *tree = run_parse(pspec, lspec, input, lexer, tokens,
                                            parser, start_rule, &err_listener);

        size_t n_rules = pspec.atn->ruleToStartState.size();
        std::vector<char> rule_keep =
            rule_mask ? make_mask(rule_mask, n_rules) : std::vector<char>();
        collect_rule_spans(tree, buf, rule_mask ? rule_keep.data() : nullptr,
                           n_rules, outermost);
    }

    nb::bytes spans(reinterpret_cast<const char *>(buf.data()),
                    buf.size() * sizeof(int32_t));
    return nb::make_tuple(std::move(spans), std::move(err_listener.errors));
}

// Trampoline so a Python subclass can override the 4 ParseTreeListener virtuals.
struct PyListener : public tree::ParseTreeListener {
    NB_TRAMPOLINE(tree::ParseTreeListener, 4);
    void visitTerminal(tree::TerminalNode *node) override {
        NB_OVERRIDE_PURE(visitTerminal, node);
    }
    void visitErrorNode(tree::ErrorNode *node) override {
        NB_OVERRIDE_PURE(visitErrorNode, node);
    }
    void enterEveryRule(ParserRuleContext *ctx) override {
        NB_OVERRIDE_PURE(enterEveryRule, ctx);
    }
    void exitEveryRule(ParserRuleContext *ctx) override {
        NB_OVERRIDE_PURE(exitEveryRule, ctx);
    }
};

NB_MODULE(_native, m) {
    m.doc() = "antlr-pyfacade: Python binding over the official ANTLR4 C++ runtime";
    // No __version__ here: the package version lives in the VERSION file and is
    // surfaced via antlr_pyfacade.__version__ (see __init__.py).

    nb::class_<AtnShape>(m, "AtnShape")
        .def_ro("grammar_type", &AtnShape::grammar_type)
        .def_ro("num_states", &AtnShape::num_states)
        .def_ro("num_decisions", &AtnShape::num_decisions)
        .def_ro("num_rules", &AtnShape::num_rules)
        .def_ro("max_token_type", &AtnShape::max_token_type)
        .def("__repr__", [](const AtnShape &s) {
            return "AtnShape(grammar_type=" + std::to_string(s.grammar_type) +
                   ", num_states=" + std::to_string(s.num_states) +
                   ", num_decisions=" + std::to_string(s.num_decisions) +
                   ", num_rules=" + std::to_string(s.num_rules) +
                   ", max_token_type=" + std::to_string(s.max_token_type) + ")";
        });
    m.def("atn_shape", &atn_shape, nb::arg("serialized"),
          "Deserialize a serialized ATN int list and return its shape.");

    nb::class_<SyntaxError>(m, "ParseError")
        .def_ro("line", &SyntaxError::line)
        .def_ro("column", &SyntaxError::column)
        .def_ro("start", &SyntaxError::start)
        .def_ro("stop", &SyntaxError::stop)
        .def_ro("message", &SyntaxError::message)
        .def("__repr__", [](const SyntaxError &e) {
            return "ParseError(line=" + std::to_string(e.line) +
                   ", column=" + std::to_string(e.column) +
                   ", start=" + std::to_string(e.start) +
                   ", stop=" + std::to_string(e.stop) + ", message=" +
                   e.message + ")";
        });

    nb::class_<LexerSpec>(m, "LexerSpec")
        .def(nb::init<std::string, std::vector<std::string>,
                      std::vector<std::string>, std::vector<std::string>,
                      std::vector<std::string>, std::vector<std::string>,
                      const std::vector<int32_t> &>(),
             nb::arg("grammar_file_name"), nb::arg("literal_names"),
             nb::arg("symbolic_names"), nb::arg("rule_names"),
             nb::arg("channel_names"), nb::arg("mode_names"),
             nb::arg("serialized"));

    nb::class_<ParserSpec>(m, "ParserSpec")
        .def(nb::init<std::string, std::vector<std::string>,
                      std::vector<std::string>, std::vector<std::string>,
                      const std::vector<int32_t> &>(),
             nb::arg("grammar_file_name"), nb::arg("literal_names"),
             nb::arg("symbolic_names"), nb::arg("rule_names"),
             nb::arg("serialized"));

    // Minimal node/token surface the listener callbacks need.
    nb::class_<Token>(m, "Token")
        .def("getType", &Token::getType)
        .def("getText", &Token::getText)
        .def("getLine", &Token::getLine)
        .def("getCharPositionInLine", &Token::getCharPositionInLine);

    nb::class_<tree::ParseTree>(m, "ParseTree");
    nb::class_<RuleContext, tree::ParseTree>(m, "RuleContext")
        .def("getRuleIndex", &RuleContext::getRuleIndex);
    nb::class_<ParserRuleContext, RuleContext>(m, "ParserRuleContext")
        .def("getStart", &ParserRuleContext::getStart,
             nb::rv_policy::reference)
        .def("getStop", &ParserRuleContext::getStop, nb::rv_policy::reference);
    nb::class_<tree::TerminalNode, tree::ParseTree>(m, "TerminalNode")
        .def("getSymbol", &tree::TerminalNode::getSymbol,
             nb::rv_policy::reference);
    nb::class_<tree::ErrorNode, tree::TerminalNode>(m, "ErrorNode");

    nb::class_<tree::ParseTreeListener, PyListener>(m, "ParseTreeListener")
        .def(nb::init<>())
        .def("visitTerminal", &tree::ParseTreeListener::visitTerminal)
        .def("visitErrorNode", &tree::ParseTreeListener::visitErrorNode)
        .def("enterEveryRule", &tree::ParseTreeListener::enterEveryRule)
        .def("exitEveryRule", &tree::ParseTreeListener::exitEveryRule);

    m.def("parse_count", &parse_count, nb::arg("parser_spec"),
          nb::arg("lexer_spec"), nb::arg("text"), nb::arg("start_rule"),
          "Diagnostic: parse + walk with a native counting listener (no Python "
          "crossing).");
    m.def("parse_walk", &parse_walk, nb::arg("parser_spec"),
          nb::arg("lexer_spec"), nb::arg("text"), nb::arg("start_rule"),
          nb::arg("listener"),
          "Diagnostic escape hatch: parse + walk the tree, dispatching to a "
          "Python ParseTreeListener (slow per-node FFI path).");
    m.def("parse_events", &parse_events, nb::arg("parser_spec"),
          nb::arg("lexer_spec"), nb::arg("text"), nb::arg("start_rule"),
          nb::arg("rule_mask") = nb::none(), nb::arg("token_mask") = nb::none(),
          "Parse and return (events, errors): a bulk flat int32 event buffer of "
          "4*N values (kind, payload, start, stop) as bytes, and a list of "
          "SyntaxError diagnostics collected during the parse. Optional "
          "rule_mask/token_mask (lists of indices to keep) filter events "
          "natively. The default stderr error listener is suppressed.");
    m.def("parse_stage_times", &parse_stage_times, nb::arg("parser_spec"),
          nb::arg("lexer_spec"), nb::arg("text"), nb::arg("start_rule"),
          "Diagnostic: dict of per-stage seconds (input_decode, lex_fill, "
          "parse_tree, walk) plus token/event/codepoint counts.");
    m.def("lex", &lex, nb::arg("lexer_spec"), nb::arg("text"),
          nb::arg("token_mask") = nb::none(),
          "Run only the lexer and return (tokens, errors): a flat int32 buffer "
          "of 4*N values (type, channel, start, stop) as bytes (EOF omitted), and "
          "a list of ParseError diagnostics. Optional token_mask (list of token "
          "types to keep) drops the rest natively. The cheap stage used to chunk "
          "input for walk_parallel without a full parse.");
    m.def("rule_spans", &rule_spans, nb::arg("parser_spec"),
          nb::arg("lexer_spec"), nb::arg("text"), nb::arg("start_rule"),
          nb::arg("rule_mask") = nb::none(), nb::arg("outermost") = true,
          "Parse (entirely in C++) and return (spans, errors): a flat int32 "
          "buffer of 3*N values (rule_index, start, stop) for each parse-tree "
          "rule kept by rule_mask (None = all), plus a list of ParseError "
          "diagnostics. With outermost=True a matched rule's subtree is skipped. "
          "Used for rule-based chunking.");
}
