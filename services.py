from abc import ABC, abstractmethod

# АБСТРАКЦИЯ (): Базовый класс для всех уведомлений
class NotificationService(ABC):
    @abstractmethod
    def send_notification(self, target_id, message):
        pass

# НАСЛЕДОВАНИЕ: Конкретная реализация для Telegram
class TelegramNotification(NotificationService):
    def __init__(self, token):
        self.__token = token  # ИНКАПСУЛЯЦИЯ: Приватный атрибут 

    def send_notification(self, target_id, message):
        import requests
        url = f"https://api.telegram.org/bot{self.__token}/sendMessage"
        payload = {"chat_id": target_id, "text": message, "parse_mode": "Markdown"}
        return requests.post(url, json=payload)