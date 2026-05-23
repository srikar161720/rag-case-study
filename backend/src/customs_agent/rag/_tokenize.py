"""Single-source-of-truth tokenizer for BM25 indexing and retrieval (Fork 16).

The retriever and the build-time index must tokenize identically — a
mismatch silently corrupts ranking. This module owns the regex.

Default whitespace/punctuation tokenizers split ``9903.88.15`` into three
tokens (``9903``, ``88``, ``15``). Customs codes (HTS, Chapter 99
sub-codes) must stay as a single token so a query for "section 301 code
9903.88.15" can lexically match the chunk where that code is defined.
The regex below matches dotted numeric sequences FIRST, then falls back
to word characters — putting the dotted alternative first is what makes
the dotted-number variant win the longest-match race.
"""

import re

_TOKEN_RE = re.compile(r"\d+\.\d+\.\d+|\w+")


def tokenize(text: str) -> list[str]:
    """Tokenize ``text`` for BM25.

    Lowercases first so casing doesn't fragment matches; preserves dotted
    numeric sequences (``XXXX.XX.XXXX`` HTS codes, Chapter 99 codes like
    ``9903.88.15``) as single tokens.

    Parameters
    ----------
    text
        Arbitrary input — chunk body or user query.

    Returns
    -------
    list[str]
        Lowercase token list. Empty if ``text`` has no word characters.
    """
    return _TOKEN_RE.findall(text.lower())
