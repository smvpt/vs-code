import logging
import time
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class ReminderScheduler:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    def check_and_send(self):
        """Проверяет базу на наличие просроченных напоминаний и отправляет их."""
        now = datetime.now(pytz.utc)
        # Получаем все невыполненные из базы
        pending = self.db.get_all_pending() 
        
        for r in pending:
            # Превращаем строку из базы в объект даты
            remind_at = datetime.fromisoformat(r["datetime"])
            if remind_at.tzinfo is None:
                remind_at = pytz.utc.localize(remind_at)
            else:
                remind_at = remind_at.astimezone(pytz.utc)

            if remind_at <= now:
                try:
                    self.bot.send_message(
                        chat_id=r["user_id"],
                        text=f"🔔 *Напоминание!*\n\n{r['text']}",
                        parse_mode="Markdown",
                    )
                    # Помечаем в базе как отправленное
                    self.db.mark_sent(r["id"])
                    logger.info(f"Отправлено напоминание {r['id']} пользователю {r['user_id']}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке {r['id']}: {e}")

def start_scheduler(bot, db):
    """
    Та самая функция, которую вызывает bot.py в отдельном потоке.
    """
    scheduler = ReminderScheduler(bot, db)
    logger.info("Цикл планировщика запущен.")
    
    while True:
        try:
            scheduler.check_and_send()
        except Exception as e:
            logger.error(f"Критическая ошибка в цикле планировщика: {e}")
        
        # Спим 30 секунд перед следующей проверкой базы
        time.sleep(30)