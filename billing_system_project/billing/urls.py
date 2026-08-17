from django.urls import include, path
from rest_framework.routers import DefaultRouter

from billing import views, web_views

router = DefaultRouter()
router.register("products", views.ProductViewSet, basename="product")

api_urlpatterns = [
    path("", include(router.urls)),
    path("purchases/generate-bill/", views.GenerateBillAPIView.as_view(), name="generate-bill"),
    path("purchases/", views.PurchaseListAPIView.as_view(), name="purchase-list"),
    path("purchases/<int:pk>/", views.PurchaseDetailAPIView.as_view(), name="purchase-detail"),
]

web_urlpatterns = [
    path("", web_views.billing_page, name="billing-page"),
    path("purchases/history/", web_views.purchase_history_page, name="purchase-history-page"),
    path("purchases/<int:pk>/", web_views.purchase_detail_page, name="purchase-detail-page"),
]
