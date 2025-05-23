# Generated by Django 5.2 on 2025-05-22 02:54

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0021_alter_task_volunteer'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(
            model_name='event',
            name='is_approved',
        ),
        migrations.AddField(
            model_name='event',
            name='rejection_reason',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='event',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=20),
        ),
        migrations.CreateModel(
            name='ApprovalHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('approve', 'Approve'), ('reject', 'Reject')], max_length=50)),
                ('action_date', models.DateTimeField(auto_now_add=True)),
                ('reason', models.TextField(blank=True, help_text='Reason for approval/rejection', null=True)),
                ('action_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='approval_history', to=settings.AUTH_USER_MODEL)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='approval_history', to='events.event')),
            ],
        ),
    ]
