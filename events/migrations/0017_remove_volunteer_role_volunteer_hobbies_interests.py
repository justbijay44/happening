# Generated by Django 5.2 on 2025-05-14 10:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0016_alter_event_phone_number'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='volunteer',
            name='role',
        ),
        migrations.AddField(
            model_name='volunteer',
            name='hobbies_interests',
            field=models.TextField(blank=True, help_text='Your hobbies and interests'),
        ),
    ]
