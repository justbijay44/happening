from django.contrib import admin
from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html

from events.views import send_approval_notification
from .models import Event, Venue, EventParticipation, Volunteer, VenueBooking, Rating, Task, ApprovalHistory
from .utils import allocate_venue

admin.site.register(Task)

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'date', 'venue', 'status', 'proposed_by', 'email', 'phone_number', 'approval_link')
    list_filter = ('status', 'date', 'event_type')
    search_fields = ('title', 'description', 'proposed_by__username', 'email', 'phone_number')
    ordering = ['status', '-date']
    fields = ('title', 'image', 'description', 'date', 'end_date', 'venue', 'event_type', 'is_highlight', 'proposed_by', 'expected_attendees', 'email', 'phone_number', 'status', 'rejection_reason')
    readonly_fields = ('status', 'rejection_reason') 

    actions = ['approve_events']

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != 'pending':  # Lock fields after approval/rejection
            return [field for field in self.fields if field != 'expected_attendees'] + list(self.readonly_fields)
        return self.readonly_fields

    def approve_events(self, request, queryset):
        updated = 0
        for event in queryset:
            if event.status != 'approved': 
                event.status = 'approved'
                event.save()
                ApprovalHistory.objects.create(event=event, action_by=request.user, action='approve')
                send_approval_notification(event)
                if allocate_venue(event):
                    messages.success(request, f"Venue allocated for {event.title}.")
                else:
                    messages.warning(request, f"No suitable venue available for {event.title}.")
                updated += 1
        messages.info(request, f"{updated} event(s) approved.")

    def approval_link(self, obj):
        if obj.status == 'pending':
            url = reverse('event_approval')
            return format_html('<a href="{}" target="_blank">Manage Approvals</a>', url)
        return "N/A"
    approval_link.short_description = 'Approval UI'

@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ('name', 'capacity')
    search_fields = ('name',)

@admin.register(EventParticipation)
class EventParticipationAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'status')
    list_filter = ('status',)
    search_fields = ('user__username', 'event__title')

@admin.register(Volunteer)
class VolunteerAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'is_approved', 'signup_date')  # Added signup_date to list_display
    list_filter = ('is_approved',)
    search_fields = ('user__username', 'event__title')
    actions = ['approve_volunteers']

    def approve_volunteers(self, request, queryset):
        updated = queryset.update(is_approved=True)
        messages.success(request, f"{updated} volunteer(s) approved.")
    approve_volunteers.short_description = "Approve selected volunteers"

@admin.register(VenueBooking)
class VenueBookingAdmin(admin.ModelAdmin):
    list_display = ('event', 'venue', 'start_time', 'end_time')
    list_filter = ('start_time',)
    search_fields = ('event__title', 'venue__name')

admin.site.register(Rating)
admin.site.register(ApprovalHistory)