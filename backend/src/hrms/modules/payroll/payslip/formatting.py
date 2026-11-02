"""How amounts and identifiers are written on a payslip (Indian conventions)."""

from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("0.01")

_ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
    "Eighteen", "Nineteen",
)  # fmt: skip
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def to_paise(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_UP)


def format_inr(amount: Decimal) -> str:
    """1234567.5 -> "12,34,567.50": the last three digits, then groups of two."""
    value = to_paise(amount)
    sign = "-" if value < 0 else ""
    rupees, paise = f"{abs(value):.2f}".split(".")
    head, tail = rupees[:-3], rupees[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join([*groups, tail]) + "." + paise


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = [f"{_ONES[hundreds]} Hundred"] if hundreds else []
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def _indian_words(n: int) -> str:
    if n == 0:
        return "Zero"
    crores, n = divmod(n, 10_000_000)
    lakhs, n = divmod(n, 100_000)
    thousands, n = divmod(n, 1000)
    parts = []
    if crores:
        parts.append(f"{_indian_words(crores)} Crore")
    if lakhs:
        parts.append(f"{_below_hundred(lakhs)} Lakh")
    if thousands:
        parts.append(f"{_below_hundred(thousands)} Thousand")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(amount: Decimal) -> str:
    """41362.91 -> "Rupees Forty-One Thousand Three Hundred Sixty-Two and Ninety-One Paise Only"."""
    value = to_paise(amount)
    prefix = "Minus " if value < 0 else ""
    rupees, paise = divmod(int(abs(value) * 100), 100)
    words = f"{prefix}Rupees {_indian_words(rupees)}"
    if paise:
        words += f" and {_below_hundred(paise)} Paise"
    return words + " Only"


def mask(value: str | None, keep: int = 4) -> str | None:
    """Every character but the last `keep` replaced by X: a bank account prints XXXXXXXX4821."""
    if not value:
        return value
    value = value.strip()
    if len(value) <= keep:
        return value
    return "X" * (len(value) - keep) + value[-keep:]
