from django.core.management.base import BaseCommand
from chatbot.models import FAQ
import json
import os

with open(os.path.join(os.path.dirname(__file__), '..', '..', 'response.json'), 'r', encoding='utf-8') as file:
    intents = json.load(file)['intents']

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for intent in intents:
            faq_data = {
                'tag': intent['tag'],
                'question': intent['patterns'][0],
                'answer': intent['responses'][0], 
                'keywords': intent['keywords']
            }
            FAQ.objects.get_or_create(tag=faq_data['tag'], question=faq_data['question'], defaults=faq_data)
        self.stdout.write(self.style.SUCCESS("Event FAQs added successfully from response.json!"))