from django.contrib import admin
from django.urls import include, path
from rest_framework import routers

from tutorial.quickstart import views
from .quickstart.views import CustomAuthToken, RegisterView


router = routers.DefaultRouter()
router.register(r"users", views.UserViewSet)
router.register(r"groups", views.GroupViewSet)

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browsable API.
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include(router.urls)),
    path("", include("tutorial.quickstart.urls")),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    path("api-token-auth/", CustomAuthToken.as_view(), name="api_token_auth"),
    path("api-register/", views.RegisterView.as_view(), name="api_register"),
]