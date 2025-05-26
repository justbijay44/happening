from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from django.conf import settings

from .models import Venue, VenueBooking, Event, EventParticipation, Task

from math import radians, sin, cos, sqrt, atan2

# ACEM College coordinates
COLLEGE_LATITUDE = 27.6887106
COLLEGE_LONGITUDE = 85.2897808

DEFAULT_EVENT_DURATION = getattr(settings, 'DEFAULT_EVENT_DURATION', 4)  # Hours

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points using the Haversine formula (in km)."""
    R = 6371  # Earth's radius in km
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def allocate_venue(event):
    start_time = event.date
    end_time = event.end_date or event.date + timedelta(hours=DEFAULT_EVENT_DURATION)

    # Clear existing bookings to avoid duplicates
    VenueBooking.objects.filter(event=event).delete()

    # Validate or handle manual venue assignment
    if event.venue and event.venue.capacity < event.expected_attendees:
        event.venue = None  # Clear invalid manual assignment
        event.save(update_fields=['venue'])

    # Check manual assignment (if set and sufficient capacity)
    if event.venue:
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

    # Automatic allocation (greedy: optimize for capacity and distance)
    suitable_venues = Venue.objects.filter(
        capacity__gte=event.expected_attendees
    ).order_by('capacity')  # Start with smallest suitable capacity

    best_venue = None
    best_score = float('inf')

    for venue in suitable_venues:
        # Check if venue is available (no overlapping bookings)
        conflicts = VenueBooking.objects.filter(
            venue=venue,
            start_time__lt=end_time,
            end_time__gt=start_time
        )
        if conflicts.exists() or not venue.latitude or not venue.longitude:
            continue

        # Calculate distance from college
        distance = calculate_distance(COLLEGE_LATITUDE, COLLEGE_LONGITUDE, venue.latitude, venue.longitude)

        # Calculate score
        capacity_diff = venue.capacity - event.expected_attendees
        score = (capacity_diff * 100) + (distance * 5)  # Prioritize capacity, then distance

        if score < best_score:
            best_score = score
            best_venue = venue

    if best_venue:
        # Create a booking
        booking = VenueBooking(
            event=event,
            venue=best_venue,
            start_time=start_time,
            end_time=end_time
        )
        booking.save()
        event.venue = best_venue
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
    Store previous values to detect changes in expected_attendees, date, end_date, or venue.
    """
    if instance.pk:
        try:
            previous = Event.objects.get(pk=instance.pk)
            instance._previous_attendees = previous.expected_attendees
            instance._previous_date = previous.date
            instance._previous_end_date = previous.end_date
            instance._previous_status = previous.status
            instance._previous_venue = previous.venue
        except Event.DoesNotExist:
            instance._previous_attendees = None
            instance._previous_date = None
            instance._previous_end_date = None
            instance._previous_status = None
            instance._previous_venue = None
    else:
        instance._previous_attendees = None
        instance._previous_date = None
        instance._previous_end_date = None
        instance._previous_status = None
        instance._previous_venue = None

@receiver(post_save, sender=Event)
def allocate_venue_on_approval_or_update(sender, instance, created, **kwargs):
    """
    Trigger venue allocation:
    - On creation by superuser (auto-approve).
    - On approval for regular users.
    - On changes to expected_attendees, date, end_date, or venue if approved.
    """
    # Auto-approve for superusers on creation
    if created and instance.proposed_by and instance.proposed_by.is_superuser:
        if not instance.status:
            instance.status = 'approved'  # Match EVENT_STATUS choices
            instance.save(update_fields=['status'])
        allocate_venue(instance)
        return

    # Check for approval change or relevant field changes
    fields_changed = (
        instance._previous_attendees != instance.expected_attendees or
        instance._previous_date != instance.date or
        instance._previous_end_date != instance.end_date or
        instance._previous_venue != instance.venue
    )
    approval_changed = (
        instance._previous_status == 'pending' and instance.status == 'approved'
    )

    if instance.status == 'approved' and (created or approval_changed or fields_changed):
        allocate_venue(instance)

# Union-Find for Kruskal's MST
class UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, x):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1

def suggest_task_assignments(volunteers, tasks, event):
    if not volunteers or not tasks:
        return {}

    volunteer_list = list(volunteers)
    n = len(volunteer_list)
    edges = []

    # Compute communication cost based on participation frequency
    for i in range(n):
        for j in range(i + 1, n):
            vol1, vol2 = volunteer_list[i], volunteer_list[j]
            vol1_participation = EventParticipation.objects.filter(user=vol1.user).count()
            vol2_participation = EventParticipation.objects.filter(user=vol2.user).count()
            cost = 1 if vol1_participation > 5 and vol2_participation > 5 else (2 if vol1_participation > 5 or vol2_participation > 5 else 3)
            edges.append((cost, i, j))

    # Kruskal's MST
    edges.sort()
    uf = UnionFind(n)
    mst = []
    for cost, u, v in edges:
        if uf.find(u) != uf.find(v):
            uf.union(u, v)
            mst.append((u, v))

    # Compute workload and suggest assignments for unassigned tasks only
    workload = {vol.id: Task.objects.filter(volunteer=vol, event=vol.event, status=False).count() for vol in volunteer_list}
    suggestions = {}
    # Filter unassigned tasks
    unassigned_tasks = [task for task in Task.objects.filter(event=event) if not task.volunteer]
    unassigned_descriptions = [task.description for task in unassigned_tasks]

    for task_desc in unassigned_descriptions:
        min_workload = float('inf')
        suggested_volunteer = None
        for i, vol in enumerate(volunteer_list):
            current_workload = workload.get(vol.id, 0)
            if current_workload < min_workload:
                min_workload = current_workload
                suggested_volunteer = vol
        if suggested_volunteer:
            suggestions[task_desc] = suggested_volunteer
            workload[suggested_volunteer.id] = workload.get(suggested_volunteer.id, 0) + 1

    return suggestions