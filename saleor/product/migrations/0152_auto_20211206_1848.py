# Generated by Django 3.2.6 on 2021-12-06 18:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0151_merge_20211206_1813'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productvariant',
            name='backorder_quantity_global_threshold',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='productvariantchannellisting',
            name='backorder_quantity_threshold',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
