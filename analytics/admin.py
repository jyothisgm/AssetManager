from datetime import datetime
from decimal import Decimal

from django.contrib import admin
from django.db.models import Case, DecimalField, ExpressionWrapper, F, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import path

from analytics.models import AnalyticsDummyModel
from common.logging_config import logger
from transaction.models import Transaction


@admin.register(AnalyticsDummyModel)
class AnalyticsAdmin(admin.ModelAdmin):
    """Custom admin for the analytics dashboard."""

    site_header = "Asset Manager Admin"
    site_title = "Asset Manager"
    index_title = "Dashboard"

    # ---------------------------------------------------------
    # URLs
    # ---------------------------------------------------------
    def get_urls(self):
        """Register custom analytics URLs under the admin site."""
        base_urls = super().get_urls()
        custom_urls = [
            path(
                "analytics_dashboard/",
                self.admin_site.admin_view(self.analytics_dashboard),
                name="analytics_dashboard",
            ),
            path(
                "analytics_transactions_block/",
                self.admin_site.admin_view(self.transactions_block),
                name="analytics_transactions_block",
            ),
        ]
        return custom_urls + base_urls

    # ---------------------------------------------------------
    # Dashboard view
    # ---------------------------------------------------------
    def analytics_dashboard(self, request):
        """Render the analytics dashboard summary (currency, categories, charts)."""
        func_name = "AnalyticsAdmin.analytics_dashboard"
        today = datetime.today()

        try:
            # --- Query parameters ---
            month = int(request.GET.get("month") or today.month)
            year = int(request.GET.get("year") or today.year)
            view_type = request.GET.get("view") or "monthly"

            logger.info(f"[{func_name}] Generating analytics — view={view_type}, month={month}, year={year}")

            # --- Base queryset ---
            tx_filter = {"date__year": year, "created_by": request.user}
            if view_type == "monthly":
                tx_filter["date__month"] = month

            transactions = Transaction.objects.filter(**tx_filter)

            # -----------------------------------------------------
            # Currency-wise totals (income, expense, transfers)
            # -----------------------------------------------------
            D = DecimalField(max_digits=20, decimal_places=2)
            zero = Value(0, output_field=D)

            currency_summary = (
                transactions.values("currency__code")
                .annotate(
                    income=Coalesce(Sum(Case(When(transaction_type="credit", then=F("amount")), default=zero, output_field=D)), zero, output_field=D),
                    expenses=Coalesce(Sum(Case(When(transaction_type="debit", then=F("amount")), default=zero, output_field=D)), zero, output_field=D),
                    transfers=Coalesce(
                        Sum(Case(
                            When(transaction_type="transfer_credit", then=F("amount")),
                            When(transaction_type="transfer_debit", then=-F("amount")),
                            default=zero,
                            output_field=D,
                        )),
                        zero,
                        output_field=D,
                    ),
                )
            )

            # -----------------------------------------------------
            # Helper to build category breakdown per currency
            # -----------------------------------------------------
            def build_category_totals(transactions_qs, tx_type: str):
                data = (
                    transactions_qs.filter(transaction_type=tx_type)
                    .values("currency__code", "category__name")
                    .annotate(
                        total=Coalesce(
                            Sum(ExpressionWrapper(F("amount"), output_field=D), output_field=D),
                            zero,
                            output_field=D,
                        )
                    )
                    .order_by("currency__code", "-total")
                )

                totals_per_currency = {}
                for row in data:
                    code = row["currency__code"] or "—"
                    totals_per_currency[code] = totals_per_currency.get(code, Decimal(0)) + row["total"]

                for row in data:
                    code = row["currency__code"] or "—"
                    denom = totals_per_currency.get(code, Decimal(1))
                    row["percent"] = round((row["total"] / denom) * 100, 1)

                chart_data = {}
                for row in data:
                    code = row["currency__code"] or "—"
                    chart_data.setdefault(code, {"labels": [], "totals": []})
                    chart_data[code]["labels"].append(row["category__name"] or "—")
                    chart_data[code]["totals"].append(float(row["total"]))

                return data, chart_data

            # --- Build debit/credit data sets ---
            category_debit, chart_debit = build_category_totals(transactions, "debit")
            category_credit, chart_credit = build_category_totals(transactions, "credit")

            # -----------------------------------------------------
            # Render dashboard
            # -----------------------------------------------------
            context = {
                **self.admin_site.each_context(request),
                "title": "Analytics Dashboard",
                "currency_summary": currency_summary,
                "category_totals_by_currency_debit": category_debit,
                "category_totals_by_currency_credit": category_credit,
                "currency_chart_data_debit": chart_debit,
                "currency_chart_data_credit": chart_credit,
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

    # ---------------------------------------------------------
    # Partial transactions block (AJAX)
    # ---------------------------------------------------------
    def transactions_block(self, request):
        """Return rendered HTML for transactions in a selected category (AJAX)."""
        func_name = "AnalyticsAdmin.transactions_block"

        try:
            category_name = request.GET.get("category")
            currency = request.GET.get("currency")
            transaction_type = request.GET.get("transaction_type")
            view_type = request.GET.get("view")
            year = int(request.GET.get("year"))
            month = int(request.GET.get("month", 0))

            # --- Query ---
            qs = Transaction.objects.filter(
                created_by=request.user,
                category__name=category_name,
                currency__code=currency,
                transaction_type=transaction_type,
            )
            qs = qs.filter(date__year=year)
            if view_type == "monthly":
                qs = qs.filter(date__month=month)

            selected_transactions = qs.order_by("-date")

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
