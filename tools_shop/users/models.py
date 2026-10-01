from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    phone_number = models.CharField(
        max_length=30, default="", verbose_name="телефон для связи", blank=True
    )

    def __str__(self):
        return self.username

