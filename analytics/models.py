from django.db import models

class AnalyticsDummyModel(models.Model):
    class Meta:
        managed = False
        verbose_name = "Analytics Dashboard"
        verbose_name_plural = "Analytics Dashboard"
