from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from .models import Venue, VenueBooking, Event

DEFAULT_EVENT_DURATION = getattr(settings, 'DEFAULT_EVENT_DURATION', 4)  # Hours

def allocate_venue(event):
    """
    Allocate a venue for the event. If event.venue is set and has sufficient capacity, use it if available.
    Otherwise, use greedy algorithm to select the smallest suitable venue.
    Returns True if allocation succeeds, False otherwise.
    """
    start_time = event.date
    end_time = event.end_date or event.date + timedelta(hours=DEFAULT_EVENT_DURATION)

    # Clear existing bookings to avoid duplicates
    VenueBooking.objects.filter(event=event).delete()

    # Check manual assignment (if set and sufficient capacity)
    if event.venue and event.venue.capacity >= event.expected_attendees:
        conflicts = VenueBooking.objects.filter(
            venue=event.venue,
            start_time__lt=end_time,
            end_time__gt=start_time
        )
        if not conflicts.exists():
            VenueBooking.objects.create(
                event=event,
                venue=event.venue,
                start_time=start_time,
                end_time=end_time
            )
            return True
        # Manual venue unavailable; proceed to automatic allocation

    # Automatic allocation (greedy: smallest suitable venue)
    suitable_venues = Venue.objects.filter(
        capacity__gte=event.expected_attendees
    ).order_by('capacity')

    for venue in suitable_venues:
        conflicts = VenueBooking.objects.filter(
            venue=venue,
            start_time__lt=end_time,
            end_time__gt=start_time
        )
        if not conflicts.exists():
            VenueBooking.objects.create(
                event=event,
                venue=venue,
                start_time=start_time,
                end_time=end_time
            )
            event.venue = venue
            event.save(update_fields=['venue'])
            return True

    # No suitable venue; clear event.venue
    if event.venue:
        event.venue = None
        event.save(update_fields=['venue'])
    return False

@receiver(pre_save, sender=Event)
def store_previous_state(sender, instance, **kwargs):
    """
    Store previous values to detect changes in expected_attendees, date, or end_date.
    """
    if instance.pk:
        try:
            previous = Event.objects.get(pk=instance.pk)
            instance._previous_attendees = previous.expected_attendees
            instance._previous_date = previous.date
            instance._previous_end_date = previous.end_date
            instance._previous_approved = previous.is_approved
        except Event.DoesNotExist:
            instance._previous_attendees = None
            instance._previous_date = None
            instance._previous_end_date = None
            instance._previous_approved = None
    else:
        instance._previous_attendees = None
        instance._previous_date = None
        instance._previous_end_date = None
        instance._previous_approved = None

@receiver(post_save, sender=Event)
def allocate_venue_on_approval_or_update(sender, instance, created, **kwargs):
    """
    Trigger venue allocation:
    - On creation by superuser (auto-approve).
    - On approval for regular users.
    - On changes to expected_attendees, date, or end_date if approved.
    """
    # Auto-approve for superusers on creation
    if created and instance.proposed_by and instance.proposed_by.is_superuser:
        if not instance.is_approved:
            instance.is_approved = True
            instance.save(update_fields=['is_approved'])
        allocate_venue(instance)
        return

    # Check for approval change or relevant field changes
    fields_changed = (
        instance._previous_attendees != instance.expected_attendees or
        instance._previous_date != instance.date or
        instance._previous_end_date != instance.end_date
    )
    approval_changed = (
        instance._previous_approved is False and instance.is_approved is True
    )

    if instance.is_approved and (created or approval_changed or fields_changed):
        allocate_venue(instance)