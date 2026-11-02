import bisect


def t(f, *a, **k):
    try:
        print(f(*a, **k))
    except Exception as e:
        print(type(e).__name__, e)


# the host's message wording for a negative lo varies between 3.15 builds
# ("lo must be non-negative" / "lo cannot be negative"), so only the type
for f, a, k in ((bisect.bisect_left, ([1, 2, 3], 2, -1), {}),
                (bisect.bisect_right, ([1, 2, 3], 2), {"lo": -5}),
                (bisect.insort_left, ([1, 2, 3], 2, -1), {})):
    try:
        f(*a, **k)
    except ValueError as e:
        print(type(e).__name__, "lo" in str(e))
t(bisect.bisect_left, [1, 2, 3], 2, 0, "x")
t(bisect.bisect_right, [1, 2, 3], 2, 0, 2.5)
t(bisect.bisect_left, [1, 2, 3], 2, "x")
t(bisect.bisect_left, [1, 2, 3], 2, 0, None)
t(bisect.bisect_left, [1, 2, 3], 2, 0, -1)
t(bisect.bisect_left, 5, 2)
t(bisect.bisect_left, {1: 2}, 2)
