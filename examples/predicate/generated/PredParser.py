# Generated from Pred.g4 by ANTLR 4.13.2
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
        4,1,2,9,2,0,7,0,1,0,1,0,1,0,1,0,3,0,7,8,0,1,0,0,0,1,0,0,0,8,0,6,
        1,0,0,0,2,3,4,0,0,0,3,7,5,1,0,0,4,5,5,1,0,0,5,7,5,1,0,0,6,2,1,0,
        0,0,6,4,1,0,0,0,7,1,1,0,0,0,1,6
    ]

class PredParser ( Parser ):

    grammarFileName = "Pred.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    sharedContextCache = PredictionContextCache()

    literalNames = [ "<INVALID>", "'a'" ]

    symbolicNames = [ "<INVALID>", "A", "WS" ]

    RULE_s = 0

    ruleNames =  [ "s" ]

    EOF = Token.EOF
    A=1
    WS=2

    def __init__(self, input:TokenStream, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.2")
        self._interp = ParserATNSimulator(self, self.atn, self.decisionsToDFA, self.sharedContextCache)
        self._predicates = None




    class SContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def A(self, i:int=None):
            if i is None:
                return self.getTokens(PredParser.A)
            else:
                return self.getToken(PredParser.A, i)

        def getRuleIndex(self):
            return PredParser.RULE_s

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterS" ):
                listener.enterS(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitS" ):
                listener.exitS(self)




    def s(self):

        localctx = PredParser.SContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_s)
        try:
            self.state = 6
            self._errHandler.sync(self)
            la_ = self._interp.adaptivePredict(self._input,0,self._ctx)
            if la_ == 1:
                self.enterOuterAlt(localctx, 1)
                self.state = 2
                if not False:
                    from antlr4.error.Errors import FailedPredicateException
                    raise FailedPredicateException(self, "False")
                self.state = 3
                self.match(PredParser.A)
                pass

            elif la_ == 2:
                self.enterOuterAlt(localctx, 2)
                self.state = 4
                self.match(PredParser.A)
                self.state = 5
                self.match(PredParser.A)
                pass


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx



    def sempred(self, localctx:RuleContext, ruleIndex:int, predIndex:int):
        if self._predicates == None:
            self._predicates = dict()
        self._predicates[0] = self.s_sempred
        pred = self._predicates.get(ruleIndex, None)
        if pred is None:
            raise Exception("No predicate with index:" + str(ruleIndex))
        else:
            return pred(localctx, predIndex)

    def s_sempred(self, localctx:SContext, predIndex:int):
            if predIndex == 0:
                return False
         




