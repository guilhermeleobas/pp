"""CSV parsing and writing.

Pure-Python ``_csv`` for pp (replaces Modules/_csv.c, 3.15): ``Dialect``,
``reader``/``Reader``, ``writer``/``Writer``, the dialect registry
(``register_dialect``, ``unregister_dialect``, ``get_dialect``,
``list_dialects``), ``field_size_limit``, ``Error`` and the ``QUOTE_*``
constants. The reader is the same character state machine as the C parser and
the writer the same ``join_append`` logic, so quoting, escaping, error
messages and ``QUOTE_STRINGS``/``QUOTE_NOTNULL`` handling follow the C module.

Limitations: it is interpreted, so parsing and writing are much slower than C
(the writer takes a fast path for fields without special characters, the
reader has none); ``Reader``/``Writer`` instances cannot be created directly
(as in C) but, unlike the C heap types, the classes are ordinary Python
classes (``Dialect`` attributes are read-only properties, not members).
"""

__all__ = ['Dialect', 'Error', 'Reader', 'Writer', 'QUOTE_MINIMAL',
           'QUOTE_ALL', 'QUOTE_NONNUMERIC', 'QUOTE_NONE', 'QUOTE_STRINGS',
           'QUOTE_NOTNULL', 'reader', 'writer', 'register_dialect',
           'unregister_dialect', 'get_dialect', 'list_dialects',
           'field_size_limit']

QUOTE_MINIMAL = 0
QUOTE_ALL = 1
QUOTE_NONNUMERIC = 2
QUOTE_NONE = 3
QUOTE_STRINGS = 4
QUOTE_NOTNULL = 5

_QUOTE_STYLES = (QUOTE_MINIMAL, QUOTE_ALL, QUOTE_NONNUMERIC, QUOTE_NONE,
                 QUOTE_STRINGS, QUOTE_NOTNULL)

(START_RECORD, START_FIELD, ESCAPED_CHAR, IN_FIELD, IN_QUOTED_FIELD,
 ESCAPE_IN_QUOTED_FIELD, QUOTE_IN_QUOTED_FIELD, EAT_CRNL,
 AFTER_ESCAPED_CRNL) = range(9)

_EOL = -2
_UNSET = object()

_dialects = {}
_field_limit = 128 * 1024


class Error(Exception):
    pass


Error.__module__ = '_csv'


def _tname(obj):
    # "%T": fully qualified type name, without "builtins".
    tp = type(obj)
    mod = tp.__module__
    if mod in (None, 'builtins', '__main__'):
        return tp.__qualname__
    return f'{mod}.{tp.__qualname__}'


def _ssize(v):
    if not -(1 << 63) <= v < (1 << 63):
        raise OverflowError("Python int too large to convert to C ssize_t")
    return v


def _get_dialect_from_registry(name):
    try:
        return _dialects[name]
    except KeyError:
        raise Error("unknown dialect") from None


def _set_bool(name, src, dflt):
    if src is _UNSET:
        return dflt
    return bool(src)


def _set_int(name, src, dflt):
    if src is _UNSET:
        return dflt
    if type(src) is not int:
        raise TypeError(f'"{name}" must be an integer, not {_tname(src)}')
    if not -(1 << 31) <= src < (1 << 31):
        raise OverflowError("Python int too large to convert to C int")
    return src


def _set_char_or_none(name, src, dflt):
    if src is _UNSET:
        return dflt
    if src is None:
        return None
    if not isinstance(src, str):
        raise TypeError(f'"{name}" must be a unicode character or None, '
                        f'not {_tname(src)}')
    if len(src) != 1:
        raise TypeError(f'"{name}" must be a unicode character or None, '
                        f'not a string of length {len(src)}')
    return src


def _set_char(name, src, dflt):
    if src is _UNSET:
        return dflt
    if not isinstance(src, str):
        raise TypeError(f'"{name}" must be a unicode character, '
                        f'not {_tname(src)}')
    if len(src) != 1:
        raise TypeError(f'"{name}" must be a unicode character, '
                        f'not a string of length {len(src)}')
    return src


def _set_str(name, src, dflt):
    if src is _UNSET:
        return dflt
    if not isinstance(src, str):
        raise TypeError(f'"{name}" must be a string, not {_tname(src)}')
    return src


def _check_char(name, c, lineterminator, allowspace):
    if c == '\r' or c == '\n' or (c == ' ' and not allowspace):
        raise ValueError(f"bad {name} value")
    if c is not None and c in lineterminator:
        raise ValueError(f"bad {name} or lineterminator value")


