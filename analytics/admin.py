from django.contrib import admin
from django.urls import path
from django.shortcuts import render
from django.db.models import Sum, DecimalField, F, ExpressionWrapper, Value, Case, When
from django.db.models.functions import Coalesce
from datetime import datetime
from decimal import Decimal
from transaction.models import Transaction
from analytics.models import AnalyticsDummyModel
from common.logging_config import logger


@admin.register(AnalyticsDummyModel)
class AnalyticsAdmin(admin.ModelAdmin):
    site_header = "Asset Manager Admin"
    site_title = "Asset Manager"
    index_title = "Dashboard"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("analytics_dashboard/", self.admin_site.admin_view(self.analytics_dashboard), name="analytics_dashboard"),
            path("analytics_transactions_block/", self.admin_site.admin_view(self.transactions_block), name="analytics_transactions_block"),
        ]
        return custom_urls + urls

    def analytics_dashboard(self, request):
        func_name = "AnalyticsAdmin.analytics_dashboard"
        today = datetime.today()

        try:
            # --- Filters ---
            month = request.GET.get("month") or str(today.month)
            year = request.GET.get("year") or str(today.year)
            view_type = request.GET.get("view") or "monthly"

            month, year = int(month), int(year)
            logger.info(f"[{func_name}] Generating analytics — view={view_type}, month={month}, year={year}")

            # --- Filter transactions ---
            if view_type == "annual":
                transactions = Transaction.objects.filter(date__year=year, created_by=request.user)
            else:
                transactions = Transaction.objects.filter(date__year=year, date__month=month, created_by=request.user)

            # --- Currency-wise totals (income + expense) ---
            currency_summary = (
                transactions.values("currency__code")
                .annotate(
                    income=Coalesce(
                        Sum(
                            Case(
                                When(transaction_type="credit", then=F("amount")),
                                default=Value(0),
                                output_field=DecimalField(max_digits=20, decimal_places=2),
                            )
                        ),
                        Value(0),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    ),
                    expenses=Coalesce(
                        Sum(
                            Case(
                                When(transaction_type="debit", then=F("amount")),
                                default=Value(0),
                                output_field=DecimalField(max_digits=20, decimal_places=2),
                            )
                        ),
                        Value(0),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    ),
                    transfers=Coalesce(
                        Sum(
                            Case(
                                When(transaction_type__in=["transfer_debit", "transfer_credit"], then=F("amount")),
                                default=Value(0),
                                output_field=DecimalField(max_digits=20, decimal_places=2),
                            )
                        ),
                        Value(0),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                )
                .order_by("currency__code")
            )

            # --- Category totals by currency ---
            category_totals_by_currency = (
                transactions.filter(transaction_type="debit")
                .values("currency__code", "category__name")
                .annotate(
                    total=Coalesce(
                        Sum(
                            ExpressionWrapper(
                                F("amount"),
                                output_field=DecimalField(max_digits=20, decimal_places=2),
                            )
                        ),
                        Value(0),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                )
                .order_by("currency__code", "-total")
            )

            # --- Compute % within each currency ---
            totals_per_currency = {}
            for row in category_totals_by_currency:
                code = row["currency__code"] or "—"
                totals_per_currency[code] = totals_per_currency.get(code, Decimal("0")) + row["total"]

            for row in category_totals_by_currency:
                code = row["currency__code"] or "—"
                denom = totals_per_currency.get(code, Decimal("1"))
                row["percent"] = round((row["total"] / denom) * 100, 1)

            # --- Chart data for JS ---
            currency_chart_data = {}
            for row in category_totals_by_currency:
                code = row["currency__code"] or "—"
                currency_chart_data.setdefault(code, {"labels": [], "totals": []})
                currency_chart_data[code]["labels"].append(row["category__name"] or "—")
                currency_chart_data[code]["totals"].append(float(row["total"]))

            # --- Context ---
            context = {
                **self.admin_site.each_context(request),
                "title": "Analytics Dashboard",
                "currency_summary": currency_summary,
                "category_totals_by_currency": category_totals_by_currency,
                "currency_chart_data": currency_chart_data,
                "month": month,
                "year": year,
                "view_type": view_type,
                "months": range(1, 13),
                "years": range(today.year - 3, today.year + 1),
            }

            return render(request, "admin/analytics_dashboard.html", context)

        except Exception as e:
            logger.exception(f"[{func_name}] Error generating analytics: {e}")
            raise

    def transactions_block(self, request):
        """Return only the rendered HTML block for a selected category."""
        from django.template.loader import render_to_string
        from django.http import JsonResponse

        func_name = "AnalyticsAdmin.transactions_block"

        try:
            category_name = request.GET.get("category")
            currency = request.GET.get("currency")
            view_type = request.GET.get("view")
            month = int(request.GET.get("month", 0))
            year = int(request.GET.get("year"))

            transactions = Transaction.objects.filter(
                created_by=request.user,
                category__name=category_name,
                currency__code=currency,
            )
            if view_type == "monthly":
                transactions = transactions.filter(date__year=year, date__month=month)
            else:
                transactions = transactions.filter(date__year=year)

            selected_transactions = transactions.order_by("-amount")

            html = render_to_string(
                "admin/partials/_transactions_block.html",
                {
                    "selected_transactions": selected_transactions,
                    "selected_category": category_name,
                    "selected_currency": currency,
                },
                request=request,
            )
            return JsonResponse({"html": html})

        except Exception as e:
            logger.exception(f"[{func_name}] Error: {e}")
            return JsonResponse({"error": str(e)}, status=500)
