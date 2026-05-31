// Bulk-event-stream collector: an iterative DFS over a finished parse tree that
// emits a flat (kind, payload, start, stop) int32 record per visited item into
// one contiguous buffer. Driven by the grammar-agnostic ParserInterpreter path
// in binding.cpp. Traversal mirrors IterativeParseTreeWalker (pre-order
// enter/terminal, post-order exit).
#pragma once

#include <cstdint>
#include <optional>
#include <utility>
#include <vector>

#include "RuleContext.h"
#include "Token.h"
#include "tree/ErrorNode.h"
#include "tree/ParseTree.h"
#include "tree/TerminalNode.h"

namespace antlr_pyfacade_events {

enum EventKind : int32_t {
    EV_ENTER_RULE = 0,
    EV_EXIT_RULE = 1,
    EV_TERMINAL = 2,
    EV_ERROR = 3,
};

// Build a keep-mask of size n from a Python index list. Callers pass nullptr
// (not this table) when a mask is absent, which collect_events reads as
// "keep all".
inline std::vector<char> make_mask(
    const std::optional<std::vector<int32_t>> &idx, size_t n) {
    std::vector<char> keep(n, 0);
    for (int32_t i : *idx) {
        if (i >= 0 && static_cast<size_t>(i) < n)
            keep[static_cast<size_t>(i)] = 1;
    }
    return keep;
}

inline void collect_events(antlr4::tree::ParseTree *root,
                           std::vector<int32_t> &out, const char *rule_keep,
                           size_t n_rules, const char *tok_keep,
                           size_t n_toks) {
    using namespace antlr4;
    std::vector<std::pair<tree::ParseTree *, size_t>> stack;
    tree::ParseTree *node = root;
    size_t index = 0;

    auto push = [&](int32_t kind, int32_t payload, int32_t start, int32_t stop) {
        out.push_back(kind);
        out.push_back(payload);
        out.push_back(start);
        out.push_back(stop);
    };

    while (node != nullptr) {
        // pre-order
        if (tree::TerminalNode::is(*node)) {
            Token *sym = static_cast<tree::TerminalNode *>(node)->getSymbol();
            size_t type = sym->getType();
            bool is_err = tree::ErrorNode::is(*node);
            bool keep = tok_keep == nullptr || (type < n_toks && tok_keep[type]);
            if (keep) {
                push(is_err ? EV_ERROR : EV_TERMINAL, static_cast<int32_t>(type),
                     static_cast<int32_t>(sym->getStartIndex()),
                     static_cast<int32_t>(sym->getStopIndex()));
            }
        } else {
            size_t ridx = static_cast<RuleContext *>(node)->getRuleIndex();
            if (rule_keep == nullptr || (ridx < n_rules && rule_keep[ridx])) {
                push(EV_ENTER_RULE, static_cast<int32_t>(ridx), -1, -1);
            }
        }

        if (!node->children.empty()) {
            stack.emplace_back(node, index);
            index = 0;
            node = node->children[0];
            continue;
        }

        do {
            // post-order (rules only)
            if (!tree::TerminalNode::is(*node)) {
                size_t ridx = static_cast<RuleContext *>(node)->getRuleIndex();
                if (rule_keep == nullptr || (ridx < n_rules && rule_keep[ridx])) {
                    push(EV_EXIT_RULE, static_cast<int32_t>(ridx), -1, -1);
                }
            }
            if (stack.empty()) {
                node = nullptr;
                index = 0;
                break;
            }
            if (stack.back().first->children.size() > ++index) {
                node = stack.back().first->children[index];
                break;
            }
            std::tie(node, index) = stack.back();
            stack.pop_back();
        } while (node != nullptr);
    }
}

}  // namespace antlr_pyfacade_events
