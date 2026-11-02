"""Pure-Python ``_json`` (replaces Modules/_json.c, 3.15).

Provides ``scanstring``, ``encode_basestring``, ``encode_basestring_ascii``,
``make_scanner`` (the ``Scanner`` type) and ``make_encoder`` (the ``Encoder``
type), following the C code: error messages and positions, ``StopIteration(idx)``
from the scanner, ``(string,)`` tuples from the encoder, exception notes
(``when serializing list item 0``), the ``_current_indent_level`` indent cache
semantics and the ``bool()`` conversion of flag arguments at construction.

Limitations: ``RecursionError`` comes from the interpreter's own recursion
limit rather than ``Py_EnterRecursiveCall`` (so the message does not mention
"while encoding a JSON object"); everything runs interpreted, so it is much
slower than the C module; dicts are iterated over a snapshot of their items
(the C code walks the live dict with ``PyDict_Next``).
"""

import builtins as _builtins

_frozendict = getattr(_builtins, 'frozendict', None)
_DICTS = (dict,) if _frozendict is None else (dict, _frozendict)

_WS = ' \t\n\r'
_DIGITS = '0123456789'
_HEX = '0123456789abcdefABCDEF'
_CONTROL = {i: None for i in range(0x20)}

_ESCAPES = {
    '\\': '\\\\', '"': '\\"', '\b': '\\b', '\f': '\\f',
    '\n': '\\n', '\r': '\\r', '\t': '\\t',
}
_UNESCAPES = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f',
              'n': '\n', 'r': '\r', 't': '\t'}
_ESCAPE_TABLE = dict(_ESCAPES)
for _i in range(0x20):
    _ESCAPE_TABLE.setdefault(chr(_i), '\\u%04x' % _i)
_ASCII_TABLE = dict(_ESCAPE_TABLE)
_ASCII_TABLE[chr(0x7f)] = '\\u007f'
_ESCAPE_TABLE = {ord(k): v for k, v in _ESCAPE_TABLE.items()}
_ASCII_TABLE = {ord(k): v for k, v in _ASCII_TABLE.items()}
del _i


def _ssize(v):
    # Py_ssize_t argument conversion ("n" format): an index, range-checked.
    m = getattr(type(v), '__index__', None)
    if m is None:
        raise TypeError(f"'{type(v).__name__}' object cannot be interpreted "
                        "as an integer")
    v = m(v)
    if not -(1 << 63) <= v < (1 << 63):
        raise OverflowError("Python int too large to convert to C ssize_t")
    return v


def _raise_errmsg(msg, s, end):
    # Raise JSONDecodeError (looked up lazily, like the C code does).
    import json.decoder
    raise json.decoder.JSONDecodeError(msg, s, end)


def _fqn(obj):
    tp = type(obj)
    mod = tp.__module__
    if mod in (None, 'builtins', '__main__'):
        return tp.__qualname__
    return f'{mod}.{tp.__qualname__}'


def _is_hex(s):
    for c in s:
        if c not in _HEX:
            return False
    return True


