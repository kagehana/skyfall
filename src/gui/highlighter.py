from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


def _fmt(hex_color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(hex_color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


_KW_FMT = _fmt("#f472b6", bold=True)  # pink - keywords
_STR_FMT = _fmt("#86efac")  # green - strings
_CMT_FMT = _fmt("#6b7280")  # gray - comments
_NUM_FMT = _fmt("#fb923c")  # amber - numbers
_GLOBAL_FMT = _fmt("#93c5fd")  # blue - builtins / bridge globals

_KEYWORDS = {
    "and",
    "break",
    "do",
    "else",
    "elseif",
    "end",
    "false",
    "for",
    "function",
    "goto",
    "if",
    "in",
    "local",
    "nil",
    "not",
    "or",
    "repeat",
    "return",
    "then",
    "true",
    "until",
    "while",
}

_BUILTINS = {
    "print",
    "pairs",
    "ipairs",
    "type",
    "tostring",
    "tonumber",
    "string",
    "table",
    "math",
    "io",
    "os",
    "coroutine",
    "pcall",
    "xpcall",
    "error",
    "assert",
    "select",
    "rawget",
    "rawset",
    "setmetatable",
    "getmetatable",
    "require",
    # SkyFall bridge globals
    "sleep",
    "wait_free",
    "wait_battle",
    "wait_dialog",
    "wait_window",
    "send_key",
    "click_window",
    "window_text",
    "boss_nearby",
    "in_zone",
    "in_combat",
    "enemy_is_death",
    "load_playstyle",
    "navigate",
    "teleport",
    "to_zone",
    "health",
    "mana",
    "energy",
    "log",
}


class LuaSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._rules = []

        kw_alt = "|".join(sorted(_KEYWORDS, key=len, reverse=True))
        self._rules.append((QRegularExpression(rf"\b(?:{kw_alt})\b"), _KW_FMT))

        bt_alt = "|".join(sorted(_BUILTINS, key=len, reverse=True))
        self._rules.append((QRegularExpression(rf"\b(?:{bt_alt})\b"), _GLOBAL_FMT))

        self._rules.append((QRegularExpression(r"\b0x[0-9a-fA-F]+\b"), _NUM_FMT))
        self._rules.append(
            (QRegularExpression(r"\b\d+\.?\d*(?:[eE][+-]?\d+)?\b"), _NUM_FMT)
        )

        self._rules.append((QRegularExpression(r'"(?:[^"\\]|\\.)*"'), _STR_FMT))
        self._rules.append((QRegularExpression(r"'(?:[^'\\]|\\.)*'"), _STR_FMT))

    def highlightBlock(self, text):
        for pat, fmt in self._rules:
            it = pat.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        self.setCurrentBlockState(0)
        prev = self.previousBlockState()
        start = 0

        if prev == 1:
            end = text.find("]]")
            if end == -1:
                self.setFormat(0, len(text), _STR_FMT)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 2, _STR_FMT)
            start = end + 2
        elif prev == 2:
            end = text.find("]]")
            if end == -1:
                self.setFormat(0, len(text), _CMT_FMT)
                self.setCurrentBlockState(2)
                return
            self.setFormat(0, end + 2, _CMT_FMT)
            start = end + 2

        i = start
        while i < len(text):
            if text[i : i + 4] == "--[[":
                end = text.find("]]", i + 4)
                if end == -1:
                    self.setFormat(i, len(text) - i, _CMT_FMT)
                    self.setCurrentBlockState(2)
                    return
                self.setFormat(i, end + 2 - i, _CMT_FMT)
                i = end + 2
            elif text[i : i + 2] == "--":
                self.setFormat(i, len(text) - i, _CMT_FMT)
                return
            elif text[i : i + 2] == "[[":
                end = text.find("]]", i + 2)
                if end == -1:
                    self.setFormat(i, len(text) - i, _STR_FMT)
                    self.setCurrentBlockState(1)
                    return
                self.setFormat(i, end + 2 - i, _STR_FMT)
                i = end + 2
            else:
                i += 1
