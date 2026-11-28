from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

VAT_DIVISOR = Decimal("122")
PROFIT_TAX_OSNO = Decimal("0.25")
USN_6_RATE = Decimal("0.06")
USN_15_RATE = Decimal("0.15")
USN_MIN_TAX_RATE = Decimal("0.01")
USN_VAT_5_DIVISOR = Decimal("105")
PLATON_RATE_PER_KM = Decimal("3.34")
PLATON_FED_SHARE = Decimal("0.75")
TWO_PLACES = Decimal("0.01")


def _r2(val: Decimal) -> Decimal:
    return val.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

def rate_breakdown_by_vat(amount: Decimal, is_vat_included: bool, distance_km: int | None) -> dict:
    no_vat = _r2(amount * Decimal("100") / Decimal("122")) if is_vat_included else amount
    with_vat = amount if is_vat_included else _r2(amount * Decimal("122") / Decimal("100"))
    result = {"no_vat": no_vat, "with_vat": with_vat}
    if distance_km and distance_km > 0:
        result["no_vat_per_km"] = (no_vat / Decimal(distance_km)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        result["with_vat_per_km"] = (with_vat / Decimal(distance_km)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return result


def _usn_vat(client_rate: Decimal, client_vat: bool, note: str) -> tuple[Decimal, str | None]:
    return (client_rate * Decimal("22") / VAT_DIVISOR, note) if client_vat else (Decimal("0"), None)

@dataclass(frozen=True)
class CalcResult:
    tax_mode: str
    client_rate: Decimal
    carrier_rate: Decimal
    vat_to_pay: Decimal
    income_tax: Decimal
    total_taxes: Decimal
    net_profit: Decimal
    margin_pct: Decimal
    stop_price: Decimal
    carrier_with_vat_eq: Decimal | None
    platon_hint: Decimal | None
    warning: str | None


def calculate_margin(
    tax_mode: str,
    client_rate: Decimal,
    carrier_rate: Decimal,
    client_vat: bool = False,
    carrier_vat: bool = False,
    weight_t: Decimal | None = None,
    deadhead_km: Decimal | None = None,
) -> CalcResult:
    if client_rate <= 0 or carrier_rate < 0:
        raise ValueError("Ставка клиента должна быть больше нуля, ставка перевозчика — не меньше нуля.")

    warning: str | None = None
    vat_to_pay = Decimal("0")
    income_tax = Decimal("0")
    carrier_eq: Decimal | None = None

    if tax_mode == "osno_22":
        rev_net = client_rate * Decimal("100") / VAT_DIVISOR
        vat_out = client_rate - rev_net
        cost_net = (carrier_rate * Decimal("100") / VAT_DIVISOR) if carrier_vat else carrier_rate
        vat_in = (carrier_rate - cost_net) if carrier_vat else Decimal("0")

        if not client_vat:
            warning = "На ОСНО НДС выделяется из ставки клиента — проверь условия договора."
        if not carrier_vat:
            carrier_eq = _r2(carrier_rate * VAT_DIVISOR / Decimal("100"))

        vat_to_pay = max(Decimal("0"), vat_out - vat_in)
        income_tax = max(Decimal("0"), (rev_net - cost_net) * PROFIT_TAX_OSNO)
        target_rev_net = cost_net + max(Decimal("0"), vat_in - vat_out)
        stop_price = target_rev_net * VAT_DIVISOR / Decimal("100")

    elif tax_mode == "usn_5_nds":
        rev_net = client_rate * Decimal("100") / USN_VAT_5_DIVISOR
        vat_to_pay = client_rate - rev_net
        income_tax = rev_net * USN_6_RATE
        if not client_vat:
            warning = "В ставке клиента учтён НДС 5% по режиму УСН."
        target_rev_net = carrier_rate / (Decimal("1") - USN_6_RATE)
        stop_price = target_rev_net * USN_VAT_5_DIVISOR / Decimal("100")

    elif tax_mode == "usn_6":
        vat_to_pay, warning = _usn_vat(client_rate, client_vat, "Выделенный НДС 22% уплачивается в бюджет без вычета входящего НДС.")
        income_tax = client_rate * USN_6_RATE
        stop_price = carrier_rate / (Decimal("1") - USN_6_RATE)

    elif tax_mode == "usn_6_agent":
        vat_to_pay, warning = _usn_vat(client_rate, client_vat, "Выделенный НДС 22% уплачивается в бюджет без вычета входящего НДС.")
        income_tax = max(Decimal("0"), client_rate - carrier_rate) * USN_6_RATE
        stop_price = carrier_rate

    elif tax_mode == "usn_15":
        vat_to_pay, warning = _usn_vat(client_rate, client_vat, "Выделенный НДС 22% уплачивается в бюджет без вычета входящего НДС.")
        tax_15 = max(Decimal("0"), client_rate - carrier_rate) * USN_15_RATE
        tax_min = client_rate * USN_MIN_TAX_RATE
        income_tax = max(tax_15, tax_min)
        stop_price = carrier_rate / (Decimal("1") - USN_MIN_TAX_RATE)

    else:
        raise ValueError(f"Неизвестный налоговый режим: {tax_mode}")

    total_taxes = vat_to_pay + income_tax
    net_profit = client_rate - carrier_rate - total_taxes
    margin_pct = (net_profit / client_rate) * Decimal("100")

    platon_hint: Decimal | None = None
    if weight_t is not None and weight_t >= Decimal("12") and deadhead_km and deadhead_km > 0:
        platon_hint = _r2(deadhead_km * PLATON_FED_SHARE * PLATON_RATE_PER_KM)

    return CalcResult(
        tax_mode=tax_mode,
        client_rate=_r2(client_rate),
        carrier_rate=_r2(carrier_rate),
        vat_to_pay=_r2(vat_to_pay),
        income_tax=_r2(income_tax),
        total_taxes=_r2(total_taxes),
        net_profit=_r2(net_profit),
        margin_pct=_r2(margin_pct),
        stop_price=_r2(stop_price),
        carrier_with_vat_eq=carrier_eq,
        platon_hint=platon_hint,
        warning=warning,
    )