def _scanstring(s, end, strict):
    """Return (decoded string, index after the closing quote)."""
    begin = end - 1
    length = len(s)
    if end < 0 or length < end:
        raise ValueError("end is out of bounds")
    chunks = None
    while True:
        # Find the end of the string or the next escape.
        q = s.find('"', end)
        b = s.find('\\', end)
        if q < 0:
            q = length
        if b < 0:
            b = length
        nxt = q if q < b else b
        if strict:
            chunk = s[end:nxt]
            if len(chunk.translate(_CONTROL)) != len(chunk):
                for i in range(end, nxt):
                    if s[i] <= '\x1f':
                        _raise_errmsg("Invalid control character at", s, i)
        if nxt >= length:
            _raise_errmsg("Unterminated string starting at", s, begin)
        c = s[nxt]
        if c == '"' and chunks is None:
            return s[end:nxt], nxt + 1
        if chunks is None:
            chunks = []
        if nxt != end:
            chunks.append(s[end:nxt])
        nxt += 1
        if c == '"':
            end = nxt
            break
        if nxt == length:
            _raise_errmsg("Unterminated string starting at", s, begin)
        c = s[nxt]
        if c != 'u':
            end = nxt + 1
            ch = _UNESCAPES.get(c)
            if ch is None:
                _raise_errmsg("Invalid \\escape", s, end - 2)
        else:
            nxt += 1
            end = nxt + 4
            if end > length:
                _raise_errmsg("Invalid \\uXXXX escape", s, nxt - 1)
            digits = s[nxt:end]
            if not _is_hex(digits):
                _raise_errmsg("Invalid \\uXXXX escape", s, end - 5)
            cp = int(digits, 16)
            nxt = end
            # Surrogate pair (same bounds test as the C code).
            if (0xd800 <= cp <= 0xdbff and end + 6 < length
                    and s[nxt] == '\\' and s[nxt + 1] == 'u'):
                nxt += 2
                end += 6
                digits = s[nxt:end]
                if not _is_hex(digits):
                    _raise_errmsg("Invalid \\uXXXX escape", s, end - 5)
                cp2 = int(digits, 16)
                if 0xdc00 <= cp2 <= 0xdfff:
                    cp = 0x10000 + (((cp - 0xd800) << 10) | (cp2 - 0xdc00))
                else:
                    end -= 6
            ch = chr(cp)
        chunks.append(ch)
    return ''.join(chunks), end


def scanstring(pystr, end, strict=True, /):
    """Scan the string s for a JSON string.

    End is the index of the character in s after the quote that started the
    JSON string. Unescapes all valid JSON string escape sequences and raises
    ValueError on attempt to decode an invalid string. If strict is False
    then literal control characters are allowed in the string.

    Returns a tuple of the decoded string and the index of the character in
    s after the end quote.
    """
    if not isinstance(pystr, str):
        raise TypeError(f"scanstring() argument 1 must be str, not {type(pystr).__name__}")
    return _scanstring(pystr, _ssize(end), bool(strict))


def encode_basestring_ascii(pystr, /):
    """Return an ASCII-only JSON representation of a Python string"""
    if not isinstance(pystr, str):
        raise TypeError("encode_basestring_ascii() argument must be str, "
                        f"not {type(pystr).__name__}")
    if pystr.isascii():
        return '"' + pystr.translate(_ASCII_TABLE) + '"'
    out = ['"']
    for c in pystr:
        n = ord(c)
        if c in _ASCII_TABLE_STR:
            out.append(_ASCII_TABLE[n])
        elif ' ' <= c <= '~':
            out.append(c)
        elif n < 0x10000:
            out.append('\\u%04x' % n)
        else:
            n -= 0x10000
            out.append('\\u%04x\\u%04x' % (0xd800 | (n >> 10), 0xdc00 | (n & 0x3ff)))
    out.append('"')
    return ''.join(out)


_ASCII_TABLE_STR = {chr(k) for k in _ASCII_TABLE}


def encode_basestring(pystr, /):
    """Return a JSON representation of a Python string"""
    if not isinstance(pystr, str):
        raise TypeError("encode_basestring() argument must be str, "
                        f"not {type(pystr).__name__}")
    return '"' + pystr.translate(_ESCAPE_TABLE) + '"'


