from django import forms

class EventQuizForm(forms.Form):
    DEPARTMENT_CHOICES = [
        ('BCA', 'BCA'),
        ('BCE', 'BCE'),
        ('BCT', 'BCT'),
        ('BEI', 'BEI'),
        ('BEL', 'BEL'),
    ]

    EVENT_TYPES = [
        ('Guest Lecture', 'Guest Lecture'),
        ('Hackathon', 'Hackathon'),
        ('Seminar', 'Seminar'),
        ('Social', 'Social'),
        ('Workshop', 'Workshop')
    ]

    TIME_PREFERENCES = [
        ('Morning', 'Morning'),
        ('Afternoon', 'Afternoon'),
        ('Evening', 'Evening')
    ]

    FORMATS = [
        ('Hybrid', 'Hybrid'),
        ('In-Person', 'In-Person'),
        ('Virtual', 'Virtual')
    ]

    INTERESTS = [
        ('Career Development', 'Career Development'),
        ('Fun', 'Fun'),
        ('Inspiration', 'Inspiration'),
        ('Networking', 'Networking'),
        ('Skill-Building', 'Skill-Building')
    ]

    # ✅ ADD THIS FIELD
    department = forms.ChoiceField(choices=DEPARTMENT_CHOICES, label='Department')

    event_type = forms.ChoiceField(choices=EVENT_TYPES, widget=forms.RadioSelect)
    time_preference = forms.ChoiceField(choices=TIME_PREFERENCES, widget=forms.RadioSelect)
    format = forms.ChoiceField(choices=FORMATS, widget=forms.RadioSelect)
    interest = forms.ChoiceField(choices=INTERESTS, widget=forms.RadioSelect)
