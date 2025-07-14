from django import forms
from .models import Event, Volunteer

class EventProposalForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'image', 'description', 'date', 'end_date', 'event_type', 'expected_attendees', 'email', 'phone_number']
        widgets = {
            'date': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'end_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'event_type': forms.Select(choices=Event.EVENT_TYPES),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('end_date') and cleaned_data.get('date') and cleaned_data['end_date'] < cleaned_data['date']:
            raise forms.ValidationError("End date cannot be before start date.")
        return cleaned_data

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