def _check_chars(name1, name2, c1, c2):
    if c1 == c2 and c1 is not None:
        raise ValueError(f"bad {name1} or {name2} value")


class Dialect:
    """CSV dialect

    The Dialect type records CSV parsing and generation options.
    """

    __slots__ = ('_doublequote', '_skipinitialspace', '_strict', '_quoting',
                 '_delimiter', '_quotechar', '_escapechar', '_lineterminator')

    def __new__(cls, dialect=_UNSET, delimiter=_UNSET, doublequote=_UNSET,
                escapechar=_UNSET, lineterminator=_UNSET, quotechar=_UNSET,
                quoting=_UNSET, skipinitialspace=_UNSET, strict=_UNSET):
        if dialect is not _UNSET:
            if isinstance(dialect, str):
                dialect = _get_dialect_from_registry(dialect)
            # Can we reuse this instance?
            if (isinstance(dialect, Dialect) and delimiter is _UNSET
                    and doublequote is _UNSET and escapechar is _UNSET
                    and lineterminator is _UNSET and quotechar is _UNSET
                    and quoting is _UNSET and skipinitialspace is _UNSET
                    and strict is _UNSET):
                return dialect
        self = object.__new__(cls)

        if dialect is not _UNSET:
            def fetch(v, n):
                if v is _UNSET:
                    try:
                        return getattr(dialect, n)
                    except AttributeError:
                        return _UNSET
                return v
            delimiter = fetch(delimiter, "delimiter")
            doublequote = fetch(doublequote, "doublequote")
            escapechar = fetch(escapechar, "escapechar")
            lineterminator = fetch(lineterminator, "lineterminator")
            quotechar = fetch(quotechar, "quotechar")
            quoting = fetch(quoting, "quoting")
            skipinitialspace = fetch(skipinitialspace, "skipinitialspace")
            strict = fetch(strict, "strict")

        # check types and convert to C values
        self._delimiter = _set_char("delimiter", delimiter, ',')
        self._doublequote = _set_bool("doublequote", doublequote, True)
        self._escapechar = _set_char_or_none("escapechar", escapechar, None)
        self._lineterminator = _set_str("lineterminator", lineterminator, "\r\n")
        self._quotechar = _set_char_or_none("quotechar", quotechar, '"')
        self._quoting = _set_int("quoting", quoting, QUOTE_MINIMAL)
        self._skipinitialspace = _set_bool("skipinitialspace",
                                           skipinitialspace, False)
        self._strict = _set_bool("strict", strict, False)

        # validate options
        if self._quoting not in _QUOTE_STYLES:
            raise TypeError('bad "quoting" value')
        if quotechar is None and quoting is _UNSET:
            self._quoting = QUOTE_NONE
        if self._quoting != QUOTE_NONE and self._quotechar is None:
            raise TypeError("quotechar must be set if quoting enabled")
        lt = self._lineterminator
        _check_char("delimiter", self._delimiter, lt, True)
        _check_char("escapechar", self._escapechar, lt, not self._skipinitialspace)
        _check_char("quotechar", self._quotechar, lt, not self._skipinitialspace)
        _check_chars("delimiter", "escapechar", self._delimiter, self._escapechar)
        _check_chars("delimiter", "quotechar", self._delimiter, self._quotechar)
        _check_chars("escapechar", "quotechar", self._escapechar, self._quotechar)
        return self

    @property
    def skipinitialspace(self):
        return self._skipinitialspace

    @property
    def doublequote(self):
        return self._doublequote

    @property
    def strict(self):
        return self._strict

    @property
    def delimiter(self):
        return self._delimiter

    @property
    def escapechar(self):
        return self._escapechar

    @property
    def lineterminator(self):
        return self._lineterminator

    @property
    def quotechar(self):
        return self._quotechar

    @property
    def quoting(self):
        return self._quoting

    def __reduce__(self, *args):
        """raises an exception to avoid pickling"""
        raise TypeError(f"cannot pickle '{type(self).__name__}' instances")

    __reduce_ex__ = __reduce__


Dialect.__module__ = '_csv'


def _call_dialect(dialect_inst, kwargs):
    if dialect_inst is not _UNSET:
        return Dialect(dialect_inst, **kwargs)
    return Dialect(**kwargs)


