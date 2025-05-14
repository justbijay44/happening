from django import forms
from .models import Event, Volunteer

class EventProposalForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'image', 'description', 'date', 'expected_attendees','event_type']
        widgets = {
            'date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    email = forms.EmailField(required=False, label='Email')
    phone_number = forms.CharField(max_length=10, required=False, label='Phone Number')

class VolunteerForm(forms.ModelForm):
    class Meta:
        model = Volunteer
        fields = ['hobbies_interests']
        widgets = {
            'hobbies_interests': forms.Textarea(attrs={
                'class': 'w-full p-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-600',
                'rows': 4,
                'required': 'required',
                'placeholder': 'Tell us about your hobbies and interests (e.g., I love music, playing soccer, and organizing events)!'
            }),
        }

