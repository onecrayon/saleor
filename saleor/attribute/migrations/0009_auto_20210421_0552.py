# Generated by Django 3.1.8 on 2021-04-21 05:52

from django.db import migrations


def clear_assignment_instances_without_values(apps, schema_editor):
    AssignedProductAttribute = apps.get_model("attribute", "AssignedProductAttribute")
    AssignedVariantAttribute = apps.get_model("attribute", "AssignedVariantAttribute")
    AssignedPageAttribute = apps.get_model("attribute", "AssignedPageAttribute")

    for model in [
        AssignedProductAttribute,
        AssignedVariantAttribute,
        AssignedPageAttribute,
    ]:
        model.objects.filter(values__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("attribute", "0008_auto_20210407_0632"),
    ]

    operations = [
        migrations.RunPython(
            clear_assignment_instances_without_values,
            migrations.RunPython.noop,
        ),
    ]
