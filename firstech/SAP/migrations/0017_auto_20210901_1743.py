# Generated by Django 3.2.6 on 2021-09-01 17:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('SAP', '0016_sapreturn_sapreturnline'),
    ]

    operations = [
        migrations.AddField(
            model_name='sapreturn',
            name='currency',
            field=models.CharField(default='USD', max_length=3),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='sapreturn',
            name='total_gross_amount',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='sapreturn',
            name='total_net_amount',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=12),
        ),
    ]