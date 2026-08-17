"""
Server-rendered "View" layer (Jinja2 templates) that wraps the REST API.

Page 1 (billing form) and the history search page render mostly-static
shells; their forms POST/GET against the REST API asynchronously via
fetch() in a small inline script, per the requirement that bill
generation itself must happen asynchronously.

Page 2 (bill detail) is rendered server-side directly from the database,
so it can be reused both right after generating a bill and when revisiting
a purchase from history -- selecting a purchase from history shows the
exact same view.
"""
from django.shortcuts import get_object_or_404, render

from billing.models import Purchase


#: Default denomination values shown on Page 1, matching the wireframe.
#: Falls back to this list if no Denomination rows exist in the DB yet.
DEFAULT_DENOMINATIONS = [500, 50, 20, 10, 5, 2, 1]


def billing_page(request):
    """Page 1: the billing form."""
    from billing.models import Denomination

    values = list(Denomination.objects.values_list("value", flat=True))
    context = {"default_denominations": sorted(values, reverse=True) or DEFAULT_DENOMINATIONS}
    return render(request, "billing/page1.html", context)


def purchase_detail_page(request, pk):
    """Page 2: bill detail, both for a freshly generated bill and for history."""
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related("items", "balance_denominations"), pk=pk
    )
    return render(request, "billing/page2.html", {"purchase": purchase})


def purchase_history_page(request):
    """'View previous purchases': search by customer email, then list + drill in."""
    email = request.GET.get("customer_email", "").strip()
    purchases = []
    if email:
        purchases = Purchase.objects.filter(customer_email__iexact=email)
    return render(
        request,
        "billing/history.html",
        {"email": email, "purchases": purchases},
    )
