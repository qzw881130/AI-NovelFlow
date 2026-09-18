"""Deterministic explicit-speech facts, independent of proposed Treatment types."""
import re

GRAMMAR_VERSION = 'source-attribution-v1'
QUOTATION = re.compile(r'“([^”]*)”|"([^"\n]*)"|「([^」]*)」|『([^』]*)』|‘([^’]*)’')
SPEAKING = re.compile(r'(?:曰|说(?:道|着|完)?|道|问(?:道)?|回答|答(?:道)?|喊(?:道)?|喝(?:道)?|叱|呼|唱)\s*$')
UNSPOKEN = re.compile(
    r'(?:书|写|刻|印|题|题字|碑文|标语|标题|招牌|标注|命名|称为|名为|号为|名叫|'
    r'(?:心(?:里|中)?|暗(?:自)?)(?:想|道|说|念|忖|思忖)|想道|默念|寻思)(?:着|有|了|道)?\s*$')


def attribution(clause):
    phrase = clause.rstrip(' \t\r\n，,:：')
    if UNSPOKEN.search(phrase):return 'UNSPOKEN'
    if SPEAKING.search(phrase):return 'SPEECH'
    return None


def direct_speech_matches(content):
    """Recognize only the documented reporting-clause/quotation grammar.

    A colon alone is not a speech predicate. Reporting text that introduces the
    next quote is never borrowed as the previous quote's postposed attribution.
    """
    quotes=list(QUOTATION.finditer(content))
    for index,match in enumerate(quotes):
        left=quotes[index-1].end() if index else 0
        # Strip trailing formatting before finding a clause boundary. This keeps
        # colon + LF/CRLF attached while still respecting preceding sentences.
        leading=content[left:match.start()].rstrip()
        prefix=re.split(r'[。！？!?；;\n]',leading)[-1]
        kind = attribution(prefix)
        if kind == 'UNSPOKEN':
            continue
        right=quotes[index+1].start() if index+1<len(quotes) else len(content)
        trailing=content[match.end():right].lstrip(' \t\r\n，,')
        terminal=re.match(r'([^。！？!?；;：:，,\r\n]*?)(?:[。！？!?；;]|$)',trailing)
        if kind == 'SPEECH' or (terminal and attribution(terminal[1])=='SPEECH'):
            yield match


def direct_speech_quotes(content):
    return [next(value for value in match.groups() if value is not None)
            for match in direct_speech_matches(content)]
