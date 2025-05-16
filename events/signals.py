from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Volunteer, GroupChat, GroupChatMember

@receiver(post_save, sender=Volunteer)
def add_volunteer_to_group_chat(sender, instance, **kwargs):
    if instance.is_approved:
        event = instance.event
        user = instance.user
        group_chat, created = GroupChat.objects.get_or_create(event=event)
        GroupChatMember.objects.get_or_create(group_chat=group_chat, user=event.proposed_by)
        GroupChatMember.objects.get_or_create(group_chat=group_chat, user=user)