# Generated by Django 3.1.5 on 2021-03-16 23:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drone', '0002_droneuserprofile_update_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='droneuserprofile',
            name='dealer_id',
            field=models.IntegerField(null=True, unique=True),
        ),
        migrations.AddField(
            model_name='droneuserprofile',
            name='dealer_retired_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='droneuserprofile',
            name='installer_id',
            field=models.IntegerField(null=True, unique=True),
        ),
    ]