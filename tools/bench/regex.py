"""Regex-heavy work: compiling patterns (re._parser, re._compiler) and matching."""
import re


def main():
    text = ("The quick brown fox jumps over the lazy dog 12345 times; "
            "email me at someone@example.com or other.person@test.org. ") * 20
    word = re.compile(r"\b\w+\b")
    email = re.compile(r"[\w.]+@[\w.]+\.\w+")
    num = re.compile(r"\d+")
    total = 0
    for _ in range(15):
        re.purge()
        for pat in (r"(?P<year>\d{4})-(?P<month>\d\d)-(?P<day>\d\d)", r"^\s*(#.*)?$",
                    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
                    r"(?i)(?:https?|ftp)://[^\s/$.?#].[^\s]*", r"(a|b|c|d)+?(?=x)[^xyz]{2,5}"):
            total += re.compile(pat).groups
        total += len(word.findall(text))
        total += len(email.findall(text))
        total += len(num.sub("#", text))
        total += sum(1 for _ in re.finditer(r"o\w", text))
        total += bool(re.match(r"(?:The|A) (\w+) (\w+)", text))
    print(total)


main()
