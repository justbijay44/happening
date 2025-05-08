from django import forms
from .models import Event

class EventProposalForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'image', 'description', 'date', 'location', 'venue', 'category', 'event_type']
        widgets = {
            'date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    # These fields are optional for admin/staff users
    email = forms.EmailField(required=False, label='Email')
    phone_number = forms.CharField(max_length=10, required=False, label='Phone Number')

