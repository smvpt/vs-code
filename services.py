from abc import ABC, abstractmethod

# АБСТРАКЦИЯ (Part 2 лабы): Базовый класс для всех уведомлений[cite: 1]
class NotificationService(ABC):
    @abstractmethod
    def send_notification(self, target_id, message):
        pass

# НАСЛЕДОВАНИЕ: Конкретная реализация для Telegram
class TelegramNotification(NotificationService):
    def __init__(self, token):
        self.__token = token  # ИНКАПСУЛЯЦИЯ: Приватный атрибут (Part 2 лабы)[cite: 1]

    def send_notification(self, target_id, message):
        import requests
        url = f"https://api.telegram.org/bot{self.__token}/sendMessage"
        payload = {"chat_id": target_id, "text": message, "parse_mode": "Markdown"}
        return requests.post(url, json=payload)