def _unpack(name, args, lo, hi):
    n = len(args)
    if n < lo:
        raise TypeError(f"{name} expected at least {lo} argument"
                        f"{'s' if lo != 1 else ''}, got {n}")
    if n > hi:
        raise TypeError(f"{name} expected at most {hi} argument"
                        f"{'s' if hi != 1 else ''}, got {n}")
    return args + (_UNSET,) * (hi - n)


def _no_new(cls, *args, **kwargs):
    raise TypeError(f"cannot create '{cls.__module__}.{cls.__qualname__}' instances")


class Reader:
    """CSV reader

    Reader objects are responsible for reading and parsing tabular data
    in CSV format.
    """

    __slots__ = ('_input_iter', '_dialect', '_fields', '_state', '_field',
                 '_unquoted_field', '_line_num')

    __new__ = _no_new

    @property
    def dialect(self):
        return self._dialect

    @property
    def line_num(self):
        return self._line_num

    def __iter__(self):
        return self

    def _save_field(self):
        quoting = self._dialect._quoting
        field = self._field
        if (self._unquoted_field and not field
                and quoting in (QUOTE_NOTNULL, QUOTE_STRINGS)):
            value = None
        else:
            value = ''.join(field)
            if (self._unquoted_field and field
                    and quoting in (QUOTE_NONNUMERIC, QUOTE_STRINGS)):
                value = float(value)
            self._field = []
        self._fields.append(value)

    def _add_char(self, c):
        if len(self._field) >= _field_limit:
            raise Error(f"field larger than field limit ({_field_limit})")
        self._field.append(c)

    def _process_char(self, c):
        dialect = self._dialect
        state = self._state

        if state == START_RECORD:
            # start of record
            if c == _EOL:
                # empty line - return []
                return
            elif c == '\n' or c == '\r':
                self._state = EAT_CRNL
                return
            # normal character - handle as START_FIELD
            state = self._state = START_FIELD
        if state == START_FIELD:
            # expecting field
            self._unquoted_field = True
            if c == '\n' or c == '\r' or c == _EOL:
                # save empty field - return [fields]
                self._save_field()
                self._state = START_RECORD if c == _EOL else EAT_CRNL
            elif c == dialect._quotechar and dialect._quoting != QUOTE_NONE:
                # start quoted field
                self._unquoted_field = False
                self._state = IN_QUOTED_FIELD
            elif c == dialect._escapechar:
                # possible escaped character
                self._state = ESCAPED_CHAR
            elif c == ' ' and dialect._skipinitialspace:
                # ignore spaces at start of field
                pass
            elif c == dialect._delimiter:
                # save empty field
                self._save_field()
            else:
                # begin new unquoted field
                self._add_char(c)
                self._state = IN_FIELD

        elif state == ESCAPED_CHAR:
            if c == '\n' or c == '\r':
                self._add_char(c)
                self._state = AFTER_ESCAPED_CRNL
                return
            if c == _EOL:
                c = '\n'
            self._add_char(c)
            self._state = IN_FIELD

        elif state == AFTER_ESCAPED_CRNL:
            if c == _EOL:
                return
            self._state = state = IN_FIELD
            self._process_in_field(c, dialect)

        elif state == IN_FIELD:
            self._process_in_field(c, dialect)

        elif state == IN_QUOTED_FIELD:
            # in quoted field
            if c == _EOL:
                pass
            elif c == dialect._escapechar:
                # Possible escape character
                self._state = ESCAPE_IN_QUOTED_FIELD
            elif c == dialect._quotechar and dialect._quoting != QUOTE_NONE:
                if dialect._doublequote:
                    # doublequote; " represented by ""
                    self._state = QUOTE_IN_QUOTED_FIELD
                else:
                    # end of quote part of field
                    self._state = IN_FIELD
            else:
                # normal character - save in field
                self._add_char(c)

        elif state == ESCAPE_IN_QUOTED_FIELD:
            if c == _EOL:
                c = '\n'
            self._add_char(c)
            self._state = IN_QUOTED_FIELD

        elif state == QUOTE_IN_QUOTED_FIELD:
            # doublequote - seen a quote in a quoted field
            if dialect._quoting != QUOTE_NONE and c == dialect._quotechar:
                # save "" as "
                self._add_char(c)
                self._state = IN_QUOTED_FIELD
            elif c == dialect._delimiter:
                # save field - wait for new field
                self._save_field()
                self._state = START_FIELD
            elif c == '\n' or c == '\r' or c == _EOL:
                # end of line - return [fields]
                self._save_field()
                self._state = START_RECORD if c == _EOL else EAT_CRNL
            elif not dialect._strict:
                self._add_char(c)
                self._state = IN_FIELD
            else:
                # illegal
                raise Error(f"'{dialect._delimiter}' expected after "
                            f"'{dialect._quotechar}'")

        elif state == EAT_CRNL:
            if c == '\n' or c == '\r':
                pass
            elif c == _EOL:
                self._state = START_RECORD
            else:
                raise Error("new-line character seen in unquoted field - "
                            "do you need to open the file with newline=''?")

    def _process_in_field(self, c, dialect):
        # in unquoted field
        if c == '\n' or c == '\r' or c == _EOL:
            # end of line - return [fields]
            self._save_field()
            self._state = START_RECORD if c == _EOL else EAT_CRNL
        elif c == dialect._escapechar:
            # possible escaped character
            self._state = ESCAPED_CHAR
        elif c == dialect._delimiter:
            # save field - wait for new field
            self._save_field()
            self._state = START_FIELD
        else:
            # normal character - save in field
            self._add_char(c)

    def _reset(self):
        self._fields = []
        self._field = []
        self._state = START_RECORD
        self._unquoted_field = False

    def __next__(self):
        self._reset()
        while True:
            try:
                lineobj = next(self._input_iter)
            except StopIteration:
                # End of input
                if self._field or self._state == IN_QUOTED_FIELD:
                    if self._dialect._strict:
                        raise Error("unexpected end of data") from None
                    self._save_field()
                    break
                raise
            if not isinstance(lineobj, str):
                raise Error("iterator should return strings, "
                            f"not {type(lineobj).__name__} "
                            "(the file should be opened in text mode)")
            if self._fields is None:
                raise Error("iterator has already advanced the reader")
            self._line_num += 1
            process = self._process_char
            for c in lineobj:
                process(c)
            process(_EOL)
            if self._state == START_RECORD:
                break
        fields = self._fields
        self._fields = None
        return fields


