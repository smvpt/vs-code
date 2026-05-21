from django.contrib import admin
from .models import UserQuery
from config import BOT_TOKEN
import requests

@admin.register(UserQuery)
class UserQueryAdmin(admin.ModelAdmin):
    # 1. Настройка колонок
    # Мы убираем ID и системные имена, оставляя понятные заголовки
    list_display = ('display_username', 'display_question', 'display_date')
    
    # 2. Фильтры и поиск
    list_filter = ('created_at', 'is_answered')
    search_fields = ('username', 'question')
    
    # 3. Поля только для чтения при редактировании
    readonly_fields = ('user_id', 'username', 'question', 'created_at')

    # --- Кастомные колонки ---

    def display_username(self, obj):
        return obj.username or f"ID: {obj.user_id}"
    display_username.short_description = "Никнейм" 

    def display_question(self, obj):
        return obj.question
    display_question.short_description = "Текст запроса" 

    def display_date(self, obj):
        # Форматируем дату красиво
        return obj.created_at.strftime("%B %d, %Y, %I:%M %p")
    display_date.short_description = "Дата" 

    def save_model(self, request, obj, form, change):
        if change and obj.answer and not obj.is_answered:
            token = BOT_TOKEN
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            
            payload = {
                "chat_id": obj.user_id,
                "text": f"⚠️ *Ответ поддержки:*\n\n{obj.answer}",
                "parse_mode": "Markdown"
            }
            
            try:
                r = requests.post(url, json=payload)
                if r.status_code == 200:
                    obj.is_answered = True
            except Exception as e:
                self.message_user(request, f"Ошибка отправки: {e}", level='error')
        
        super().save_model(request, obj, form, change)