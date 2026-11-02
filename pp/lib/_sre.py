"""Pure-Python _sre, executed by the pp VM (replaces the C regex engine).

Semantics follow Modules/_sre/sre.c and sre_lib.h of CPython 3.15: the
compiler in re/_compiler.py emits an opcode list and `compile()` here returns
a Pattern whose matcher interprets that list with the same backtracking rules
(MARK, REPEAT/MAX_UNTIL/MIN_UNTIL, POSSESSIVE_REPEAT, ATOMIC_GROUP,
GROUPREF*, ASSERT/ASSERT_NOT, charsets, categories, IGNORE variants).

Limitations (also in BLOCKERS.md):

* Speed: an interpreter inside an interpreter. Only the INFO block's literal
  prefix / charset search shortcuts and minimum length are used; everything
  else is a plain opcode loop.
* Recursion: where C keeps an explicit heap stack, each backtracking point
  here is a Python call, so a pattern that needs more nested backtrack
  points than the interpreter's recursion limit (e.g. `(?:a|b)*` over a very
  long string) raises RecursionError instead of matching.
* No code validation: `compile()` trusts the opcode list (C runs `_validate`
  and raises RuntimeError("invalid SRE code")). Malformed lists may raise
  IndexError or loop instead.
* Locale: re.LOCALE behaves as the "C" locale (ASCII case mapping and word
  characters) regardless of the process locale.
* Signals are not checked while matching (no KeyboardInterrupt mid-match).
* Subject strings are copied to a bytes/list-of-ordinals buffer per call.
* Pattern._fail_after (debug builds only) is not provided.
"""


__all__ = [
    "MAGIC", "CODESIZE", "MAXREPEAT", "MAXGROUPS", "getcodesize",
    "ascii_iscased", "unicode_iscased", "ascii_tolower", "unicode_tolower",
    "template", "compile",
]

MAGIC = 20230612
CODESIZE = 4
MAXREPEAT = 0xFFFFFFFF
MAXGROUPS = 0x7FFFFFFF // 2

_MAXSIZE = 0x7FFFFFFFFFFFFFFF

# opcodes (re/_constants.py OPCODES)
(FAILURE, SUCCESS, ANY, ANY_ALL, ASSERT, ASSERT_NOT, AT, BRANCH, CATEGORY,
 CHARSET, BIGCHARSET, GROUPREF, GROUPREF_EXISTS, IN, INFO, JUMP, LITERAL,
 MARK, MAX_UNTIL, MIN_UNTIL, NOT_LITERAL, NEGATE, RANGE, REPEAT, REPEAT_ONE,
 SUBPATTERN, MIN_REPEAT_ONE, ATOMIC_GROUP, POSSESSIVE_REPEAT,
 POSSESSIVE_REPEAT_ONE, GROUPREF_IGNORE, IN_IGNORE, LITERAL_IGNORE,
 NOT_LITERAL_IGNORE, GROUPREF_LOC_IGNORE, IN_LOC_IGNORE, LITERAL_LOC_IGNORE,
 NOT_LITERAL_LOC_IGNORE, GROUPREF_UNI_IGNORE, IN_UNI_IGNORE,
 LITERAL_UNI_IGNORE, NOT_LITERAL_UNI_IGNORE, RANGE_UNI_IGNORE) = range(43)

# positions (ATCODES)
(AT_BEGINNING, AT_BEGINNING_LINE, AT_BEGINNING_STRING, AT_BOUNDARY,
 AT_NON_BOUNDARY, AT_END, AT_END_LINE, AT_END_STRING, AT_LOC_BOUNDARY,
 AT_LOC_NON_BOUNDARY, AT_UNI_BOUNDARY, AT_UNI_NON_BOUNDARY) = range(12)

# categories (CHCODES)
(CATEGORY_DIGIT, CATEGORY_NOT_DIGIT, CATEGORY_SPACE, CATEGORY_NOT_SPACE,
 CATEGORY_WORD, CATEGORY_NOT_WORD, CATEGORY_LINEBREAK, CATEGORY_NOT_LINEBREAK,
 CATEGORY_LOC_WORD, CATEGORY_LOC_NOT_WORD, CATEGORY_UNI_DIGIT,
 CATEGORY_UNI_NOT_DIGIT, CATEGORY_UNI_SPACE, CATEGORY_UNI_NOT_SPACE,
 CATEGORY_UNI_WORD, CATEGORY_UNI_NOT_WORD, CATEGORY_UNI_LINEBREAK,
 CATEGORY_UNI_NOT_LINEBREAK) = range(18)

SRE_FLAG_IGNORECASE = 2
SRE_FLAG_LOCALE = 4
SRE_FLAG_MULTILINE = 8
SRE_FLAG_DOTALL = 16
SRE_FLAG_UNICODE = 32
SRE_FLAG_VERBOSE = 64
SRE_FLAG_DEBUG = 128
SRE_FLAG_ASCII = 256

SRE_INFO_PREFIX = 1
SRE_INFO_LITERAL = 2
SRE_INFO_CHARSET = 4

_GenericAlias = type(list[int])
_MappingProxy = type(type.__dict__)


# ---------------------------------------------------------------------------
# character predicates

def _lower_ascii(ch):
    return ch + 32 if 65 <= ch <= 90 else ch


def _upper_ascii(ch):
    return ch - 32 if 97 <= ch <= 122 else ch


_lower_cache = {}
_upper_cache = {}


def _lower_unicode(ch):
    if ch < 128:
        return ch + 32 if 65 <= ch <= 90 else ch
    r = _lower_cache.get(ch)
    if r is None:
        r = _lower_cache[ch] = ord(chr(ch).lower()[0])
    return r


def _upper_unicode(ch):
    if ch < 128:
        return ch - 32 if 97 <= ch <= 122 else ch
    r = _upper_cache.get(ch)
    if r is None:
        r = _upper_cache[ch] = ord(chr(ch).upper()[0])
    return r


# locale predicates: the "C" locale
_lower_locale = _lower_ascii
_upper_locale = _upper_ascii


def _is_word_ascii(ch):
    return (48 <= ch <= 57) or (65 <= ch <= 90) or (97 <= ch <= 122) or ch == 95


_LINEBREAKS = frozenset((0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029))


def _is_word_unicode(ch):
    return ch == 95 or chr(ch).isalnum()


