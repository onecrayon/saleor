# Generated by Django 3.2.6 on 2021-11-02 21:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drone', '0006_droneuserprofile_is_company_owner'),
    ]

    operations = [
        migrations.AlterField(
            model_name='droneuserprofile',
            name='is_company_owner',
            field=models.BooleanField(default=None, null=True),
        ),
    ]