Reader.__module__ = '_csv'
Reader.__name__ = Reader.__qualname__ = 'reader'  # the C type is _csv.reader


def reader(*args, **kwargs):
    """reader(iterable, /, dialect='excel', **fmtparams)

    Return a reader object that will process lines from the given iterable.

    The "iterable" argument can be any object that returns a line
    of input for each iteration, such as a file object or a list.  The
    optional "dialect" argument defines a CSV dialect.  The function
    also accepts optional keyword arguments which override settings
    provided by the dialect.

    The returned object is an iterator.  Each iteration returns a row
    of the CSV file (which can span multiple input lines).
    """
    self = object.__new__(Reader)
    self._dialect = None
    self._input_iter = None
    self._line_num = 0
    self._reset()
    iterator, dialect = _unpack("reader", args, 1, 2)
    self._input_iter = iter(iterator)
    self._dialect = _call_dialect(dialect, kwargs)
    return self


class Writer:
    """CSV writer

    Writer objects are responsible for generating tabular data
    in CSV format from sequence input.
    """

    __slots__ = ('_write', '_dialect', '_rec', '_num_fields', '_specials')

    __new__ = _no_new

    @property
    def dialect(self):
        return self._dialect

    def _join_append(self, field, quoted):
        # field is a str, or None for a null field
        dialect = self._dialect
        quoting = dialect._quoting
        if not field and dialect._delimiter == ' ' and dialect._skipinitialspace:
            if (quoting == QUOTE_NONE
                    or (field is None
                        and quoting in (QUOTE_STRINGS, QUOTE_NOTNULL))):
                raise Error("empty field must be quoted if delimiter is a "
                            "space and skipinitialspace is true")
            quoted = True
        out = []
        if self._num_fields > 0:
            out.append(dialect._delimiter)
        if field:
            specials = self._specials
            if specials.isdisjoint(field):
                body = field
            else:
                body = []
                delimiter = dialect._delimiter
                escapechar = dialect._escapechar
                quotechar = dialect._quotechar
                for c in field:
                    want_escape = False
                    if c in specials:
                        if quoting == QUOTE_NONE:
                            want_escape = True
                        else:
                            if c == quotechar:
                                if dialect._doublequote:
                                    body.append(quotechar)
                                else:
                                    want_escape = True
                            elif c == escapechar:
                                want_escape = True
                            if not want_escape:
                                quoted = True
                        if want_escape:
                            if escapechar is None:
                                raise Error("need to escape, but no escapechar set")
                            body.append(escapechar)
                    body.append(c)
                body = ''.join(body)
        else:
            body = ''
        if quoted:
            out.append(dialect._quotechar)
            out.append(body)
            out.append(dialect._quotechar)
        else:
            out.append(body)
        self._rec.extend(out)
        self._num_fields += 1

    def writerow(self, row, /):
        """Construct and write a CSV record from an iterable of fields.

        Non-string elements will be converted to string.
        """
        dialect = self._dialect
        try:
            it = iter(row)
        except TypeError:
            raise Error(f"iterable expected, not {type(row).__name__}") from None
        quoting = dialect._quoting
        self._rec = []
        self._num_fields = 0
        null_field = False
        for field in it:
            if quoting == QUOTE_NONNUMERIC:
                quoted = not _is_number(field)
            elif quoting == QUOTE_ALL:
                quoted = True
            elif quoting == QUOTE_STRINGS:
                quoted = isinstance(field, str)
            elif quoting == QUOTE_NOTNULL:
                quoted = field is not None
            else:
                quoted = False
            null_field = field is None
            if isinstance(field, str):
                self._join_append(field, quoted)
            elif null_field:
                self._join_append(None, quoted)
            else:
                self._join_append(str(field), quoted)

        if self._num_fields > 0 and not ''.join(self._rec):
            if (quoting == QUOTE_NONE
                    or (null_field and quoting in (QUOTE_STRINGS, QUOTE_NOTNULL))):
                raise Error("single empty field record must be quoted")
            self._num_fields -= 1
            self._join_append(None, True)

        self._rec.append(dialect._lineterminator)
        return self._write(''.join(self._rec))

    def writerows(self, rows, /):
        """Construct and write a series of iterables to a csv file.

        Non-string elements will be converted to string.
        """
        for row in iter(rows):
            Writer.writerow(self, row)


