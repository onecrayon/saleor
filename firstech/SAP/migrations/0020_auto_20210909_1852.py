# Generated by Django 3.2.6 on 2021-09-09 18:52

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def clear_shipping_methods(apps, schema_editor):
    business_partner = apps.get_model("SAP", "BusinessPartner")
    business_partner.objects.all().update(shipping_preference=None)


class Migration(migrations.Migration):

    dependencies = [
        ('shipping', '0031_alter_shippingmethodtranslation_language_code'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('SAP', '0019_auto_20210907_1744'),
    ]

    operations = [
        migrations.RunPython(clear_shipping_methods),
        migrations.AddField(
            model_name='businesspartneraddresses',
            name='row_number',
            field=models.IntegerField(null=True),
        ),
        migrations.AlterUniqueTogether(
            name='businesspartneraddresses',
            unique_together={('business_partner', 'row_number')},
        ),
        migrations.CreateModel(
            name='SAPSalesManager',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=20, unique=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
