// A tiny schema / interface-definition language: a file is a sequence of
// independent `message` (struct) and `enum` definitions. Each definition is
// self-contained and may span many lines, which is exactly what lets antlrope
// chunk a large schema on grammar structure and parse the pieces in parallel.
//
// Target-agnostic: no embedded actions and no semantic predicates, so the
// interpreted ATN parses it faithfully. Keywords and punctuation are given named
// lexer rules (MESSAGE, LBRACE, …) so the generated facade exposes readable
// token-type constants instead of ANTLR's positional `T__n`.
grammar Schema;

schema      : definition* EOF ;
definition  : messageDef | enumDef ;

// A message groups named, typed fields:  message Point { int x; int y; }
messageDef  : MESSAGE ID LBRACE field* RBRACE ;
field       : fieldType ID SEMI ;
fieldType   : INT | STRING | BOOL | ID ;     // a builtin, or a reference to another type

// An enum lists named constants:  enum Color { RED, GREEN, BLUE }
enumDef     : ENUM ID LBRACE (ID (COMMA ID)*)? RBRACE ;

MESSAGE : 'message' ;
ENUM    : 'enum' ;
INT     : 'int' ;
STRING  : 'string' ;
BOOL    : 'bool' ;

LBRACE  : '{' ;
RBRACE  : '}' ;
SEMI    : ';' ;
COMMA   : ',' ;

ID      : [a-zA-Z_] [a-zA-Z_0-9]* ;

WS      : [ \t\r\n]+ -> skip ;
COMMENT : '//' ~[\r\n]* -> skip ;
