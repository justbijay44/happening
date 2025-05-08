from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Venue(models.Model):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300)
    capacity = models.IntegerField()

    def __str__(self):
        return self.name

class Event(models.Model):

    EVENT_TYPES = [
        ('sports', 'Sports'),
        ('music', 'Music'),
        ('program', 'Program'),
    ]

    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to='event_images/', blank=True, null=True)
    description = models.TextField()
    date = models.DateTimeField()
    location = models.CharField(max_length=200)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='events')
    category = models.CharField(max_length=50, blank=True, null=True)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, default='program')
    is_approved = models.BooleanField(default=False)
    is_highlight =models.BooleanField(default=False)
    proposed_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='proposed_events', null=True, blank=True)

    email = models.EmailField(max_length=100, blank=True, null=True)
    phone_number = models.CharField(max_length=10, blank=True, null=True)

    def is_upcoming(self):
        return self.date >= timezone.now().date()

    def __str__(self):
        return self.title
