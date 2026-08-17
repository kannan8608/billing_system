"""
Business logic that is independent of Django's request/response cycle,
so it can be unit tested in isolation from views/serializers.
"""
import logging
import math
import threading
from decimal import ROUND_DOWN, Decimal

from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def round_down_to_whole(amount: Decimal) -> Decimal:
    """Round a Decimal amount DOWN to the nearest whole currency unit.

    Example: 2357.60 -> 2357.00 (matches the wireframe's
    "Rounded down value of the purchased items net price").
    """
    return amount.quantize(Decimal("1"), rounding=ROUND_DOWN)


def compute_change_denominations(balance_amount: Decimal, available_denominations: dict) -> dict:
    """
    Greedily break `balance_amount` (a whole-number Decimal) down into
    denomination counts, constrained by what's actually available in the
    till right now.

    Args:
        balance_amount: non-negative whole-number amount to return as change.
        available_denominations: {denomination_value(int): available_count(int)}

    Returns:
        {denomination_value(int): count_used(int)} for denominations actually used.

    Raises:
        ValueError: if the available denominations cannot exactly make up
            balance_amount (i.e. the till cannot give exact change).
    """
    remaining = int(balance_amount)
    if remaining < 0:
        raise ValueError("balance_amount must not be negative")

    result = {}
    for value in sorted((v for v in available_denominations if v > 0), reverse=True):
        if remaining <= 0:
            break
        max_available = int(available_denominations.get(value, 0))
        if max_available <= 0:
            continue
        usable = min(remaining // value, max_available)
        if usable > 0:
            result[value] = usable
            remaining -= usable * value

    if remaining != 0:
        raise ValueError(
            "Cannot make exact change of %s with the available denominations." % balance_amount
        )
    return result


def send_invoice_email_async(purchase, plain_text_body: str, html_body: str = ""):
    """
    Send the invoice email in a background thread so the API request that
    generates the bill does not block on SMTP latency.

    A lightweight `threading.Thread` is used rather than a task queue
    (Celery/RQ) so the project has no extra infrastructure dependency
    (broker/worker) and runs out of the box with `manage.py runserver`.
    For a larger production deployment, swap this for a Celery task --
    the call site (views.py) would not need to change.
    """

    def _send():
        from billing.models import Purchase  # local import to avoid app-loading issues in thread

        try:
            email = EmailMessage(
                subject=f"Your invoice #{purchase.pk}",
                body=plain_text_body,
                to=[purchase.customer_email],
            )
            if html_body:
                email.content_subtype = "html"
                email.body = html_body
            email.send(fail_silently=False)
            Purchase.objects.filter(pk=purchase.pk).update(email_sent=True, email_error="")
        except Exception as exc:  # noqa: BLE001 - log and record, never crash the thread
            logger.exception("Failed to send invoice email for purchase %s", purchase.pk)
            Purchase.objects.filter(pk=purchase.pk).update(email_sent=False, email_error=str(exc))

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def build_invoice_email_body(purchase) -> str:
    """Plain-text invoice body built from a saved Purchase (with .items prefetched)."""
    lines = [
        f"Invoice #{purchase.pk}",
        f"Customer: {purchase.customer_email}",
        "",
        "Items:",
    ]
    for item in purchase.items.all():
        lines.append(
            f"  {item.product_id_snapshot} ({item.product_name_snapshot}) "
            f"x{item.quantity} @ {item.unit_price_snapshot} "
            f"= {item.total_price} (incl. tax {item.tax_payable})"
        )
    lines += [
        "",
        f"Total price without tax: {purchase.total_price_without_tax}",
        f"Total tax payable: {purchase.total_tax_payable}",
        f"Net price: {purchase.net_price}",
        f"Rounded net price: {purchase.rounded_net_price}",
        f"Cash paid: {purchase.cash_paid}",
        f"Balance returned: {purchase.balance_amount}",
        "",
        "Thank you for your purchase!",
    ]
    return "\n".join(lines)
