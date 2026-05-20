from django.db import models

class UserQuery(models.Model):
    user_id = models.BigIntegerField("ID пользователя")
    username = models.CharField("Никнейм", max_length=150, blank=True, null=True)
    question = models.TextField("Запрос пользователя")
    answer = models.TextField("Ответ поддержки", blank=True, null=True)
    is_answered = models.BooleanField("Статус ответа", default=False)
    created_at = models.DateTimeField("Дата запроса", auto_now_add=True)

    class Meta:
        verbose_name = "Запрос пользователя"
        verbose_name_plural = "История запросов"

    def __str__(self):
        return f"Запрос от {self.user_id} ({self.created_at.strftime('%d.%m %H:%M')})"