from django.db import models

class FAQ(models.Model):
    tag = models.CharField(max_length=50, unique=True)
    question = models.CharField(max_length=255)
    answer = models.TextField()
    keywords = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.tag}: {self.question}"