class Scanner:
    """JSON scanner object"""

    __slots__ = ('strict', 'object_hook', 'object_pairs_hook', 'array_hook',
                 'parse_float', 'parse_int', 'parse_constant')

    def __init__(self, context):
        # All of these fail "gracefully" (AttributeError) like the C code.
        self.strict = bool(context.strict)
        self.object_hook = context.object_hook
        self.object_pairs_hook = context.object_pairs_hook
        self.array_hook = context.array_hook
        self.parse_float = context.parse_float
        self.parse_int = context.parse_int
        self.parse_constant = context.parse_constant

    def __call__(self, string, idx):
        if not isinstance(string, str):
            raise TypeError("first argument must be a string, "
                            f"not {type(string).__name__}")
        return self._scan_once(string, {}, _ssize(idx))

    def _scan_once(self, s, memo, idx):
        length = len(s)
        if idx < 0:
            raise ValueError("idx cannot be negative")
        if idx >= length:
            raise StopIteration(idx)
        c = s[idx]
        if c == '"':
            return _scanstring(s, idx + 1, self.strict)
        if c == '{':
            return self._parse_object(s, memo, idx + 1)
        if c == '[':
            return self._parse_array(s, memo, idx + 1)
        if c == 'n':
            if s.startswith('null', idx):
                return None, idx + 4
        elif c == 't':
            if s.startswith('true', idx):
                return True, idx + 4
        elif c == 'f':
            if s.startswith('false', idx):
                return False, idx + 5
        elif c == 'N':
            if s.startswith('NaN', idx):
                return self.parse_constant('NaN'), idx + 3
        elif c == 'I':
            if s.startswith('Infinity', idx):
                return self.parse_constant('Infinity'), idx + 8
        elif c == '-':
            if s.startswith('-Infinity', idx):
                return self.parse_constant('-Infinity'), idx + 9
        return self._match_number(s, idx)

    def _parse_object(self, s, memo, idx):
        pairs_hook = self.object_pairs_hook
        has_pairs_hook = pairs_hook is not None
        rval = [] if has_pairs_hook else {}
        end_idx = len(s) - 1
        while idx <= end_idx and s[idx] in _WS:
            idx += 1
        if idx > end_idx or s[idx] != '}':
            while True:
                if idx > end_idx or s[idx] != '"':
                    _raise_errmsg("Expecting property name enclosed in double quotes", s, idx)
                key, idx = _scanstring(s, idx + 1, self.strict)
                key = memo.setdefault(key, key)
                while idx <= end_idx and s[idx] in _WS:
                    idx += 1
                if idx > end_idx or s[idx] != ':':
                    _raise_errmsg("Expecting ':' delimiter", s, idx)
                idx += 1
                while idx <= end_idx and s[idx] in _WS:
                    idx += 1
                val, idx = self._scan_once(s, memo, idx)
                if has_pairs_hook:
                    rval.append((key, val))
                else:
                    rval[key] = val
                while idx <= end_idx and s[idx] in _WS:
                    idx += 1
                if idx <= end_idx and s[idx] == '}':
                    break
                if idx > end_idx or s[idx] != ',':
                    _raise_errmsg("Expecting ',' delimiter", s, idx)
                comma_idx = idx
                idx += 1
                while idx <= end_idx and s[idx] in _WS:
                    idx += 1
                if idx <= end_idx and s[idx] == '}':
                    _raise_errmsg("Illegal trailing comma before end of object", s, comma_idx)
        idx += 1
        if has_pairs_hook:
            return pairs_hook(rval), idx
        if self.object_hook is not None:
            return self.object_hook(rval), idx
        return rval, idx

    def _parse_array(self, s, memo, idx):
        rval = []
        end_idx = len(s) - 1
        while idx <= end_idx and s[idx] in _WS:
            idx += 1
        if idx > end_idx or s[idx] != ']':
            while True:
                val, idx = self._scan_once(s, memo, idx)
                rval.append(val)
                while idx <= end_idx and s[idx] in _WS:
                    idx += 1
                if idx <= end_idx and s[idx] == ']':
                    break
                if idx > end_idx or s[idx] != ',':
                    _raise_errmsg("Expecting ',' delimiter", s, idx)
                comma_idx = idx
                idx += 1
                while idx <= end_idx and s[idx] in _WS:
                    idx += 1
                if idx <= end_idx and s[idx] == ']':
                    _raise_errmsg("Illegal trailing comma before end of array", s, comma_idx)
        if idx > end_idx or s[idx] != ']':
            _raise_errmsg("Expecting value", s, end_idx)
        idx += 1
        if self.array_hook is not None:
            return self.array_hook(rval), idx
        return rval, idx

    def _match_number(self, s, start):
        end_idx = len(s) - 1
        idx = start
        is_float = False
        if s[idx] == '-':
            idx += 1
            if idx > end_idx:
                raise StopIteration(start)
        c = s[idx]
        if '1' <= c <= '9':
            idx += 1
            while idx <= end_idx and s[idx] in _DIGITS:
                idx += 1
        elif c == '0':
            idx += 1
        else:
            raise StopIteration(start)
        if idx < end_idx and s[idx] == '.' and s[idx + 1] in _DIGITS:
            is_float = True
            idx += 2
            while idx <= end_idx and s[idx] in _DIGITS:
                idx += 1
        if idx < end_idx and s[idx] in 'eE':
            e_start = idx
            idx += 1
            if idx < end_idx and s[idx] in '-+':
                idx += 1
            while idx <= end_idx and s[idx] in _DIGITS:
                idx += 1
            if s[idx - 1] in _DIGITS:
                is_float = True
            else:
                idx = e_start
        numstr = s[start:idx]
        if is_float:
            return self.parse_float(numstr), idx
        return self.parse_int(numstr), idx


