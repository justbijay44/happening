import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
import pytz
from .models import GroupChat, Message, GroupChatMember

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        self.chat_group_name = f'chat_{self.chat_id}'
        self.user = self.scope['user']

        if not await self.is_member():
            await self.close()
            return

        await self.channel_layer.group_add(
            self.chat_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.chat_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message_content = text_data_json['message']

        message = await self.save_message(message_content)

        # Convert UTC to Nepal time
        nepal_tz = pytz.timezone('Asia/Kathmandu')
        local_time = message.created_at.astimezone(nepal_tz)

        await self.channel_layer.group_send(
            self.chat_group_name,
            {
                'type': 'chat_message',
                'message': message_content,
                'username': self.user.username,
                'created_at': local_time.strftime('%Y-%m-%d %H:%M:%S'),  # Now in local time
            }
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'message': event['message'],
            'username': event['username'],
            'created_at': event['created_at'],
        }))

    @database_sync_to_async
    def is_member(self):
        return GroupChatMember.objects.filter(
            group_chat_id=self.chat_id,
            user=self.user
        ).exists()

    @database_sync_to_async
    def save_message(self, message_content):
        group_chat = GroupChat.objects.get(id=self.chat_id)
        return Message.objects.create(
            group_chat=group_chat,
            user=self.user,
            content=message_content
        )