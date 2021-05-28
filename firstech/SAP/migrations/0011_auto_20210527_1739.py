# Generated by Django 3.1.7 on 2021-05-27 17:39

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0050_auto_20210506_1058'),
        ('SAP', '0010_auto_20210518_2246'),
    ]

    operations = [
        migrations.CreateModel(
            name='BusinessPartnerAddresses',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(choices=[('billing', 'Billing'), ('shipping', 'Shipping')], default='shipping', max_length=10)),
                ('address', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='account.address')),
                ('business_partner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='SAP.businesspartner')),
            ],
        ),
        migrations.RemoveField(model_name='businesspartner', name='addresses'),
        migrations.AddField(
            model_name='businesspartner',
            name='addresses',
            field=models.ManyToManyField(blank=True, related_name='business_partner_addresses', through='SAP.BusinessPartnerAddresses', to='account.Address'),
        ),
    ]
