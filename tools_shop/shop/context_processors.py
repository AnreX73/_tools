"""Контекст-процессоры приложения shop."""
from .models import PopupNotice


def popup_notice(request):
    """
    Делает активное всплывающее окно доступным на всех страницах сайта.

    Не считаем запрос там, где окно не рендерится: в админке, при htmx-запросах
    (отдаются фрагменты) и в служебных live-reload-запросах.
    """
    if request.headers.get("HX-Request"):
        return {}
    path = request.path
    if path.startswith("/admin/") or path.startswith("/__reload__/"):
        return {}
    return {"popup_notice": PopupNotice.get_active()}
