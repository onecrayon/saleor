# Generated by Django 3.2.6 on 2021-09-07 17:44

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('SAP', '0018_sapcreditmemo_sapcreditmemoline'),
    ]

    operations = [
        migrations.RenameField(
            model_name='sapcreditmemoline',
            old_name='product_variant',
            new_name='variant',
        ),
        migrations.RenameField(
            model_name='sapreturnline',
            old_name='product_variant',
            new_name='variant',
        ),
    ]