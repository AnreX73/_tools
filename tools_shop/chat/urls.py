from django.urls import path

from . import views

app_name = "chat"
urlpatterns = [
    path("start/", views.start, name="start"),
    path("operator/", views.inbox, name="inbox"),
    path("operator/<uuid:pk>/", views.conversation, name="conversation"),
]
