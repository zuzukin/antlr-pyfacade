# Generated from Schema.g4 by ANTLR 4.13.2
# encoding: utf-8
from antlr4 import *
from io import StringIO
import sys
if sys.version_info[1] > 5:
	from typing import TextIO
else:
	from typing.io import TextIO

def serializedATN():
    return [
        4,1,12,57,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,1,0,5,
        0,14,8,0,10,0,12,0,17,9,0,1,0,1,0,1,1,1,1,3,1,23,8,1,1,2,1,2,1,2,
        1,2,5,2,29,8,2,10,2,12,2,32,9,2,1,2,1,2,1,3,1,3,1,3,1,3,1,4,1,4,
        1,5,1,5,1,5,1,5,1,5,1,5,5,5,48,8,5,10,5,12,5,51,9,5,3,5,53,8,5,1,
        5,1,5,1,5,0,0,6,0,2,4,6,8,10,0,1,2,0,3,5,10,10,55,0,15,1,0,0,0,2,
        22,1,0,0,0,4,24,1,0,0,0,6,35,1,0,0,0,8,39,1,0,0,0,10,41,1,0,0,0,
        12,14,3,2,1,0,13,12,1,0,0,0,14,17,1,0,0,0,15,13,1,0,0,0,15,16,1,
        0,0,0,16,18,1,0,0,0,17,15,1,0,0,0,18,19,5,0,0,1,19,1,1,0,0,0,20,
        23,3,4,2,0,21,23,3,10,5,0,22,20,1,0,0,0,22,21,1,0,0,0,23,3,1,0,0,
        0,24,25,5,1,0,0,25,26,5,10,0,0,26,30,5,6,0,0,27,29,3,6,3,0,28,27,
        1,0,0,0,29,32,1,0,0,0,30,28,1,0,0,0,30,31,1,0,0,0,31,33,1,0,0,0,
        32,30,1,0,0,0,33,34,5,7,0,0,34,5,1,0,0,0,35,36,3,8,4,0,36,37,5,10,
        0,0,37,38,5,8,0,0,38,7,1,0,0,0,39,40,7,0,0,0,40,9,1,0,0,0,41,42,
        5,2,0,0,42,43,5,10,0,0,43,52,5,6,0,0,44,49,5,10,0,0,45,46,5,9,0,
        0,46,48,5,10,0,0,47,45,1,0,0,0,48,51,1,0,0,0,49,47,1,0,0,0,49,50,
        1,0,0,0,50,53,1,0,0,0,51,49,1,0,0,0,52,44,1,0,0,0,52,53,1,0,0,0,
        53,54,1,0,0,0,54,55,5,7,0,0,55,11,1,0,0,0,5,15,22,30,49,52
    ]

