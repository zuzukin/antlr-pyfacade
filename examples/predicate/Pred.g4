grammar Pred;

// `s` has a predicate-gated alternative whose predicate is *always false*.
// In a real ANTLR-generated parser the first alternative is therefore never
// taken, so the single-token input "a" is a syntax error (the only non-predicated
// way to match `s` needs two A's). The ATN interpreter this runtime drives cannot
// evaluate target-language semantic predicates, so it treats `{False}?` as true
// and happily matches "a" via the first alternative. That divergence is the
// documented limitation; tests/test_predicate_limitation.py pins it.
s : {False}? A
  | A A
  ;

A  : 'a' ;
WS : [ \t\r\n]+ -> skip ;