def _category(cat, ch):
    if cat == CATEGORY_DIGIT:
        return 48 <= ch <= 57
    if cat == CATEGORY_NOT_DIGIT:
        return not 48 <= ch <= 57
    if cat == CATEGORY_SPACE:
        return ch in (9, 10, 11, 12, 13, 32)
    if cat == CATEGORY_NOT_SPACE:
        return ch not in (9, 10, 11, 12, 13, 32)
    if cat == CATEGORY_WORD:
        return _is_word_ascii(ch)
    if cat == CATEGORY_NOT_WORD:
        return not _is_word_ascii(ch)
    if cat == CATEGORY_LINEBREAK:
        return ch == 10
    if cat == CATEGORY_NOT_LINEBREAK:
        return ch != 10
    if cat == CATEGORY_LOC_WORD:
        return _is_word_ascii(ch)
    if cat == CATEGORY_LOC_NOT_WORD:
        return not _is_word_ascii(ch)
    if cat == CATEGORY_UNI_DIGIT:
        return chr(ch).isdecimal()
    if cat == CATEGORY_UNI_NOT_DIGIT:
        return not chr(ch).isdecimal()
    if cat == CATEGORY_UNI_SPACE:
        return chr(ch).isspace()
    if cat == CATEGORY_UNI_NOT_SPACE:
        return not chr(ch).isspace()
    if cat == CATEGORY_UNI_WORD:
        return _is_word_unicode(ch)
    if cat == CATEGORY_UNI_NOT_WORD:
        return not _is_word_unicode(ch)
    if cat == CATEGORY_UNI_LINEBREAK:
        return ch in _LINEBREAKS
    if cat == CATEGORY_UNI_NOT_LINEBREAK:
        return ch not in _LINEBREAKS
    return False


def _char_loc_ignore(pattern, ch):
    return (ch == pattern or _lower_locale(ch) == pattern
            or _upper_locale(ch) == pattern)


# ---------------------------------------------------------------------------
# module functions

def getcodesize():
    return CODESIZE


def ascii_iscased(character):
    return character < 128 and (65 <= character <= 90 or 97 <= character <= 122)


def unicode_iscased(character):
    return character != _lower_unicode(character) or character != _upper_unicode(character)


def ascii_tolower(character):
    return _lower_ascii(character) if character < 128 else character


def unicode_tolower(character):
    return _lower_unicode(character)


# ---------------------------------------------------------------------------
# subject handling

def _index(x):
    if type(x) is int:
        return x
    m = getattr(type(x), "__index__", None)
    if m is None:
        raise TypeError("'%s' object cannot be interpreted as an integer"
                        % type(x).__name__)
    return m(x)


def _bad_string(string):
    return TypeError("expected string or bytes-like object, got '%s'"
                     % type(string).__name__)


def _getstring(string):
    """Return (data, isbytes): data is bytes or a list of code points."""
    if isinstance(string, str):
        try:
            return string.encode("latin-1"), False
        except UnicodeEncodeError:
            return [ord(c) for c in string], False
    if type(string) is bytes:
        return string, True
    try:
        return memoryview(string).tobytes(), True
    except TypeError:
        raise _bad_string(string) from None


def _find(data, ch, start, end):
    """Index of the first `ch` in data[start:end], or -1."""
    if type(data) is bytes:
        return data.find(ch, start, end)
    try:
        return data.index(ch, start, end)
    except ValueError:
        return -1


class _Repeat:
    __slots__ = ("count", "pc", "prev", "last_ptr")

    def __init__(self, pc, prev):
        self.count = -1
        self.pc = pc
        self.prev = prev
        self.last_ptr = -1