make_scanner = Scanner


class Encoder:
    """Encoder(markers, default, encoder, indent, key_separator,
    item_separator, sort_keys, skipkeys, allow_nan)"""

    __slots__ = ('markers', 'default', 'encoder', 'indent', 'key_separator',
                 'item_separator', 'sort_keys', 'skipkeys', 'allow_nan')

    def __init__(self, markers, default, encoder, indent, key_separator,
                 item_separator, sort_keys, skipkeys, allow_nan):
        if markers is not None and not isinstance(markers, dict):
            raise TypeError("make_encoder() argument 1 must be dict or None, "
                            f"not {type(markers).__name__}")
        if not isinstance(key_separator, str):
            raise TypeError("make_encoder() argument 5 must be str, "
                            f"not {type(key_separator).__name__}")
        if not isinstance(item_separator, str):
            raise TypeError("make_encoder() argument 6 must be str, "
                            f"not {type(item_separator).__name__}")
        self.markers = markers
        self.default = default
        self.encoder = encoder
        self.indent = indent
        self.key_separator = key_separator
        self.item_separator = item_separator
        self.sort_keys = bool(sort_keys)
        self.skipkeys = bool(skipkeys)
        self.allow_nan = bool(allow_nan)

    def __call__(self, obj, _current_indent_level):
        level = _ssize(_current_indent_level)
        w = []
        cache = None
        if self.indent is not None:
            # cache[2*k] = '\n' + indent * (k + initial level); cache[2*k-1] =
            # item_separator + that (see create_indent_cache in _json.c).
            cache = ['\n' + self.indent * level]
        self._obj(w, obj, 0, cache)
        return (''.join(w),)

    def _update_cache(self, level, cache):
        newline_indent = cache[(level - 1) * 2] + self.indent
        cache.append(self.item_separator + newline_indent)
        cache.append(newline_indent)

    def _separator(self, level, cache):
        if level * 2 > len(cache):
            self._update_cache(level, cache)
        return cache[level * 2 - 1]

    def _float(self, obj):
        if obj != obj or obj in (float('inf'), float('-inf')):
            if not self.allow_nan:
                raise ValueError(
                    f"Out of range float values are not JSON compliant: {obj!r}")
            if obj > 0:
                return 'Infinity'
            if obj < 0:
                return '-Infinity'
            return 'NaN'
        return float.__repr__(obj)

    def _string(self, w, obj):
        encoded = self.encoder(obj)
        if not isinstance(encoded, str):
            raise TypeError("encoder() must return a string, "
                            f"not {type(encoded).__name__}")
        w.append(encoded)

    def _obj(self, w, obj, level, cache):
        if obj is None:
            w.append('null')
        elif obj is True:
            w.append('true')
        elif obj is False:
            w.append('false')
        elif isinstance(obj, str):
            self._string(w, obj)
        elif isinstance(obj, int):
            w.append(int.__repr__(obj))
        elif isinstance(obj, float):
            w.append(self._float(obj))
        elif isinstance(obj, (list, tuple)):
            self._list(w, obj, level, cache)
        elif isinstance(obj, _DICTS):
            self._dict(w, obj, level, cache)
        else:
            markers = self.markers
            ident = None
            if markers is not None:
                ident = id(obj)
                if ident in markers:
                    raise ValueError("Circular reference detected")
                markers[ident] = obj
            newobj = self.default(obj)
            try:
                self._obj(w, newobj, level, cache)
            except BaseException as exc:
                exc.add_note(f'when serializing {_fqn(obj)} object')
                raise
            if ident is not None:
                del markers[ident]

    def _key_value(self, w, first, dct, key, value, level, cache, separator):
        if isinstance(key, str):
            keystr = key
        elif isinstance(key, float):
            keystr = self._float(key)
        elif key is True:
            keystr = 'true'
        elif key is False:
            keystr = 'false'
        elif key is None:
            keystr = 'null'
        elif isinstance(key, int):
            keystr = int.__repr__(key)
        elif self.skipkeys:
            return first
        else:
            raise TypeError("keys must be str, int, float, bool or None, "
                            f"not {type(key).__name__}")
        if first:
            first = False
            if self.indent is not None:
                w.append(cache[level * 2])
        else:
            w.append(separator)
        self._string(w, keystr)
        w.append(self.key_separator)
        try:
            self._obj(w, value, level, cache)
        except BaseException as exc:
            exc.add_note(f'when serializing {_fqn(dct)} item {key!r}')
            raise
        return first

    def _dict(self, w, dct, level, cache):
        if len(dct) == 0:
            w.append('{}')
            return
        markers = self.markers
        ident = None
        if markers is not None:
            ident = id(dct)
            if ident in markers:
                raise ValueError("Circular reference detected")
            markers[ident] = dct
        w.append('{')
        separator = self.item_separator
        if self.indent is not None:
            level += 1
            separator = self._separator(level, cache)
        first = True
        if self.sort_keys or type(dct) not in _DICTS:
            items = dct.items()
            if type(items) is not list:
                items = list(items)
            if self.sort_keys:
                items.sort()
            i = 0
            while i < len(items):
                item = items[i]
                i += 1
                if type(item) is not tuple or len(item) != 2:
                    raise ValueError("items must return 2-tuples")
                first = self._key_value(w, first, dct, item[0], item[1],
                                        level, cache, separator)
        else:
            for key, value in list(type(dct).items(dct)):
                first = self._key_value(w, first, dct, key, value,
                                        level, cache, separator)
        if ident is not None:
            del markers[ident]
        if self.indent is not None and not first:
            level -= 1
            w.append(cache[level * 2])
        w.append('}')

    def _list(self, w, seq, level, cache):
        # PySequence_Fast: only exact lists/tuples are indexed in place;
        # subclasses (which may override __iter__/__len__) are snapshotted
        # through iteration.
        orig = seq
        if type(seq) is not list and type(seq) is not tuple:
            seq = list(seq)
        if len(seq) == 0:
            w.append('[]')
            return
        markers = self.markers
        ident = None
        if markers is not None:
            ident = id(orig)
            if ident in markers:
                raise ValueError("Circular reference detected")
            markers[ident] = orig
        w.append('[')
        separator = self.item_separator
        if self.indent is not None:
            level += 1
            separator = self._separator(level, cache)
            w.append(cache[level * 2])
        i = 0
        while i < len(seq):
            obj = seq[i]
            if i:
                w.append(separator)
            try:
                self._obj(w, obj, level, cache)
            except BaseException as exc:
                exc.add_note(f'when serializing {_fqn(orig)} item {i}')
                raise
            i += 1
        if ident is not None:
            del markers[ident]
        if self.indent is not None:
            level -= 1
            w.append(cache[level * 2])
        w.append(']')


make_encoder = Encoder
