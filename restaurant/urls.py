from django.contrib import admin
from django.urls import include, path
from rest_framework import routers

from restaurant.catalog.preferences import preferences
from restaurant.catalog import views
from restaurant.catalog.orders import TableOrderViewSet
from restaurant.catalog.supplies import SupplyRequestViewSet
from restaurant.catalog.business import BusinessViewSet, InventoryViewSet
from restaurant.catalog.promotions import PromotionViewSet
from .catalog.views import CustomAuthToken, RegisterView, LogoutView, ResetTokenView, CardViewSet
from .catalog.views import me

from django.conf import settings
from django.conf.urls.static import static

from restaurant.catalog.reservations import ReservationViewSet, DiningTableViewSet

from restaurant.catalog.checkout import CheckoutViewSet, TableAccessViewSet

router = routers.DefaultRouter()
router.register(r'checkout', CheckoutViewSet, basename='checkout')
router.register(r'table-access', TableAccessViewSet, basename='table-access')
router.register(r"dining-tables", DiningTableViewSet, basename="dining-table")
router.register(r"reservations", ReservationViewSet, basename="reservation")
router.register(r"users", views.UserViewSet)
router.register(r"groups", views.GroupViewSet)

router.register(r"categories", views.CategoryViewSet)
router.register(r"cards", CardViewSet)
router.register(r"table-orders", TableOrderViewSet, basename="table-order")
router.register(r"supply-requests", SupplyRequestViewSet, basename="supply-request")
router.register(r"business", BusinessViewSet, basename="business")
router.register(r"inventory", InventoryViewSet, basename="inventory")
router.register(r"promotions", PromotionViewSet, basename="promotion")

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browsable API.
urlpatterns = [
    path("preferences/", preferences, name="preferences"),
    path("admin/", admin.site.urls),
    path("", include(router.urls)),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    path("api-token-auth/", CustomAuthToken.as_view(), name="api_token_auth"),
    path("register/", RegisterView.as_view(), name="api_register"),
    path('me', me, name='me'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('reset-token/', ResetTokenView.as_view(), name='reset_token'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)