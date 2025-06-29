from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib import messages
from django.core.validators import RegexValidator

class Venue(models.Model):
    name = models.CharField(max_length=200)
    capacity = models.PositiveIntegerField(db_index=True)
    location = models.CharField(max_length=300, blank=True, help_text="General Location or Area")
    google_map_link = models.URLField(max_length=500, blank=True, help_text="Link to Google Maps location")
    latitude = models.FloatField(null=True, blank=True)  # Parsed from URL
    longitude = models.FloatField(null=True, blank=True)  # Parsed from URL

    def __str__(self):
        return self.name

    class Meta:
        indexes = [models.Index(fields=['capacity'])]

    def parse_coordinates(self):
        import re

        if self.google_map_link:
            try:
                # First, try @latitude,longitude (e.g., @27.6887106,85.2872059)
                match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', self.google_map_link)
                if match:
                    self.latitude = float(match.group(1))
                    self.longitude = float(match.group(2))
                    return
                # Fallback: try q=latitude,longitude (e.g., q=27.6887106,85.2872059)
                match = re.search(r'q=(-?\d+\.\d+),(-?\d+\.\d+)', self.google_map_link)
                if match:
                    self.latitude = float(match.group(1))
                    self.longitude = float(match.group(2))
            except Exception:
                pass

@receiver(post_save, sender=Venue)
def parse_venue_coordinates(sender, instance, created, **kwargs):
    if instance.google_map_link and (instance.latitude is None or instance.longitude is None):
        instance.parse_coordinates()
        Venue.objects.filter(pk=instance.pk).update(
            latitude=instance.latitude,
            longitude=instance.longitude
        )

class Event(models.Model):
    
    EVENT_TYPES = [
        ('sports', 'Sports'),
        ('music', 'Music'),
        ('program', 'Program'),
    ]

    EVENT_STATUS = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to='event_images/', blank=True, null=True)
    description = models.TextField()
    date = models.DateTimeField(db_index=True)
    end_date = models.DateTimeField(null=True, blank=True, help_text="End date/time of the event")
    venue = models.ForeignKey(Venue, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, default='program')
    is_highlight = models.BooleanField(default=False)
    proposed_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='proposed_events', null=True, blank=True)
    expected_attendees = models.IntegerField(default=0)
    email = models.EmailField(max_length=100, blank=True, default='')
    phone_number = models.CharField(max_length=10, blank=True, default='',validators=[RegexValidator(r'^\d{10}$', 'Enter a valid 10-digit phone number.')])
    status = models.CharField(max_length=20, choices=EVENT_STATUS, default='pending')
    rejection_reason = models.TextField(blank=True, null=True)

    def clean(self):
        if self.end_date and self.end_date < self.date:
            raise ValidationError("End date cannot be before start date.")

    def is_upcoming(self):
        return self.date >= timezone.now()
    
    def is_past(self):
        reference_time = self.end_date if self.end_date else self.date
        return reference_time < timezone.now()

    def __str__(self):
        return self.title

class VenueBooking(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="venue_bookings")
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="bookings")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    def clean(self):
        if self.end_time < self.start_time:
            raise ValidationError("End time cannot be before start time.")
        if self.event.venue and self.venue != self.event.venue:
            raise ValidationError("Booking  venue must match event venue if set")
        
    def save(self, *args, **kwargs):
        self.start_time = self.event.date
        self.end_time = self.event.end_date or self.event.date
        super().save(*args,**kwargs)

    def __str__(self):
        return f"{self.event.title} at {self.venue.name}"
    
    class Meta:
        unique_together = ('venue', 'start_time', 'end_time')
        indexes = [models.Index(fields=['venue', 'start_time', 'end_time'])]
    
class ApprovalHistory(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='approval_history')
    action_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='approval_history')
    action = models.CharField(max_length=50, choices=[('approve', 'Approve'), ('reject', 'Reject')])
    action_date = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True, null=True, help_text="Reason for approval/rejection")

    def __str__(self):
        return f"{self.event.title} - {self.action} by {self.action_by.username} on {self.action_date}"

class EventView(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='views')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_views')
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('event', 'user')

    def __str__(self):
        return f"{self.user.username} viewed {self.event.title}"

class EventParticipation(models.Model):
    STATUS = [
        ('going', 'Going'),
        ('interested', 'Interested'),
        ('not_going', 'Not Going'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='participations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='participants')
    status = models.CharField(max_length=20, choices=STATUS, default='going')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('event', 'user')

    def __str__(self):
        return f"{self.user.username} is {self.status} to {self.event.title}"

class Volunteer(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='volunteers')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='volunteering')
    hobbies_interests = models.TextField(blank=True, help_text="Your hobbies and interests")
    signup_date = models.DateTimeField(auto_now_add=True)
    is_approved = models.BooleanField(default=False)

    class Meta:
        unique_together = ('event', 'user')
    
    def __str__(self):
        return f"{self.user.username} is volunteering for {self.event.title} (Approved: {self.is_approved})"
    
    
class Rating(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='ratings')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ratings')
    score = models.IntegerField(choices=[(i, str(i)) for i in range(1,6)], help_text="Rating from 1 to 5")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together=('event', 'user')

    def __str__(self):
        return f"{self.user.username} rated {self.event.title} {self.score}/5"

class GroupChat(models.Model):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name='group_chat')
    name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = f"Chat for {self.event.title}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
class GroupChatMember(models.Model):
    group_chat = models.ForeignKey(GroupChat, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_chat_memberships')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('group_chat', 'user')

    def __str__(self):
        return f"{self.user.username} in {self.group_chat.name}"

class Message(models.Model):
    group_chat = models.ForeignKey(GroupChat, on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}: {self.content[:50]}"

class Task(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='tasks')
    volunteer = models.ForeignKey(Volunteer, on_delete=models.SET_NULL, related_name='tasks', null=True, blank=True)
    description = models.TextField()
    status = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.description} - {self.volunteer.user.username}"