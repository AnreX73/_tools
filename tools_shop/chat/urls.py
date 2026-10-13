from django.urls import path

from . import push_views, views

app_name = "chat"
urlpatterns = [
    path("push/vapid-public-key/", push_views.public_key, name="push-key"),
    path("push/subscribe/", push_views.subscribe, name="push-subscribe"),
    path("push/unsubscribe/", push_views.unsubscribe, name="push-unsubscribe"),
    path("start/", views.start, name="start"),
    path("operator/", views.inbox, name="inbox"),
    path("operator/<uuid:pk>/", views.conversation, name="conversation"),
]
