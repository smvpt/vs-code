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
        """Checks the database for overdue reminders and sends them."""
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
                    # Перевели текст уведомления на английский
                    self.bot.send_message(
                        chat_id=r["user_id"],
                        text=f"🔔 *Reminder!*\n\n{r['text']}",
                        parse_mode="Markdown",
                    )
                    # Помечаем в базе как отправленное
                    self.db.mark_sent(r["id"])
                    logger.info(f"Sent reminder {r['id']} to user {r['user_id']}")
                except Exception as e:
                    logger.error(f"Error sending reminder {r['id']}: {e}")

def start_scheduler(bot, db):
    """
    The function called by bot.py in a separate thread.
    """
    scheduler = ReminderScheduler(bot, db)
    logger.info("Scheduler loop started.")
    
    while True:
        try:
            scheduler.check_and_send()
        except Exception as e:
            logger.error(f"Critical error in scheduler loop: {e}")
        