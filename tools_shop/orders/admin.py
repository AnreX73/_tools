"""
orders/admin.py

Рабочее место менеджера: заявки, позиции, история статусов, счета.

Ключевые правила:
* состав заявки редактируется только в ``new``/``review``, после выставления
  счёта inline становится read-only;
* статус меняется только действиями, а не свободным редактированием поля;
* одобрение идёт через ``orders.services.approve_order`` — счёт и статус
  меняются в одной транзакции, PDF/письмо ставится в очередь после коммита;
* отклонение требует комментарий и идёт через промежуточную форму.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    Invoice,
    InvoiceNotAllowed,
    InvalidTransition,
    Order,
    OrderItem,
    OrderStatusLog,
)
from .pdf import InvoicePDFError, render_invoice_pdf
from .services import approve_order, reissue_invoice as reissue_invoice_service
from .statuses import OrderStatus, can_transition

logger = logging.getLogger(__name__)


class RejectOrdersForm(forms.Form):
    """Промежуточная форма отклонения: комментарий обязателен."""

    order_ids = forms.CharField(widget=forms.HiddenInput)
    comment = forms.CharField(
        label="Причина отклонения",
        required=True,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "class": "vLargeTextField",
                "placeholder": "Например: нет в наличии, неверные реквизиты…",
            }
        ),
    )

    def clean_order_ids(self):
        raw = (self.cleaned_data.get("order_ids") or "").strip()
        if not raw:
            raise forms.ValidationError("Не выбрано ни одной заявки.")
        try:
            ids = [int(part) for part in raw.split(",") if part.strip()]
        except ValueError as exc:
            raise forms.ValidationError("Некорректный список заявок.") from exc
        if not ids:
            raise forms.ValidationError("Не выбрано ни одной заявки.")
        if len(ids) != len(set(ids)):
            raise forms.ValidationError("Заявки в списке повторяются.")
        if len(ids) > 500:
            raise forms.ValidationError("За один раз можно отклонить не более 500 заявок.")
        return ids


class OrderItemInline(admin.TabularInline):
    """Позиции заявки; редактируются только до выставления счёта."""

    model = OrderItem
    extra = 0
    fields = ("product", "name", "sku", "price", "qty", "line_total")
    readonly_fields = ("line_total",)
    autocomplete_fields = ("product",)

    @admin.display(description="Сумма")
    def line_total(self, obj):
        return obj.line_total if obj and obj.pk else "—"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product")

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and not obj.is_editable:
            return ("product", "name", "sku", "price", "qty", "line_total")
        return ("line_total",)

    def has_add_permission(self, request, obj=None):
        return bool(obj is not None and obj.is_editable)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is not None and obj.is_editable)


class OrderStatusLogInline(admin.TabularInline):
    """История статусов — только чтение, без добавления и удаления."""

    model = OrderStatusLog
    extra = 0
    can_delete = False
    fields = ("at", "from_status", "to_status", "changed_by", "comment")
    readonly_fields = fields

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("changed_by")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class InvoiceInline(admin.TabularInline):
    """Счета заявки со ссылкой на предпросмотр PDF."""

    model = Invoice
    extra = 0
    can_delete = False
    fields = ("number", "version", "issued_at", "sent_at", "is_current", "pdf_link")
    readonly_fields = fields

    @admin.display(description="PDF")
    def pdf_link(self, obj):
        if not obj or not obj.pk:
            return "—"
        url = reverse("admin:orders_invoice_preview", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Предпросмотр</a>',
            url,
        )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "created_at",
        "company",
        "contact_name",
        "status",
        "total",
        "invoice_state",
    )
    list_filter = (
        "status",
        ("created_at", admin.DateFieldListFilter),
        "company__is_verified",
    )
    search_fields = (
        "number",
        "company__inn",
        "company__short_name",
        "company__full_name",
        "contact_email",
        "contact_name",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-pk")
    list_select_related = ("company",)
    list_per_page = 50

    readonly_fields = (
        "number",
        "uuid",
        "company",
        "user",
        "status",
        "idempotency_key",
        "consent_at",
        "requisites_snapshot",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Заявка",
            {
                "fields": (
                    "number",
                    "uuid",
                    "status",
                    "created_at",
                    "updated_at",
                )
            },
        ),
        (
            "Клиент",
            {
                "fields": (
                    "company",
                    "user",
                    "contact_name",
                    "contact_email",
                    "contact_phone",
                )
            },
        ),
        (
            "Доставка",
            {
                "fields": ("delivery_address", "comment"),
            },
        ),
        (
            "Реквизиты на момент заявки",
            {
                "fields": ("requisites_snapshot",),
                "classes": ("collapse",),
            },
        ),
        (
            "Служебное",
            {
                "fields": ("idempotency_key", "consent_at"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = (OrderItemInline, InvoiceInline, OrderStatusLogInline)

    actions = (
        "take_to_work",
        "approve_and_send",
        "reject_orders",
        "mark_paid",
        "mark_shipped",
        "mark_done",
        "cancel_orders",
        "reissue_invoice",
    )

    # ---- list display -----------------------------------------------------
    @admin.display(description="Сумма")
    def total(self, obj):
        return f"{obj.items_total} руб."

    @admin.display(description="Счёт")
    def invoice_state(self, obj):
        invoice = next(
            (item for item in obj.invoices.all() if item.is_current),
            None,
        )
        if invoice is None:
            return "—"
        state = "отправлен" if invoice.sent_at else "не отправлен"
        return f"{invoice.number} (v{invoice.version}), {state}"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .with_relations()
            .prefetch_related("invoices", "status_log")
        )

    # ---- URLs -------------------------------------------------------------
    def get_urls(self):
        custom = [
            path(
                "reject/",
                self.admin_site.admin_view(self.reject_view),
                name="orders_order_reject",
            ),
        ]
        return custom + super().get_urls()

    # ---- actions ----------------------------------------------------------
    @admin.action(description="Взять в работу")
    def take_to_work(self, request, queryset):
        changed = 0
        skipped = []
        for order in queryset:
            if order.status != OrderStatus.NEW:
                skipped.append(order.number)
                continue
            try:
                order.transition_to(
                    OrderStatus.REVIEW,
                    by=request.user,
                    comment="Взято в работу менеджером",
                )
            except InvalidTransition:
                skipped.append(order.number)
            else:
                changed += 1
        if changed:
            self.message_user(
                request, f"Взято в работу: {changed}.", messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                "Пропущены заявки не в статусе «Новая»: " + ", ".join(skipped),
                messages.WARNING,
            )

    @admin.action(description="Одобрить и отправить счёт")
    def approve_and_send(self, request, queryset):
        approved = 0
        skipped = []
        for order in queryset:
            if order.status != OrderStatus.REVIEW:
                skipped.append(order.number)
                continue
            try:
                invoice = approve_order(
                    order,
                    by=request.user,
                    comment="Одобрено менеджером",
                )
            except (InvoiceNotAllowed, InvalidTransition):
                skipped.append(order.number)
            else:
                approved += 1
                self.message_user(
                    request,
                    f"Заявка {order.number}: выставлен счёт {invoice.number} "
                    f"(v{invoice.version}).",
                    messages.SUCCESS,
                )
        if not approved and skipped:
            self.message_user(
                request,
                "Одобрять можно только заявки на проверке. Пропущены: "
                + ", ".join(skipped),
                messages.WARNING,
            )
        elif skipped:
            self.message_user(
                request,
                "Пропущены заявки не на проверке: " + ", ".join(skipped),
                messages.WARNING,
            )

    @admin.action(description="Отклонить")
    def reject_orders(self, request, queryset):
        ids = list(queryset.values_list("pk", flat=True))
        if not ids:
            self.message_user(request, "Заявки не выбраны.", messages.WARNING)
            return None
        query = urlencode({"ids": ",".join(str(pk) for pk in ids)})
        return HttpResponseRedirect(
            reverse("admin:orders_order_reject") + "?" + query
        )

    def reject_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        raw_ids = request.POST.get("order_ids") or request.GET.get("ids", "")
        if request.method == "POST":
            form = RejectOrdersForm(request.POST)
            if form.is_valid():
                ids = form.cleaned_data["order_ids"]
                orders = list(
                    self.get_queryset(request)
                    .select_related("company")
                    .filter(pk__in=ids)
                )
                if len(orders) != len(ids):
                    form.add_error(None, "Часть выбранных заявок не найдена.")
                else:
                    not_allowed = [
                        order.number
                        for order in orders
                        if not can_transition(order.status, OrderStatus.REJECTED)
                    ]
                    if not_allowed:
                        form.add_error(
                            None,
                            "Нельзя отклонить заявки: " + ", ".join(not_allowed),
                        )
                    else:
                        try:
                            with transaction.atomic():
                                for order in orders:
                                    order.transition_to(
                                        OrderStatus.REJECTED,
                                        by=request.user,
                                        comment=form.cleaned_data["comment"],
                                    )
                        except InvalidTransition as exc:
                            form.add_error(None, str(exc))
                        else:
                            self.message_user(
                                request,
                                f"Отклонено заявок: {len(orders)}.",
                                messages.SUCCESS,
                            )
                            return HttpResponseRedirect(
                                reverse("admin:orders_order_changelist")
                            )
        else:
            if not raw_ids.strip():
                self.message_user(
                    request, "Заявки не выбраны.", messages.WARNING
                )
                return HttpResponseRedirect(
                    reverse("admin:orders_order_changelist")
                )
            form = RejectOrdersForm(initial={"order_ids": raw_ids})

        display_ids = []
        try:
            display_ids = [int(part) for part in raw_ids.split(",") if part.strip()]
        except ValueError:
            display_ids = []
        orders = (
            self.get_queryset(request)
            .select_related("company")
            .filter(pk__in=display_ids)
            if display_ids
            else []
        )
        context = {
            **self.admin_site.each_context(request),
            "title": "Отклонить заявки",
            "form": form,
            "orders": orders,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/orders/order/reject_confirmation.html",
            context,
        )

    @admin.action(description="Отметить оплаченными")
    def mark_paid(self, request, queryset):
        self._bulk_transition(
            request,
            queryset,
            OrderStatus.PAID,
            "Оплата подтверждена менеджером",
        )

    @admin.action(description="Отметить отгруженными")
    def mark_shipped(self, request, queryset):
        self._bulk_transition(
            request,
            queryset,
            OrderStatus.SHIPPED,
            "Заказ отгружен",
        )

    @admin.action(description="Завершить заявки")
    def mark_done(self, request, queryset):
        self._bulk_transition(
            request,
            queryset,
            OrderStatus.DONE,
            "Заказ завершён",
        )

    @admin.action(description="Отменить заявки")
    def cancel_orders(self, request, queryset):
        self._bulk_transition(
            request,
            queryset,
            OrderStatus.CANCELLED,
            "Отменено менеджером",
        )

    def _bulk_transition(self, request, queryset, status, comment):
        changed = 0
        skipped = []
        for order in queryset:
            try:
                order.transition_to(status, by=request.user, comment=comment)
            except InvalidTransition:
                skipped.append(order.number)
            else:
                changed += 1
        if changed:
            self.message_user(
                request,
                f"Статус изменён у заявок: {changed}.",
                messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                "Пропущены заявки с недопустимым переходом: "
                + ", ".join(skipped),
                messages.WARNING,
            )

    @admin.action(description="Перевыставить счёт")
    def reissue_invoice(self, request, queryset):
        changed = 0
        skipped = []
        for order in queryset:
            if not order.invoices.current().exists():
                skipped.append(order.number)
                continue
            try:
                invoice = reissue_invoice_service(
                    order,
                    by=request.user,
                    comment="Счёт перевыставлен менеджером",
                )
            except (InvoiceNotAllowed, InvalidTransition):
                skipped.append(order.number)
            else:
                changed += 1
                self.message_user(
                    request,
                    f"Заявка {order.number}: счёт {invoice.number} "
                    f"перевыставлен (v{invoice.version}).",
                    messages.SUCCESS,
                )
        if skipped:
            self.message_user(
                request,
                "Не удалось перевыставить счёт: " + ", ".join(skipped),
                messages.WARNING,
            )
        if not changed and not skipped:
            self.message_user(request, "Счета не перевыставлены.", messages.WARNING)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "version",
        "order",
        "issued_at",
        "sent_at",
        "is_current",
        "preview_link",
    )
    list_filter = (
        "is_current",
        ("issued_at", admin.DateFieldListFilter),
        ("sent_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "number",
        "order__number",
        "order__company__inn",
        "order__contact_email",
    )
    list_select_related = ("order", "order__company")
    date_hierarchy = "issued_at"
    ordering = ("-issued_at", "-version")

    fields = (
        "order",
        "number",
        "version",
        "issued_at",
        "sent_at",
        "is_current",
        "pdf",
        "preview_link",
        "created_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="PDF")
    def preview_link(self, obj):
        if not obj or not obj.pk:
            return "—"
        url = reverse("admin:orders_invoice_preview", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Открыть предпросмотр</a>',
            url,
        )

    def get_urls(self):
        custom = [
            path(
                "<int:pk>/preview/",
                self.admin_site.admin_view(self.preview_view),
                name="orders_invoice_preview",
            ),
        ]
        return custom + super().get_urls()

    def preview_view(self, request, pk):
        invoice = get_object_or_404(
            Invoice.objects.select_related("order__company").prefetch_related(
                "order__items"
            ),
            pk=pk,
        )
        if not self.has_view_or_change_permission(request, invoice):
            raise PermissionDenied

        try:
            pdf_bytes = render_invoice_pdf(invoice)
        except InvoicePDFError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            return HttpResponseRedirect(
                reverse("admin:orders_invoice_change", args=[invoice.pk])
            )
        except Exception:  # noqa: BLE001 - не показываем менеджеру traceback
            logger.exception(
                "Не удалось сформировать предпросмотр счёта %s", invoice.pk
            )
            self.message_user(
                request,
                "Не удалось сформировать PDF счёта. Подробности в журнале.",
                messages.ERROR,
            )
            return HttpResponseRedirect(
                reverse("admin:orders_invoice_change", args=[invoice.pk])
            )

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="invoice-{invoice.pk}-v{invoice.version}.pdf"'
        )
        return response
