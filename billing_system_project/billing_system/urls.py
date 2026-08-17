from django.contrib import admin
from django.urls import include, path

from billing.urls import api_urlpatterns, web_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_urlpatterns)),
    path("", include(web_urlpatterns)),
]
