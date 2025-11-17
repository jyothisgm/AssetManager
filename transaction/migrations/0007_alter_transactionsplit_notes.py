# Generated manually for changing TransactionSplit.notes from TextField to JSONField

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transaction', '0006_owesdummymodel_remove_transactionsplit_has_paid'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transactionsplit',
            name='notes',
            field=models.JSONField(blank=True, default=dict, help_text='Optional notes and split method metadata stored as JSON', null=True),
        ),
    ]