Writer.__module__ = '_csv'
Writer.__name__ = Writer.__qualname__ = 'writer'  # the C type is _csv.writer


def _is_number(obj):
    # PyNumber_Check
    tp = type(obj)
    return (isinstance(obj, complex) or hasattr(tp, '__index__')
            or hasattr(tp, '__int__') or hasattr(tp, '__float__'))


def writer(*args, **kwargs):
    """writer(fileobj, /, dialect='excel', **fmtparams)

    Return a writer object that will write user data on the given file object.

    The "fileobj" argument can be any object that supports the file API.
    The optional "dialect" argument defines a CSV dialect.  The function
    also accepts optional keyword arguments which override settings
    provided by the dialect.
    """
    self = object.__new__(Writer)
    self._dialect = None
    self._rec = []
    self._num_fields = 0
    output_file, dialect = _unpack("writer", args, 1, 2)
    try:
        write = output_file.write
    except AttributeError:
        write = None
    if write is None or not callable(write):
        raise TypeError('argument 1 must have a "write" method')
    self._write = write
    self._dialect = d = _call_dialect(dialect, kwargs)
    specials = {d._delimiter, '\n', '\r'}
    specials.update(d._lineterminator)
    if d._escapechar is not None:
        specials.add(d._escapechar)
    if d._quotechar is not None:
        specials.add(d._quotechar)
    self._specials = frozenset(specials)
    return self


def list_dialects():
    """Return a list of all known dialect names."""
    return list(_dialects)


def register_dialect(*args, **kwargs):
    """register_dialect(name, /, dialect='excel', **fmtparams)

    Create a mapping from a string name to a CVS dialect.

    The optional "dialect" argument specifies the base dialect instance
    or the name of the registered dialect.  The function also accepts
    optional keyword arguments which override settings provided by the
    dialect.
    """
    name, dialect = _unpack("register_dialect", args, 1, 2)
    if not isinstance(name, str):
        raise TypeError("dialect name must be a string")
    _dialects[name] = _call_dialect(dialect, kwargs)


def unregister_dialect(name):
    """Delete the name/dialect mapping associated with a string name."""
    try:
        del _dialects[name]
    except KeyError:
        raise Error("unknown dialect") from None


def get_dialect(name):
    """Return the dialect instance associated with name."""
    return _get_dialect_from_registry(name)


def field_size_limit(new_limit=_UNSET):
    """Sets an upper limit on parsed fields.

    Returns old limit. If limit is not given, no new limit is set and
    the old limit is returned
    """
    global _field_limit
    old = _field_limit
    if new_limit is not _UNSET:
        if type(new_limit) is not int:
            raise TypeError("limit must be an integer")
        _field_limit = _ssize(new_limit)
    return old
