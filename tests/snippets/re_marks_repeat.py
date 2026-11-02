import re
# marks are only saved/restored while a REPEAT is active (as in sre_lib.h)
print(re.fullmatch(r'((?:(?(1)a|b)*+|\w?(b)){0,2}?)\w', 'baaaac'))
print(re.match(r'(a|ab)(c|bcd)(d*)', 'abcd').groups())
print(re.match(r'(?:ab)*', 'ab' * 3000).end())
print(re.match(r'"(?:[^"\\]|\\.)*"', '"' + 'x' * 3000 + '"').end())
