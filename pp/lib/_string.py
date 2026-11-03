"""Pure Python implementation of CPython's string.Formatter helpers.

The parsing rules follow Objects/stringlib/unicode_format.h.  The returned
iterators parse on demand, including reporting malformed input only when the
corresponding part is consumed.
"""

import sys


def _integer(text):
    if not text:
        return text
    value = 0
    for char in text:
        if not char.isdecimal():
            return text
        digit = int(char)
        if value > (sys.maxsize - digit) // 10:
            raise ValueError("Too many decimal digits in format string")
        value = value * 10 + digit
    return value


class _FieldNameIterator:
    def __init__(self, text, index):
        self.text = text
        self.index = index

    def __iter__(self):
        return self

    def __next__(self):
        text = self.text
        index = self.index
        if index >= len(text):
            raise StopIteration
        kind = text[index]
        index += 1
        self.index = index
        if kind == '.':
            start = index
            while index < len(text) and text[index] not in '.[':
                index += 1
            self.index = index
            name = text[start:index]
            is_attr = True
        elif kind == '[':
            start = index
            while index < len(text) and text[index] != ']':
                index += 1
            if index == len(text):
                self.index = index
                raise ValueError("Missing ']' in format string")
            self.index = index + 1
            name = _integer(text[start:index])
            is_attr = False
        else:
            raise ValueError("Only '.' or '[' may follow ']' in format field specifier")
        if name == '':
            raise ValueError("Empty attribute in format string")
        return is_attr, name


def _one_arg(name, args, kwargs):
    # METH_O argument checking (Objects/methodobject.c)
    if kwargs:
        raise TypeError(f"_string.{name}() takes no keyword arguments")
    if len(args) != 1:
        raise TypeError(f"_string.{name}() takes exactly one argument ({len(args)} given)")
    return args[0]


def formatter_field_name_split(*args, **kwargs):
    text = _one_arg("formatter_field_name_split", args, kwargs)
    if not isinstance(text, str):
        raise TypeError(f"expected str, got {type(text).__name__}")
    text = str.__str__(text)
    index = 0
    while index < len(text) and text[index] not in '.[':
        index += 1
    return _integer(text[:index]), _FieldNameIterator(text, index)


class _FormatterIterator:
    def __init__(self, text):
        self.text = text
        self.index = 0

    def __iter__(self):
        return self

    def __next__(self):
        text = self.text
        end = len(text)
        start = self.index
        if start >= end:
            raise StopIteration

        index = start
        while index < end and text[index] not in '{}':
            index += 1
        if index == end:
            self.index = end
            return text[start:end], None, None, None

        brace = text[index]
        index += 1
        self.index = index
        if index == end or text[index] != brace:
            if brace == '}':
                raise ValueError("Single '}' encountered in format string")
            if index == end:
                raise ValueError("Single '{' encountered in format string")
        else:
            self.index = index + 1
            return text[start:index], None, None, None

        literal = text[start:index - 1]
        field_start = index
        char = ''
        while index < end:
            char = text[index]
            index += 1
            if char == '{':
                self.index = index
                raise ValueError("unexpected '{' in field name")
            if char == '[':
                while index < end and text[index] != ']':
                    index += 1
                continue
            if char in '}:!':
                break
        self.index = index
        field = text[field_start:index - 1]
        if char == '}':
            return literal, field, '', None
        if char not in ':!' or char == '':
            raise ValueError("expected '}' before end of string")

        conversion = None
        if char == '!':
            if index >= end:
                raise ValueError("end of string while looking for conversion specifier")
            conversion = text[index]
            if conversion == '\0':
                conversion = None
            index += 1
            self.index = index
            if index < end:
                char = text[index]
                index += 1
                self.index = index
                if char == '}':
                    return literal, field, '', conversion
                if char != ':':
                    raise ValueError("expected ':' after conversion specifier")

        spec_start = index
        depth = 1
        while index < end:
            char = text[index]
            index += 1
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    self.index = index
                    return literal, field, text[spec_start:index - 1], conversion
        self.index = index
        raise ValueError("unmatched '{' in format spec")


def formatter_parser(*args, **kwargs):
    text = _one_arg("formatter_parser", args, kwargs)
    if not isinstance(text, str):
        raise TypeError(f"expected str, got {type(text).__name__}")
    return _FormatterIterator(str.__str__(text))