class _State:
    """SRE_STATE: the subject plus match progress."""

    __slots__ = ("code", "data", "isbytes", "string", "start", "ptr", "end",
                 "pos", "endpos", "mark", "lastmark", "lastindex", "repeat",
                 "match_all", "must_advance", "ngroups", "flags")

    def __init__(self, pattern, string, start, end):
        data, isbytes = _getstring(string)
        if isbytes and pattern._isbytes == 0:
            raise TypeError("cannot use a string pattern on a bytes-like object")
        if not isbytes and pattern._isbytes > 0:
            raise TypeError("cannot use a bytes pattern on a string-like object")
        length = len(data)
        start = _index(start)
        end = _index(end)
        if start < 0:
            start = 0
        elif start > length:
            start = length
        if end < 0:
            end = 0
        elif end > length:
            end = length
        self.code = pattern._code
        self.ngroups = pattern._groups
        self.flags = pattern._flags
        self.data = data
        self.isbytes = isbytes
        self.string = string
        self.start = start
        self.ptr = start
        self.end = end
        self.pos = start
        self.endpos = end
        self.mark = [None] * (pattern._groups * 2)
        self.lastmark = -1
        self.lastindex = -1
        self.repeat = None
        self.match_all = False
        self.must_advance = False

    def reset(self):
        self.lastmark = -1
        self.lastindex = -1
        self.repeat = None

    def slice(self, i, j):
        string = self.string
        if self.isbytes:
            if type(string) is bytes:
                if i == 0 and j == len(string):
                    return string
                return string[i:j]
            return self.data[i:j]
        if type(string) is str:
            return string[i:j]
        return str.__getitem__(string, slice(i, j))

    def getslice(self, index, empty):
        index = (index - 1) * 2
        mark = self.mark
        if (index >= self.lastmark or mark[index] is None
                or mark[index + 1] is None):
            if empty:
                return self.slice(0, 0)
            return None
        i = mark[index]
        j = mark[index + 1]
        if i > j:
            raise SystemError("The span of capturing group is wrong,"
                              " please report a bug for the re module.")
        return self.slice(i, j)

    # -- helpers ----------------------------------------------------------

    def _at(self, ptr, at):
        data = self.data
        if at == AT_BEGINNING or at == AT_BEGINNING_STRING:
            return ptr == 0
        if at == AT_BEGINNING_LINE:
            return ptr == 0 or data[ptr - 1] == 10
        if at == AT_END:
            end = self.end
            return (end - ptr == 1 and data[ptr] == 10) or ptr == end
        if at == AT_END_LINE:
            return ptr == self.end or data[ptr] == 10
        if at == AT_END_STRING:
            return ptr == self.end
        if at == AT_BOUNDARY or at == AT_NON_BOUNDARY:
            isword = _is_word_ascii
        elif at == AT_LOC_BOUNDARY or at == AT_LOC_NON_BOUNDARY:
            isword = _is_word_ascii
        elif at == AT_UNI_BOUNDARY or at == AT_UNI_NON_BOUNDARY:
            isword = _is_word_unicode
        else:
            return False
        thatp = isword(data[ptr - 1]) if ptr > 0 else False
        thisp = isword(data[ptr]) if ptr < self.end else False
        if at in (AT_BOUNDARY, AT_LOC_BOUNDARY, AT_UNI_BOUNDARY):
            return thisp != thatp
        return thisp == thatp

    def _charset(self, pc, ch):
        code = self.code
        ok = True
        while True:
            op = code[pc]
            pc += 1
            if op == LITERAL:
                if ch == code[pc]:
                    return ok
                pc += 1
            elif op == RANGE:
                if code[pc] <= ch <= code[pc + 1]:
                    return ok
                pc += 2
            elif op == CATEGORY:
                if _category(code[pc], ch):
                    return ok
                pc += 1
            elif op == CHARSET:
                if ch < 256 and (code[pc + (ch >> 5)] >> (ch & 31)) & 1:
                    return ok
                pc += 8
            elif op == NEGATE:
                ok = not ok
            elif op == FAILURE:
                return not ok
            elif op == BIGCHARSET:
                count = code[pc]
                pc += 1
                if ch < 0x10000:
                    hi = ch >> 8
                    block = (code[pc + (hi >> 2)] >> (8 * (hi & 3))) & 255
                    if (code[pc + 64 + ((block * 256 + (ch & 255)) >> 5)] >> (ch & 31)) & 1:
                        return ok
                pc += 64 + count * 8
            elif op == RANGE_UNI_IGNORE:
                if code[pc] <= ch <= code[pc + 1]:
                    return ok
                uch = _upper_unicode(ch)
                if code[pc] <= uch <= code[pc + 1]:
                    return ok
                pc += 2
            else:
                return False

    def _charset_loc_ignore(self, pc, ch):
        lo = _lower_locale(ch)
        up = _upper_locale(ch)
        if up == lo:
            return self._charset(pc, lo)
        code = self.code
        ok = True
        while True:
            op = code[pc]
            pc += 1
            if op == FAILURE:
                return not ok
            elif op == LITERAL:
                if lo == code[pc] or up == code[pc]:
                    return ok
                pc += 1
            elif op == CATEGORY:
                if _category(code[pc], lo) or _category(code[pc], up):
                    return ok
                pc += 1
            elif op == CHARSET:
                if ((lo < 256 and (code[pc + (lo >> 5)] >> (lo & 31)) & 1) or
                        (up < 256 and (code[pc + (up >> 5)] >> (up & 31)) & 1)):
                    return ok
                pc += 8
            elif op == RANGE:
                if (code[pc] <= lo <= code[pc + 1]) or (code[pc] <= up <= code[pc + 1]):
                    return ok
                pc += 2
            elif op == NEGATE:
                ok = not ok
            else:
                return False

    def _count(self, pc, maxcount):
        code = self.code
        data = self.data
        start = ptr = self.ptr
        end = self.end
        if maxcount < end - ptr and maxcount != MAXREPEAT:
            end = ptr + maxcount
        op = code[pc]
        if op == IN:
            cs = pc + 2
            charset = self._charset
            while ptr < end and charset(cs, data[ptr]):
                ptr += 1
        elif op == ANY:
            i = _find(data, 10, ptr, end)
            ptr = end if i < 0 else i
        elif op == ANY_ALL:
            ptr = end
        elif op == LITERAL:
            chr_ = code[pc + 1]
            while ptr < end and data[ptr] == chr_:
                ptr += 1
        elif op == LITERAL_IGNORE:
            chr_ = code[pc + 1]
            while ptr < end and _lower_ascii(data[ptr]) == chr_:
                ptr += 1
        elif op == LITERAL_UNI_IGNORE:
            chr_ = code[pc + 1]
            while ptr < end and _lower_unicode(data[ptr]) == chr_:
                ptr += 1
        elif op == LITERAL_LOC_IGNORE:
            chr_ = code[pc + 1]
            while ptr < end and _char_loc_ignore(chr_, data[ptr]):
                ptr += 1
        elif op == NOT_LITERAL:
            chr_ = code[pc + 1]
            while ptr < end and data[ptr] != chr_:
                ptr += 1
        elif op == NOT_LITERAL_IGNORE:
            chr_ = code[pc + 1]
            while ptr < end and _lower_ascii(data[ptr]) != chr_:
                ptr += 1
        elif op == NOT_LITERAL_UNI_IGNORE:
            chr_ = code[pc + 1]
            while ptr < end and _lower_unicode(data[ptr]) != chr_:
                ptr += 1
        elif op == NOT_LITERAL_LOC_IGNORE:
            chr_ = code[pc + 1]
            while ptr < end and not _char_loc_ignore(chr_, data[ptr]):
                ptr += 1
        elif op == CATEGORY:
            arg = code[pc + 1]
            while ptr < end and _category(arg, data[ptr]):
                ptr += 1
        else:
            # repeated single character pattern
            match = self._match
            while self.ptr < end:
                if not match(pc, False):
                    break
            return self.ptr - start
        return ptr - start

    def _groupref(self, pc, ptr, lower):
        """Match the text of group code[pc] at ptr; return the new ptr or -1."""
        groupref = self.code[pc] * 2
        if groupref >= self.lastmark:
            return -1
        p = self.mark[groupref]
        e = self.mark[groupref + 1]
        if p is None or e is None or e < p:
            return -1
        data = self.data
        end = self.end
        while p < e:
            if ptr >= end:
                return -1
            if lower is None:
                if data[ptr] != data[p]:
                    return -1
            elif lower(data[ptr]) != lower(data[p]):
                return -1
            p += 1
            ptr += 1
        return ptr

    # -- the matcher ------------------------------------------------------

    def _match(self, pc, toplevel):
        """Run code from pc up to its SUCCESS, starting at self.ptr.

        Returns True/False; on success self.ptr is the end of the match.
        """
        code = self.code
        data = self.data
        end = self.end
        ptr = self.ptr

        if code[pc] == INFO:
            if code[pc + 3] and end - ptr < code[pc + 3]:
                return False
            pc += code[pc + 1] + 1

        while True:
            op = code[pc]
            pc += 1

            if op == LITERAL:
                if ptr >= end or data[ptr] != code[pc]:
                    return False
                pc += 1
                ptr += 1

            elif op == MARK:
                i = code[pc]
                if i & 1:
                    self.lastindex = i // 2 + 1
                if i > self.lastmark:
                    mark = self.mark
                    j = self.lastmark + 1
                    while j < i:
                        mark[j] = None
                        j += 1
                    self.lastmark = i
                self.mark[i] = ptr
                pc += 1

            elif op == SUCCESS:
                if toplevel and ((self.match_all and ptr != self.end) or
                                 (self.must_advance and ptr == self.start)):
                    return False
                self.ptr = ptr
                return True

            elif op == IN:
                if ptr >= end or not self._charset(pc + 1, data[ptr]):
                    return False
                pc += code[pc]
                ptr += 1

            elif op == ANY:
                if ptr >= end or data[ptr] == 10:
                    return False
                ptr += 1

            elif op == ANY_ALL:
                if ptr >= end:
                    return False
                ptr += 1

            elif op == NOT_LITERAL:
                if ptr >= end or data[ptr] == code[pc]:
                    return False
                pc += 1
                ptr += 1

            elif op == AT:
                if not self._at(ptr, code[pc]):
                    return False
                pc += 1

            elif op == CATEGORY:
                if ptr >= end or not _category(code[pc], data[ptr]):
                    return False
                pc += 1
                ptr += 1

            elif op == LITERAL_IGNORE:
                if ptr >= end or _lower_ascii(data[ptr]) != code[pc]:
                    return False
                pc += 1
                ptr += 1

            elif op == LITERAL_UNI_IGNORE:
                if ptr >= end or _lower_unicode(data[ptr]) != code[pc]:
                    return False
                pc += 1
                ptr += 1

            elif op == LITERAL_LOC_IGNORE:
                if ptr >= end or not _char_loc_ignore(code[pc], data[ptr]):
                    return False
                pc += 1
                ptr += 1

            elif op == NOT_LITERAL_IGNORE:
                if ptr >= end or _lower_ascii(data[ptr]) == code[pc]:
                    return False
                pc += 1
                ptr += 1

            elif op == NOT_LITERAL_UNI_IGNORE:
                if ptr >= end or _lower_unicode(data[ptr]) == code[pc]:
                    return False
                pc += 1
                ptr += 1

            elif op == NOT_LITERAL_LOC_IGNORE:
                if ptr >= end or _char_loc_ignore(code[pc], data[ptr]):
                    return False
                pc += 1
                ptr += 1

            elif op == IN_IGNORE:
                if ptr >= end or not self._charset(pc + 1, _lower_ascii(data[ptr])):
                    return False
                pc += code[pc]
                ptr += 1

            elif op == IN_UNI_IGNORE:
                if ptr >= end or not self._charset(pc + 1, _lower_unicode(data[ptr])):
                    return False
                pc += code[pc]
                ptr += 1

            elif op == IN_LOC_IGNORE:
                if ptr >= end or not self._charset_loc_ignore(pc + 1, data[ptr]):
                    return False
                pc += code[pc]
                ptr += 1

            elif op == JUMP or op == INFO:
                pc += code[pc]

            elif op == BRANCH:
                lastmark = self.lastmark
                lastindex = self.lastindex
                saved = self.mark[:lastmark + 1] if lastmark >= 0 else None
                while code[pc]:
                    first = code[pc + 1]
                    if first == LITERAL and (ptr >= end or data[ptr] != code[pc + 2]):
                        pc += code[pc]
                        continue
                    if first == IN and (ptr >= end or
                                        not self._charset(pc + 3, data[ptr])):
                        pc += code[pc]
                        continue
                    self.ptr = ptr
                    if self._match(pc + 1, toplevel):
                        return True
                    if saved is not None:
                        self.mark[:lastmark + 1] = saved
                    self.lastmark = lastmark
                    self.lastindex = lastindex
                    pc += code[pc]
                return False

            elif op == REPEAT_ONE:
                # <REPEAT_ONE> <skip> <1=min> <2=max> item <SUCCESS> tail
                rmin = code[pc + 1]
                if rmin > end - ptr:
                    return False
                self.ptr = ptr
                count = self._count(pc + 3, code[pc + 2])
                ptr += count
                if count < rmin:
                    return False
                tail = pc + code[pc]
                if (code[tail] == SUCCESS and ptr == end and
                        not (toplevel and self.must_advance and ptr == self.start)):
                    self.ptr = ptr
                    return True
                lastmark = self.lastmark
                lastindex = self.lastindex
                saved = self.mark[:lastmark + 1] if lastmark >= 0 else None
                if code[tail] == LITERAL:
                    chr_ = code[tail + 1]
                    while True:
                        while count >= rmin and (ptr >= end or data[ptr] != chr_):
                            ptr -= 1
                            count -= 1
                        if count < rmin:
                            break
                        self.ptr = ptr
                        if self._match(tail, toplevel):
                            return True
                        if saved is not None:
                            self.mark[:lastmark + 1] = saved
                        self.lastmark = lastmark
                        self.lastindex = lastindex
                        ptr -= 1
                        count -= 1
                else:
                    while count >= rmin:
                        self.ptr = ptr
                        if self._match(tail, toplevel):
                            return True
                        if saved is not None:
                            self.mark[:lastmark + 1] = saved
                        self.lastmark = lastmark
                        self.lastindex = lastindex
                        ptr -= 1
                        count -= 1
                return False

            elif op == MIN_REPEAT_ONE:
                # <MIN_REPEAT_ONE> <skip> <1=min> <2=max> item <SUCCESS> tail
                rmin = code[pc + 1]
                rmax = code[pc + 2]
                if rmin > end - ptr:
                    return False
                self.ptr = ptr
                if rmin == 0:
                    count = 0
                else:
                    count = self._count(pc + 3, rmin)
                    if count < rmin:
                        return False
                    ptr += count
                tail = pc + code[pc]
                if (code[tail] == SUCCESS and
                        not (toplevel and ((self.match_all and ptr != self.end) or
                                           (self.must_advance and ptr == self.start)))):
                    self.ptr = ptr
                    return True
                lastmark = self.lastmark
                lastindex = self.lastindex
                saved = self.mark[:lastmark + 1] if lastmark >= 0 else None
                while rmax == MAXREPEAT or count <= rmax:
                    self.ptr = ptr
                    if self._match(tail, toplevel):
                        return True
                    if saved is not None:
                        self.mark[:lastmark + 1] = saved
                    self.lastmark = lastmark
                    self.lastindex = lastindex
                    self.ptr = ptr
                    if self._count(pc + 3, 1) == 0:
                        break
                    ptr += 1
                    count += 1
                return False

            elif op == POSSESSIVE_REPEAT_ONE:
                rmin = code[pc + 1]
                if ptr + rmin > end:
                    return False
                self.ptr = ptr
                count = self._count(pc + 3, code[pc + 2])
                ptr += count
                if count < rmin:
                    return False
                pc += code[pc]
                if (code[pc] == SUCCESS and ptr == end and
                        not (toplevel and self.must_advance and ptr == self.start)):
                    self.ptr = ptr
                    return True

            elif op == REPEAT:
                # <REPEAT> <skip> <1=min> <2=max> item <UNTIL> tail
                rep = _Repeat(pc, self.repeat)
                self.repeat = rep
                self.ptr = ptr
                ret = self._match(pc + code[pc], toplevel)
                self.repeat = rep.prev
                return ret

            elif op == MAX_UNTIL:
                rep = self.repeat
                if rep is None:
                    raise SystemError("internal error in regular expression engine")
                self.ptr = ptr
                count = rep.count + 1
                rpc = rep.pc
                if count < code[rpc + 1]:
                    rep.count = count
                    if self._match(rpc + 3, toplevel):
                        return True
                    rep.count = count - 1
                    self.ptr = ptr
                    return False
                if ((count < code[rpc + 2] or code[rpc + 2] == MAXREPEAT) and
                        self.ptr != rep.last_ptr):
                    rep.count = count
                    lastmark = self.lastmark
                    lastindex = self.lastindex
                    saved = self.mark[:lastmark + 1] if lastmark >= 0 else None
                    last_ptr = rep.last_ptr
                    rep.last_ptr = self.ptr
                    ret = self._match(rpc + 3, toplevel)
                    rep.last_ptr = last_ptr
                    if ret:
                        return True
                    if saved is not None:
                        self.mark[:lastmark + 1] = saved
                    self.lastmark = lastmark
                    self.lastindex = lastindex
                    rep.count = count - 1
                    self.ptr = ptr
                self.repeat = rep.prev
                ret = self._match(pc, toplevel)
                self.repeat = rep
                if ret:
                    return True
                self.ptr = ptr
                return False

            elif op == MIN_UNTIL:
                rep = self.repeat
                if rep is None:
                    raise SystemError("internal error in regular expression engine")
                self.ptr = ptr
                count = rep.count + 1
                rpc = rep.pc
                if count < code[rpc + 1]:
                    rep.count = count
                    if self._match(rpc + 3, toplevel):
                        return True
                    rep.count = count - 1
                    self.ptr = ptr
                    return False
                self.repeat = rep.prev
                lastmark = self.lastmark
                lastindex = self.lastindex
                saved = self.mark[:lastmark + 1] if lastmark >= 0 else None
                ret = self._match(pc, toplevel)
                self.repeat = rep
                if ret:
                    return True
                if saved is not None:
                    self.mark[:lastmark + 1] = saved
                self.lastmark = lastmark
                self.lastindex = lastindex
                self.ptr = ptr
                if ((count >= code[rpc + 2] and code[rpc + 2] != MAXREPEAT) or
                        self.ptr == rep.last_ptr):
                    return False
                rep.count = count
                last_ptr = rep.last_ptr
                rep.last_ptr = self.ptr
                ret = self._match(rpc + 3, toplevel)
                rep.last_ptr = last_ptr
                if ret:
                    return True
                rep.count = count - 1
                self.ptr = ptr
                return False

            elif op == POSSESSIVE_REPEAT:
                # <POSSESSIVE_REPEAT> <skip> <1=min> <2=max> item <SUCCESS> tail
                self.ptr = ptr
                saved_repeat = self.repeat
                self.repeat = _Repeat(None, saved_repeat)
                count = 0
                rmin = code[pc + 1]
                rmax = code[pc + 2]
                while count < rmin:
                    if self._match(pc + 3, False):
                        count += 1
                    else:
                        self.ptr = ptr
                        self.repeat = saved_repeat
                        return False
                ptr = -1
                while (count < rmax or rmax == MAXREPEAT) and self.ptr != ptr:
                    lastmark = self.lastmark
                    lastindex = self.lastindex
                    saved = self.mark[:lastmark + 1] if lastmark >= 0 else None
                    ptr = self.ptr
                    if self._match(pc + 3, False):
                        count += 1
                    else:
                        if saved is not None:
                            self.mark[:lastmark + 1] = saved
                        self.lastmark = lastmark
                        self.lastindex = lastindex
                        self.ptr = ptr
                        break
                self.repeat = saved_repeat
                pc += code[pc] + 1
                ptr = self.ptr

            elif op == ATOMIC_GROUP:
                # <ATOMIC_GROUP> <skip> pattern <SUCCESS> tail
                self.ptr = ptr
                if not self._match(pc + 1, False):
                    self.ptr = ptr
                    return False
                pc += code[pc]
                ptr = self.ptr

            elif op == GROUPREF:
                ptr = self._groupref(pc, ptr, None)
                if ptr < 0:
                    return False
                pc += 1

            elif op == GROUPREF_IGNORE:
                ptr = self._groupref(pc, ptr, _lower_ascii)
                if ptr < 0:
                    return False
                pc += 1

            elif op == GROUPREF_UNI_IGNORE:
                ptr = self._groupref(pc, ptr, _lower_unicode)
                if ptr < 0:
                    return False
                pc += 1

            elif op == GROUPREF_LOC_IGNORE:
                ptr = self._groupref(pc, ptr, _lower_locale)
                if ptr < 0:
                    return False
                pc += 1

            elif op == GROUPREF_EXISTS:
                # <GROUPREF_EXISTS> <group> <skip> codeyes <JUMP> codeno ...
                groupref = code[pc] * 2
                if groupref >= self.lastmark:
                    pc += code[pc + 1]
                else:
                    p = self.mark[groupref]
                    e = self.mark[groupref + 1]
                    if p is None or e is None or e < p:
                        pc += code[pc + 1]
                    else:
                        pc += 2

            elif op == ASSERT:
                # <ASSERT> <skip> <back> <pattern>
                back = code[pc + 1]
                if ptr < back:
                    return False
                self.ptr = ptr - back
                if not self._match(pc + 2, False):
                    return False
                pc += code[pc]

            elif op == ASSERT_NOT:
                back = code[pc + 1]
                if ptr >= back:
                    self.ptr = ptr - back
                    lastmark = self.lastmark
                    lastindex = self.lastindex
                    saved = self.mark[:lastmark + 1] if lastmark >= 0 else None
                    if self._match(pc + 2, False):
                        return False
                    if saved is not None:
                        self.mark[:lastmark + 1] = saved
                    self.lastmark = lastmark
                    self.lastindex = lastindex
                pc += code[pc]

            elif op == FAILURE:
                return False

            else:
                raise RuntimeError("internal error in regular expression engine")

    # -- entry points -----------------------------------------------------

    def sre_match(self):
        return self._match(0, True)

    def sre_search(self):
        code = self.code
        data = self.data
        ptr = self.start
        end = self.end
        if ptr > end:
            return False
        pc = 0
        flags = 0
        prefix_len = 0
        prefix_skip = 0
        prefix = None
        charset = -1
        if code[0] == INFO:
            flags = code[2]
            if code[3] and end - ptr < code[3]:
                return False
            if code[3] > 1:
                end -= code[3] - 1
                if end <= ptr:
                    end = ptr
            if flags & SRE_INFO_PREFIX:
                prefix_len = code[5]
                prefix_skip = code[6]
                prefix = code[7:7 + prefix_len]
            elif flags & SRE_INFO_CHARSET:
                charset = 5
            pc = 1 + code[1]

        if prefix_len >= 1:
            end = self.end
            if type(data) is bytes:
                for c in prefix:
                    if c > 255:
                        return False
                needle = bytes(prefix)
            else:
                needle = prefix
            self.must_advance = False
            first = prefix[0]
            while ptr < end:
                if prefix_len == 1:
                    ptr = _find(data, first, ptr, end)
                    if ptr < 0:
                        return False
                else:
                    if prefix_len > end - ptr:
                        return False
                    ptr = _find(data, first, ptr, end - prefix_len + 1)
                    if ptr < 0:
                        return False
                    if data[ptr:ptr + prefix_len] != needle:
                        ptr += 1
                        continue
                self.start = ptr
                self.ptr = ptr + prefix_skip
                if flags & SRE_INFO_LITERAL:
                    return True
                if self._match(pc + 2 * prefix_skip, False):
                    return True
                ptr += 1
                self.reset()
            return False

        if charset >= 0:
            end = self.end
            self.must_advance = False
            charset_fn = self._charset
            while True:
                while ptr < end and not charset_fn(charset, data[ptr]):
                    ptr += 1
                if ptr >= end:
                    return False
                self.start = ptr
                self.ptr = ptr
                if self._match(pc, False):
                    return True
                ptr += 1
                self.reset()

        self.start = self.ptr = ptr
        status = self._match(pc, True)
        self.must_advance = False
        if (not status and code[pc] == AT and
                code[pc + 1] in (AT_BEGINNING, AT_BEGINNING_STRING)):
            self.start = self.ptr = end
            return False
        while not status and ptr < end:
            ptr += 1
            self.reset()
            self.start = self.ptr = ptr
            status = self._match(pc, False)
        return status


