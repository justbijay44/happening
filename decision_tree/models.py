from django.db import models

class EventPredictionCount(models.Model):
    event_name = models.CharField(max_length=100, unique=True)
    count = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.event_name} - {self.count}"
