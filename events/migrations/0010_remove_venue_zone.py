# Generated by Django 5.2 on 2025-05-11 07:52

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0009_remove_event_full_address_remove_event_latitude_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='venue',
            name='zone',
        ),
    ]