class SchemaParser ( Parser ):

    grammarFileName = "Schema.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    sharedContextCache = PredictionContextCache()

    literalNames = [ "<INVALID>", "'message'", "'enum'", "'int'", "'string'", 
                     "'bool'", "'{'", "'}'", "';'", "','" ]

    symbolicNames = [ "<INVALID>", "MESSAGE", "ENUM", "INT", "STRING", "BOOL", 
                      "LBRACE", "RBRACE", "SEMI", "COMMA", "ID", "WS", "COMMENT" ]

    RULE_schema = 0
    RULE_definition = 1
    RULE_messageDef = 2
    RULE_field = 3
    RULE_fieldType = 4
    RULE_enumDef = 5

    ruleNames =  [ "schema", "definition", "messageDef", "field", "fieldType", 
                   "enumDef" ]

    EOF = Token.EOF
    MESSAGE=1
    ENUM=2
    INT=3
    STRING=4
    BOOL=5
    LBRACE=6
    RBRACE=7
    SEMI=8
    COMMA=9
    ID=10
    WS=11
    COMMENT=12

    def __init__(self, input:TokenStream, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.2")
        self._interp = ParserATNSimulator(self, self.atn, self.decisionsToDFA, self.sharedContextCache)
        self._predicates = None




    class SchemaContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def EOF(self):
            return self.getToken(SchemaParser.EOF, 0)

        def definition(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(SchemaParser.DefinitionContext)
            else:
                return self.getTypedRuleContext(SchemaParser.DefinitionContext,i)


        def getRuleIndex(self):
            return SchemaParser.RULE_schema




    def schema(self):

        localctx = SchemaParser.SchemaContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_schema)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 15
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==1 or _la==2:
                self.state = 12
                self.definition()
                self.state = 17
                self._errHandler.sync(self)
                _la = self._input.LA(1)

            self.state = 18
            self.match(SchemaParser.EOF)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class DefinitionContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def messageDef(self):
            return self.getTypedRuleContext(SchemaParser.MessageDefContext,0)


        def enumDef(self):
            return self.getTypedRuleContext(SchemaParser.EnumDefContext,0)


        def getRuleIndex(self):
            return SchemaParser.RULE_definition




    def definition(self):

        localctx = SchemaParser.DefinitionContext(self, self._ctx, self.state)
        self.enterRule(localctx, 2, self.RULE_definition)
        try:
            self.state = 22
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [1]:
                self.enterOuterAlt(localctx, 1)
                self.state = 20
                self.messageDef()
                pass
            elif token in [2]:
                self.enterOuterAlt(localctx, 2)
                self.state = 21
                self.enumDef()
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class MessageDefContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def MESSAGE(self):
            return self.getToken(SchemaParser.MESSAGE, 0)

        def ID(self):
            return self.getToken(SchemaParser.ID, 0)

        def LBRACE(self):
            return self.getToken(SchemaParser.LBRACE, 0)

        def RBRACE(self):
            return self.getToken(SchemaParser.RBRACE, 0)

        def field(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(SchemaParser.FieldContext)
            else:
                return self.getTypedRuleContext(SchemaParser.FieldContext,i)


        def getRuleIndex(self):
            return SchemaParser.RULE_messageDef




    def messageDef(self):

        localctx = SchemaParser.MessageDefContext(self, self._ctx, self.state)
        self.enterRule(localctx, 4, self.RULE_messageDef)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 24
            self.match(SchemaParser.MESSAGE)
            self.state = 25
            self.match(SchemaParser.ID)
            self.state = 26
            self.match(SchemaParser.LBRACE)
            self.state = 30
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while (((_la) & ~0x3f) == 0 and ((1 << _la) & 1080) != 0):
                self.state = 27
                self.field()
                self.state = 32
                self._errHandler.sync(self)
                _la = self._input.LA(1)

            self.state = 33
            self.match(SchemaParser.RBRACE)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class FieldContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def fieldType(self):
            return self.getTypedRuleContext(SchemaParser.FieldTypeContext,0)


        def ID(self):
            return self.getToken(SchemaParser.ID, 0)

        def SEMI(self):
            return self.getToken(SchemaParser.SEMI, 0)

        def getRuleIndex(self):
            return SchemaParser.RULE_field




    def field(self):

        localctx = SchemaParser.FieldContext(self, self._ctx, self.state)
        self.enterRule(localctx, 6, self.RULE_field)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 35
            self.fieldType()
            self.state = 36
            self.match(SchemaParser.ID)
            self.state = 37
            self.match(SchemaParser.SEMI)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class FieldTypeContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def INT(self):
            return self.getToken(SchemaParser.INT, 0)

        def STRING(self):
            return self.getToken(SchemaParser.STRING, 0)

        def BOOL(self):
            return self.getToken(SchemaParser.BOOL, 0)

        def ID(self):
            return self.getToken(SchemaParser.ID, 0)

        def getRuleIndex(self):
            return SchemaParser.RULE_fieldType




    def fieldType(self):

        localctx = SchemaParser.FieldTypeContext(self, self._ctx, self.state)
        self.enterRule(localctx, 8, self.RULE_fieldType)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 39
            _la = self._input.LA(1)
            if not((((_la) & ~0x3f) == 0 and ((1 << _la) & 1080) != 0)):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class EnumDefContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def ENUM(self):
            return self.getToken(SchemaParser.ENUM, 0)

        def ID(self, i:int=None):
            if i is None:
                return self.getTokens(SchemaParser.ID)
            else:
                return self.getToken(SchemaParser.ID, i)

        def LBRACE(self):
            return self.getToken(SchemaParser.LBRACE, 0)

        def RBRACE(self):
            return self.getToken(SchemaParser.RBRACE, 0)

        def COMMA(self, i:int=None):
            if i is None:
                return self.getTokens(SchemaParser.COMMA)
            else:
                return self.getToken(SchemaParser.COMMA, i)

        def getRuleIndex(self):
            return SchemaParser.RULE_enumDef




    def enumDef(self):

        localctx = SchemaParser.EnumDefContext(self, self._ctx, self.state)
        self.enterRule(localctx, 10, self.RULE_enumDef)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 41
            self.match(SchemaParser.ENUM)
            self.state = 42
            self.match(SchemaParser.ID)
            self.state = 43
            self.match(SchemaParser.LBRACE)
            self.state = 52
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==10:
                self.state = 44
                self.match(SchemaParser.ID)
                self.state = 49
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                while _la==9:
                    self.state = 45
                    self.match(SchemaParser.COMMA)
                    self.state = 46
                    self.match(SchemaParser.ID)
                    self.state = 51
                    self._errHandler.sync(self)
                    _la = self._input.LA(1)



            self.state = 54
            self.match(SchemaParser.RBRACE)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx





