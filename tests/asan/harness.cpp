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

// AddressSanitizer harness: drives the vendored ANTLR runtime + cpp/events.h the
// same way the binding does — deserialize the ATN, run LexerInterpreter /
// ParserInterpreter, collect the bulk event stream — over the example grammars
// and a spread of inputs (including the single-token / EOF-lookahead cases that
// exposed the DFA-edge overflow). Built with -fsanitize=address; a clean exit
// means no memory errors. The grammar data is generated into grammar_data.h by
// scripts/asan_harness.py.

#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include "antlr4-runtime.h"
#include "atn/ATNDeserializer.h"
#include "atn/SerializedATNView.h"

#include "events.h"
#include "grammar_data.h"

using namespace antlr4;
using namespace antlrope_events;

static std::unique_ptr<atn::ATN> deserialize(const std::vector<int32_t> &data) {
  atn::ATNDeserializer d;
  return d.deserialize(atn::SerializedATNView(data));
}

static void parse_once(const GrammarData &g, atn::ATN &lexerAtn,
                       atn::ATN &parserAtn, dfa::Vocabulary &lexerVocab,
                       dfa::Vocabulary &parserVocab, const std::string &text) {
  ANTLRInputStream input(text);
  LexerInterpreter lexer(g.name, lexerVocab, g.lexerRules, g.lexerChannels,
                         g.lexerModes, lexerAtn, &input);
  lexer.removeErrorListeners();
  CommonTokenStream tokens(&lexer);
  ParserInterpreter parser(g.name, parserVocab, g.parserRules, parserAtn,
                           &tokens);
  parser.removeErrorListeners();
  tokens.fill();
  tree::ParseTree *tree = parser.parse(g.startRule);

  // Exercise cpp/events.h, both unfiltered and filtered.
  size_t nRules = parserAtn.ruleToStartState.size();
  size_t nToks = parserAtn.maxTokenType + 1;
  std::vector<int32_t> buf;
  collect_events(tree, buf, nullptr, nRules, nullptr, nToks);
  std::vector<char> keep(nRules, 1);
  collect_events(tree, buf, keep.data(), nRules, nullptr, nToks);

  // Exercise the rule-span collector (outermost on/off, filtered + unfiltered).
  std::vector<int32_t> spans;
  collect_rule_spans(tree, spans, nullptr, nRules, /*outermost=*/true);
  collect_rule_spans(tree, spans, nullptr, nRules, /*outermost=*/false);
  collect_rule_spans(tree, spans, keep.data(), nRules, /*outermost=*/true);
}

int main() {
  const int iterations = 200;  // vary heap reuse; ASan reports on first bad access
  for (const auto &g : GRAMMARS) {
    std::unique_ptr<atn::ATN> lexerAtn = deserialize(g.lexerAtn);
    std::unique_ptr<atn::ATN> parserAtn = deserialize(g.parserAtn);
    dfa::Vocabulary lexerVocab(g.lexerLiteral, g.lexerSymbolic);
    dfa::Vocabulary parserVocab(g.parserLiteral, g.parserSymbolic);
    for (int i = 0; i < iterations; ++i) {
      for (const std::string &text : g.inputs) {
        parse_once(g, *lexerAtn, *parserAtn, lexerVocab, parserVocab, text);
      }
    }
    std::cout << "  " << g.name << ": " << g.inputs.size() << " inputs x "
              << iterations << " iterations, clean" << std::endl;
  }
  std::cout << "ASan harness: all grammars parsed without memory errors"
            << std::endl;
  return 0;
}
