"""Seasons: Winter, Spring, Summer, Fall. A season label looks like 'Fall 2026'. Winter of a year covers December of the year before
through February, so seasons sort in calendar order."""
import datetime

SEASONS = ["Winter", "Spring", "Summer", "Fall"]


def label(season, year):
    return f"{season} {int(year)}"


def parse(lbl):
    name, yr = lbl.rsplit(" ", 1)
    return name, int(yr)


def key(lbl):
    name, yr = parse(lbl)
    return yr * 4 + SEASONS.index(name)


def number(name):
    return SEASONS.index(name) + 1


def previous(lbl):
    k = key(lbl) - 1
    return label(SEASONS[k % 4], k // 4)


def same_last_year(lbl):
    name, yr = parse(lbl)
    return label(name, yr - 1)


def from_date(d):
    m = d.month
    name = "Winter" if m in (12, 1, 2) else "Spring" if m <= 5 else "Summer" if m <= 8 else "Fall"
    return label(name, d.year + (1 if m == 12 else 0))


def from_ts(ts):
    try:
        return from_date(datetime.datetime.strptime(str(ts)[:10], "%Y-%m-%d"))
    except Exception:
        return from_date(datetime.date.today())


def ordered(labels):
    return sorted({x for x in labels if x}, key=key)


def current_label():
    import db
    v = db.get_setting("current_season", "")
    return v or from_date(datetime.date.today())
