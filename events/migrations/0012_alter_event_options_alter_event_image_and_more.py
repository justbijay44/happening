# Generated by Django 5.2 on 2025-05-11 08:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0011_alter_event_options_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='event',
            options={},
        ),
        migrations.AlterField(
            model_name='event',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='event_images/'),
        ),
        migrations.AlterUniqueTogether(
            name='venuebooking',
            unique_together={('venue', 'start_time', 'end_time')},
        ),
    ]
