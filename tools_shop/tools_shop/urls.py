
from debug_toolbar.toolbar import debug_toolbar_urls
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from chat.push_views import service_worker




urlpatterns = [
    path('sw.js', service_worker, name='service-worker'),
    path('chat/', include('chat.urls')),
    path('admin/', admin.site.urls),
    path("cart/", include("cart.urls")),
    path("checkout/", include("checkout.urls")),
    path("", include("orders.urls")),
    path("", include("shop.urls")),
    # path("users/", include("users.urls")),
    path("__reload__/", include("django_browser_reload.urls"))
] + debug_toolbar_urls()

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)