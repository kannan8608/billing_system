"""
Jinja2 environment factory for Django's Jinja2 template backend.

Django templates get {% url %} and {% static %} tags for free; Jinja2
does not, so we expose equivalent global functions instead, as
recommended by the Django docs.
"""
from django.templatetags.static import static
from django.urls import reverse
from jinja2 import Environment


def environment(**options):
    env = Environment(**options)
    env.globals.update(
        {
            "static": static,
            "url": reverse,
        }
    )
    return env
