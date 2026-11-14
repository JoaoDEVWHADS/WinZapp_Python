"""Spell checking through macOS's NSSpellChecker.

WinZapp's checker (core/spell_checker.py) plays the spelling-error sound
when a just-finished word is misspelled; everything around that — the
word-boundary test, the three-way setting, the sound event — is kept. Only
the Windows Spell Checking API (COM) is replaced: ranges now come from the
Mac's own dictionaries, in WinZapp's language when macOS has it.
"""

import logging


def _mac_language(tag):
    """'pt-BR' -> the best NSSpellChecker language ('pt_BR' / 'pt'), or
    None to let macOS pick."""
    try:
        from AppKit import NSSpellChecker
        available = [str(l) for l in NSSpellChecker.sharedSpellChecker().availableLanguages()]
    except Exception:
        return None
    if not tag:
        return None
    wanted = [tag.replace("-", "_"), tag.split("-")[0]]
    for w in wanted:
        for a in available:
            if a.lower() == w.lower():
                return a
    return None


def _get_checker(self):
    if self._initialized:
        return self._checker
    self._initialized = True
    try:
        from AppKit import NSSpellChecker
        self._checker = NSSpellChecker.sharedSpellChecker()
        self.language = _mac_language(self.preferred_language) or ""
    except Exception:
        logging.debug("[spell_mac] NSSpellChecker unavailable", exc_info=True)
        self._checker = None
    return self._checker


def errors_for_text(self, text):
    text = text or ""
    if not text:
        return []
    checker = self._get_checker()
    if checker is None:
        return []
    errors, start = [], 0
    try:
        while start < len(text):
            rng, _count = checker.checkSpellingOfString_startingAt_language_wrap_inSpellDocumentWithTag_wordCount_(
                text, start, self.language or None, False, 0, None)
            loc, length = rng.location, rng.length
            if length == 0 or loc >= len(text) or loc < start:
                break
            errors.append((loc, loc + length))
            start = loc + length
    except Exception:
        logging.debug("[spell_mac] check failed", exc_info=True)
        return []
    return errors


def install():
    from core import spell_checker
    cls = spell_checker.WindowsSpellChecker
    cls._get_checker = _get_checker
    cls.errors_for_text = errors_for_text
