import requests
from bs4 import BeautifulSoup
import time

def get_exchange_rates():
    """Извлекает курс валют из таблицы (похоже на Вариант 8/21)[cite: 5]."""
    url = 'https://www.cbr.ru/eng/currency_base/daily/'
    
    try:
        time.sleep(1) # Соблюдаем вежливую паузу (требования лабы)[cite: 5]
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Поиск данных в таблице (find_all)[cite: 5]
        table = soup.find('table', {'class': 'data'})
        rows = table.find_all('tr')
        
        rates = {}
        for row in rows[1:]: # Пропускаем заголовок
            cols = row.find_all('td')
            char_code = cols[1].text
            value = cols[4].text
            if char_code in ['USD', 'EUR']:
                rates[char_code] = value
        return rates
    except Exception as e:
        return f"Ошибка парсинга: {e}"