# ---------------------------------------------------------------------------
# Pattern / Match / Scanner / Template

class _Immutable(type):
    """Metaclass of the _sre types: like C heap types, they reject new attributes."""

    def __setattr__(cls, name, value):
        raise TypeError("cannot set %r attribute of immutable type '%s'"
                        % (name, cls.__name__))

    def __delattr__(cls, name):
        raise TypeError("cannot delete %r attribute of immutable type '%s'"
                        % (name, cls.__name__))


class SRE_Template(metaclass=_Immutable):
    """Parsed replacement template."""

    __slots__ = ("literal", "items", "chunks")
    __module__ = "_sre"


Template = SRE_Template


def template(pattern, template):
    n = len(template)
    if n < 1 or n % 2 == 0:
        raise TypeError("invalid template")
    self = object.__new__(SRE_Template)
    self.literal = template[0]
    items = []
    chunks = 1 + (n - 1)
    for i in range((n - 1) // 2):
        try:
            index = _index(template[2 * i + 1])
        except TypeError:
            raise TypeError("an integer is required") from None
        if index < 0:
            raise TypeError("invalid template")
        literal = template[2 * i + 2]
        if isinstance(literal, (str, bytes)) and len(literal) == 0:
            literal = None
            chunks -= 1
        items.append((index, literal))
    self.items = items
    self.chunks = chunks
    return self


def _compile_template(pattern, repl):
    import re
    func = re._compile_template
    try:
        result = func(pattern, repl)
    except TypeError:
        # unhashable replacement (e.g. bytearray): retry with the basic type
        if isinstance(repl, str) and type(repl) is not str:
            repl = str.__getitem__(repl, slice(None))
        elif not isinstance(repl, (str, bytes)):
            repl = memoryview(repl).tobytes()
        else:
            raise
        result = func(pattern, repl)
    if type(result) is not SRE_Template:
        raise RuntimeError("the result of compiling a replacement string is %s"
                           % type(result).__name__)
    return result


def _expand_template(tmpl, match):
    if not tmpl.items:
        return tmpl.literal
    out = [tmpl.literal]
    groups = match._groups
    for index, literal in tmpl.items:
        if index >= groups:
            raise IndexError("no such group")
        item = match._getslice_by_index(index, None)
        if item is not None:
            out.append(item)
        if literal is not None:
            out.append(literal)
    sep = "" if isinstance(tmpl.literal, str) else b""
    return sep.join(out)


class Pattern(metaclass=_Immutable):
    """Compiled regular expression object."""

    __slots__ = ("_pattern", "_flags", "_groups", "_groupindex", "_indexgroup",
                 "_code", "_isbytes", "__weakref__")
    __module__ = "re"

    def __new__(cls, *args, **kwargs):
        raise TypeError("cannot create 're.Pattern' instances")

    pattern = property(lambda self: self._pattern,
                       doc="The pattern string from which the RE object was compiled.")
    flags = property(lambda self: self._flags, doc="The regex matching flags.")
    groups = property(lambda self: self._groups,
                      doc="The number of capturing groups in the pattern.")

    @property
    def groupindex(self):
        """A dictionary mapping group names to group numbers."""
        if self._groupindex is None:
            return {}
        return _MappingProxy(self._groupindex)

    def prefixmatch(self, string, pos=0, endpos=_MAXSIZE):
        """Matches zero or more characters at the beginning of the string."""
        state = _State(self, string, pos, endpos)
        state.ptr = state.start
        status = state.sre_match()
        return _new_match(self, state, status)

    match = prefixmatch

    def fullmatch(self, string, pos=0, endpos=_MAXSIZE):
        """Matches against all of the string."""
        state = _State(self, string, pos, endpos)
        state.ptr = state.start
        state.match_all = True
        status = state.sre_match()
        return _new_match(self, state, status)

    def search(self, string, pos=0, endpos=_MAXSIZE):
        """Scan through string looking for a match, and return a corresponding match object instance."""
        state = _State(self, string, pos, endpos)
        state.ptr = state.start
        status = state.sre_search()
        return _new_match(self, state, status)

    def findall(self, string, pos=0, endpos=_MAXSIZE):
        """Return a list of all non-overlapping matches of pattern in string."""
        state = _State(self, string, pos, endpos)
        result = []
        groups = self._groups
        while state.start <= state.end:
            state.reset()
            state.ptr = state.start
            if not state.sre_search():
                break
            if groups == 0:
                item = state.slice(state.start, state.ptr)
            elif groups == 1:
                item = state.getslice(1, True)
            else:
                item = tuple([state.getslice(i + 1, True) for i in range(groups)])
            result.append(item)
            state.must_advance = state.ptr == state.start
            state.start = state.ptr
        return result

    def finditer(self, string, pos=0, endpos=_MAXSIZE):
        """Return an iterator over all non-overlapping matches for the RE pattern in string."""
        scanner = self.scanner(string, pos, endpos)
        return iter(scanner.search, None)

    def scanner(self, string, pos=0, endpos=_MAXSIZE):
        scanner = object.__new__(SRE_Scanner)
        scanner._pattern = self
        scanner._state = _State(self, string, pos, endpos)
        scanner._executing = False
        return scanner

    def split(self, string, maxsplit=0):
        """Split string by the occurrences of pattern."""
        state = _State(self, string, 0, _MAXSIZE)
        result = []
        n = 0
        last = state.start
        groups = self._groups
        while not maxsplit or n < maxsplit:
            state.reset()
            state.ptr = state.start
            if not state.sre_search():
                break
            result.append(state.slice(last, state.start))
            for i in range(groups):
                result.append(state.getslice(i + 1, False))
            n += 1
            state.must_advance = state.ptr == state.start
            last = state.start = state.ptr
        result.append(state.slice(last, state.endpos))
        return result

    def _subx(self, repl, string, count, subn):
        count = _index(count)
        if callable(repl):
            filter_ = repl
            literal_filter = False
            is_template = False
        else:
            try:
                literal = 92 not in _getstring(repl)[0]
            except TypeError:
                literal = False
            if literal:
                filter_ = repl
                literal_filter = True
                is_template = False
            else:
                filter_ = _compile_template(self, repl)
                if not filter_.items:
                    filter_ = filter_.literal
                    literal_filter = True
                    is_template = False
                else:
                    literal_filter = False
                    is_template = True

        state = _State(self, string, 0, _MAXSIZE)
        out = []
        n = i = 0
        while not count or n < count:
            state.reset()
            state.ptr = state.start
            if not state.sre_search():
                break
            b = state.start
            e = state.ptr
            if i < b:
                out.append(state.slice(i, b))
            if literal_filter:
                item = filter_
            else:
                match = _new_match(self, state, True)
                if is_template:
                    item = _expand_template(filter_, match)
                else:
                    item = filter_(match)
            if item is not None:
                out.append(item)
            i = e
            n += 1
            state.must_advance = state.ptr == state.start
            state.start = state.ptr
        if i < state.endpos:
            out.append(state.slice(i, state.endpos))
        joiner = state.slice(0, 0)
        if not out:
            item = joiner
        else:
            item = joiner.join(out)
        if subn:
            return (item, n)
        return item

    def sub(self, repl, string, count=0):
        """Return the string obtained by replacing the leftmost non-overlapping occurrences of pattern in string by the replacement repl."""
        return self._subx(repl, string, count, False)

    def subn(self, repl, string, count=0):
        """Return the tuple (new_string, number_of_subs_made) found by replacing the leftmost non-overlapping occurrences of pattern with the replacement repl."""
        return self._subx(repl, string, count, True)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __class_getitem__(cls, item):
        return _GenericAlias(cls, item)

    def __repr__(self):
        flag_names = (
            ("re.IGNORECASE", SRE_FLAG_IGNORECASE),
            ("re.LOCALE", SRE_FLAG_LOCALE),
            ("re.MULTILINE", SRE_FLAG_MULTILINE),
            ("re.DOTALL", SRE_FLAG_DOTALL),
            ("re.UNICODE", SRE_FLAG_UNICODE),
            ("re.VERBOSE", SRE_FLAG_VERBOSE),
            ("re.DEBUG", SRE_FLAG_DEBUG),
            ("re.ASCII", SRE_FLAG_ASCII),
        )
        flags = self._flags
        if (self._isbytes == 0 and
                flags & (SRE_FLAG_LOCALE | SRE_FLAG_UNICODE | SRE_FLAG_ASCII) == SRE_FLAG_UNICODE):
            flags &= ~SRE_FLAG_UNICODE
        items = []
        for name, value in flag_names:
            if flags & value:
                items.append(name)
                flags &= ~value
        if flags:
            items.append("0x%x" % flags)
        pat = repr(self._pattern)[:200]
        if items:
            return "re.compile(%s, %s)" % (pat, "|".join(items))
        return "re.compile(%s)" % pat

    def __hash__(self):
        return hash((self._pattern, tuple(self._code), self._flags, self._isbytes))

    def __eq__(self, other):
        if type(other) is not Pattern:
            return NotImplemented
        if self is other:
            return True
        return (self._flags == other._flags and self._isbytes == other._isbytes
                and self._code == other._code and self._pattern == other._pattern)

    def __ne__(self, other):
        r = self.__eq__(other)
        return r if r is NotImplemented else not r


def _new_match(pattern, state, status):
    if not status:
        return None
    match = object.__new__(Match)
    groups = pattern._groups
    marks = [state.start, state.ptr]
    smark = state.mark
    lastmark = state.lastmark
    for g in range(groups):
        j = g * 2
        if j + 1 <= lastmark and smark[j] is not None and smark[j + 1] is not None:
            a = smark[j]
            b = smark[j + 1]
            if a > b:
                raise SystemError("The span of capturing group is wrong,"
                                  " please report a bug for the re module.")
            marks.append(a)
            marks.append(b)
        else:
            marks.append(-1)
            marks.append(-1)
    match._pattern = pattern
    match._string = state.string
    match._regs = None
    match._groups = groups + 1
    match._mark = marks
    match._pos = state.pos
    match._endpos = state.endpos
    match._lastindex = state.lastindex
    return match


class Match(metaclass=_Immutable):
    """The result of re.search(), re.prefixmatch(), and re.fullmatch().
Match objects always have a boolean value of True."""

    __slots__ = ("_pattern", "_string", "_regs", "_groups", "_mark", "_pos",
                 "_endpos", "_lastindex", "__weakref__")
    __module__ = "re"

    def __new__(cls, *args, **kwargs):
        raise TypeError("cannot create 're.Match' instances")

    @property
    def re(self):
        """The regular expression object."""
        return self._pattern

    @property
    def string(self):
        """The string passed to match() or search()."""
        return self._string

    @property
    def pos(self):
        """The index into the string at which the RE engine started looking for a match."""
        return self._pos

    @property
    def endpos(self):
        """The index into the string beyond which the RE engine will not go."""
        return self._endpos

    @property
    def lastindex(self):
        """The integer index of the last matched capturing group."""
        if self._lastindex >= 0:
            return self._lastindex
        return None

    @property
    def lastgroup(self):
        """The name of the last matched capturing group."""
        indexgroup = self._pattern._indexgroup
        if (indexgroup and 0 <= self._lastindex < len(indexgroup)):
            return indexgroup[self._lastindex]
        return None

    @property
    def regs(self):
        if self._regs is None:
            mark = self._mark
            self._regs = tuple([(mark[2 * i], mark[2 * i + 1])
                                for i in range(self._groups)])
        return self._regs

    def _getslice_by_index(self, index, default):
        index *= 2
        mark = self._mark
        string = self._string
        if string is None or mark[index] < 0:
            return default
        i = mark[index]
        j = mark[index + 1]
        if isinstance(string, str):
            length = len(string)
            i = min(i, length)
            j = min(j, length)
            if type(string) is str:
                return string[i:j]
            return str.__getitem__(string, slice(i, j))
        if type(string) is bytes:
            length = len(string)
            i = min(i, length)
            j = min(j, length)
            if i == 0 and j == length:
                return string
            return string[i:j]
        return memoryview(string)[i:j].tobytes()

    def _getindex(self, index):
        if isinstance(index, int) or hasattr(index, "__index__"):
            try:
                i = _index(index)
            except TypeError:
                i = -1
        else:
            i = -1
            groupindex = self._pattern._groupindex
            if groupindex:
                try:
                    v = groupindex[index]
                except (KeyError, TypeError):
                    v = None
                if isinstance(v, int):
                    i = v
        if i < 0 or i >= self._groups:
            raise IndexError("no such group")
        return i

    def expand(self, template):
        """Return the string obtained by doing backslash substitution on the string template, as done by the sub() method."""
        filter_ = _compile_template(self._pattern, template)
        return _expand_template(filter_, self)

    def group(self, *args):
        """group([group1, ...]) -> str or tuple.
    Return subgroup(s) of the match by indices or names.
    For 0 returns the entire match."""
        if not args:
            return self._getslice_by_index(0, None)
        if len(args) == 1:
            return self._getslice_by_index(self._getindex(args[0]), None)
        return tuple([self._getslice_by_index(self._getindex(a), None) for a in args])

    def __getitem__(self, name):
        return self._getslice_by_index(self._getindex(name), None)

    def groups(self, default=None):
        """Return a tuple containing all the subgroups of the match, from 1."""
        return tuple([self._getslice_by_index(i, default)
                      for i in range(1, self._groups)])

    def groupdict(self, default=None):
        """Return a dictionary containing all the named subgroups of the match, keyed by the subgroup name."""
        result = {}
        groupindex = self._pattern._groupindex
        if not groupindex:
            return result
        for key in list(groupindex):
            result[key] = self._getslice_by_index(self._getindex(key), default)
        return result

    def start(self, group=0):
        """Return index of the start of the substring matched by group."""
        return self._mark[self._getindex(group) * 2]

    def end(self, group=0):
        """Return index of the end of the substring matched by group."""
        return self._mark[self._getindex(group) * 2 + 1]

    def span(self, group=0):
        """For match object m, return the 2-tuple (m.start(group), m.end(group))."""
        i = self._getindex(group) * 2
        return (self._mark[i], self._mark[i + 1])

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __class_getitem__(cls, item):
        return _GenericAlias(cls, item)

    def __reduce__(self):
        raise TypeError("cannot pickle 're.Match' object")

    def __repr__(self):
        group0 = self._getslice_by_index(0, None)
        return "<re.Match object; span=(%d, %d), match=%s>" % (
            self._mark[0], self._mark[1], repr(group0)[:50])


class SRE_Scanner(metaclass=_Immutable):
    __slots__ = ("_pattern", "_state", "_executing")
    __module__ = "_sre"

    def __new__(cls, *args, **kwargs):
        raise TypeError("cannot create '_sre.SRE_Scanner' instances")

    @property
    def pattern(self):
        return self._pattern

    def _step(self, search):
        if self._executing:
            raise ValueError("regular expression scanner already executing")
        self._executing = True
        try:
            state = self._state
            if state.start is None:
                return None
            state.reset()
            state.ptr = state.start
            status = state.sre_search() if search else state.sre_match()
            match = _new_match(self._pattern, state, status)
            if not status:
                state.start = None
            else:
                state.must_advance = state.ptr == state.start
                state.start = state.ptr
            return match
        finally:
            self._executing = False

    def prefixmatch(self):
        return self._step(False)

    match = prefixmatch

    def search(self):
        return self._step(True)

    def __reduce__(self):
        raise TypeError("cannot pickle '_sre.SRE_Scanner' object")


Scanner = SRE_Scanner


def compile(pattern, flags, code, groups, groupindex, indexgroup):
    if not isinstance(code, list):
        raise TypeError("compile() argument 'code' must be list, not %s"
                        % type(code).__name__)
    if not isinstance(groupindex, dict):
        raise TypeError("compile() argument 'groupindex' must be dict, not %s"
                        % type(groupindex).__name__)
    if not isinstance(indexgroup, tuple):
        raise TypeError("compile() argument 'indexgroup' must be tuple, not %s"
                        % type(indexgroup).__name__)
    flags = _index(flags)
    groups = _index(groups)
    for value in code:
        value = _index(value)
        if value < 0:
            raise OverflowError("can't convert negative value to unsigned int")
        if value > 0xFFFFFFFF:
            raise OverflowError("regular expression code size limit exceeded")
    self = object.__new__(Pattern)
    if pattern is None:
        isbytes = -1
    else:
        isbytes = 1 if _getstring(pattern)[1] else 0
    self._pattern = pattern
    self._flags = flags
    self._groups = groups
    self._code = list(code)
    self._isbytes = isbytes
    self._groupindex = None
    self._indexgroup = None
    if len(groupindex) > 0:
        self._groupindex = groupindex
        if len(indexgroup) > 0:
            self._indexgroup = indexgroup
    if groups < 0 or groups > MAXGROUPS:
        raise RuntimeError("invalid SRE code")
    return self
