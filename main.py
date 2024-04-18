import os
import telebot
from telebot import types
import logging
import time
from datetime import datetime, timedelta
import re
import sqlite3
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from flask import Flask, request

BOT_TOKEN = "7023913254:AAEh2GutePfEFXhea9zRX10uPMfdfLYshoQ"

# Создаем объект бота
bot = telebot.TeleBot(BOT_TOKEN)
server = Flask(__name__)
logger = telebot.logger
logger.setLevel(logging.DEBUG)

# Подключаемся к базе данных
conn = sqlite3.connect("bot_data.db")
cursor = conn.cursor()

# Создаем таблицу для хранения информации о пользователях
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    is_vip INTEGER DEFAULT 0,
    banned_until DATETIME,
    last_message_time DATETIME,
    last_instagram_link TEXT
)
""")
conn.commit()

# Создаем таблицу для хранения сообщений
cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    user_id INTEGER,
    message_text TEXT,
    message_time DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# Создаем таблицу для хранения ссылок
cursor.execute("""
CREATE TABLE IF NOT EXISTS links (
    user_id INTEGER,
    link TEXT,
    time_sent DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# Настройки
CHECK_INTERVAL = 60  # Интервал проверки активности в секундах
VIP_INTERVAL = 120  # Интервал для VIP пользователей
BAN_TIME = 300  # Время бана в секундах
MIN_MESSAGES_BETWEEN_LINKS = 5  # Минимальное количество сообщений между ссылками
ADMIN_LINK_INTERVAL = 10  # Интервал для ссылок админа
last_message_time = {} # Словарь для хранения времени последнего сообщения каждого пользователя
message_count = {} # Словарь для хранения количества сообщений каждого пользователя
MAX_MESSAGES = 5 # Максимальное количество сообщений, которое пользователь может отправить за интервал времени
TIME_INTERVAL = 60 # Интервал времени для проверки сообщений (в секундах)

# Регулярное выражение для проверки ссылок Instagram
INSTAGRAM_LINK_REGEX = r"https://www.instagram.com/p/[\w-]+/"

with open('admin_ids.txt', 'r') as f:
  admin_ids = [int(line.strip()) for line in f]

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url="https://my-heroku-a14c673fb233.herokuapp.com/")
    server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

@server.route('/' + BOT_TOKEN, methods=['POST'])
def get_message():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '!', 200

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if user_id in admin_ids:
        bot.send_message(user_id, "Привет, админ!")
        # Создаем клавиатуру
        markup = types.ReplyKeyboardMarkup(row_width=2)
        itembtn1 = types.KeyboardButton('Добавить ВИП участника')
        itembtn2 = types.KeyboardButton('Обновить ссылку от админа')
        markup.add(itembtn1, itembtn2)
        bot.send_message(user_id, "Выберите действие:", reply_markup=markup)

# Функция для получения информации о пользователе из базы данных
def get_user_data(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    if not user_data:
        return None
    return {
        "user_id": user_data[0],
        "username": user_data[1],
        "is_vip": bool(user_data[2]),
        "banned_until": user_data[3],
        "last_message_time": user_data[4],
        "last_instagram_link": user_data[5],
    }

# Функция для обновления информации о пользователе в базе данных
def update_user_data(user_id, data):
    cursor.execute("""
        UPDATE users SET 
        username = :username,
        is_vip = :is_vip,
        banned_until = :banned_until,
        last_message_time = :last_message_time,
        last_instagram_link = :last_instagram_link
        WHERE user_id = :user_id
    """, data)
    conn.commit()

# Функция для проверки активности пользователя в Instagram
def check_user_activity(user_id, username, chat_id, last_instagram_link):
    driver = webdriver.Firefox()
    last_six_posts = get_last_six_posts(chat_id)  # функция, которая возвращает последние 6 постов из чата
    if not check_user_activity_on_instagram(driver, username, last_six_posts, last_instagram_link):  # предполагается, что эта функция проверяет активность пользователя на Instagram
        message_id = bot.send_message(chat_id, f"@{username}, вы не выполнили задания!").message_id
        bot.delete_message(chat_id, message_id)
    driver.quit()

def check_user_activity_on_instagram(driver, username, last_six_posts, last_instagram_link):
  for post_link in last_six_posts:
      driver.get(post_link)
  
      # Ждем, пока страница загрузится
      WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "article")))
  
      # Получаем список пользователей, которые поставили лайк под постом
      likes = driver.find_elements_by_css_selector("article div a")
      likes = [like.text for like in likes]
  
      # Получаем список пользователей, которые оставили комментарий под постом
      comments = driver.find_elements_by_css_selector("article ul li a")
      comments = [comment.text for comment in comments]
  
      # Проверяем, есть ли username среди пользователей, которые поставили лайк или оставили комментарий
      if username not in likes and username not in comments:
          return False

  return True

# Словарь для хранения количества сообщений каждого пользователя
message_counts = {}

def check_message_count(user_id):
    # Получаем количество сообщений от пользователя
    message_count = message_counts.get(user_id, 0)

    # Если количество сообщений меньше минимального количества сообщений между ссылками
    if message_count < MIN_MESSAGES_BETWEEN_LINKS:
        return False

    # Сбрасываем счетчик сообщений для пользователя
    message_counts[user_id] = 0

    return True

# Обработчик новых участников
@bot.message_handler(content_types=["new_chat_members"])
def handle_new_member(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            # Бот добавлен в чат
            bot.send_message(message.chat.id, "Привет! Я бот для контроля активности в Instagram. Пожалуйста, ознакомьтесь с правилами.")
        else:
            # Новый участник
            user_id = member.id
            username = member.username
            # Добавляем пользователя в базу данных
            cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
            conn.commit()

# Функция для проверки, является ли сообщение спамом
def is_spam(user_id):
    # Получаем текущее время
    current_time = time.time()

    # Если пользователь еще не отправлял сообщений или отправлял их более минуты назад
    if user_id not in last_message_time or current_time - last_message_time[user_id] > TIME_INTERVAL:
        # Сбрасываем счетчик сообщений
        message_count[user_id] = 0
        last_message_time[user_id] = current_time

    # Увеличиваем счетчик сообщений
    message_count[user_id] += 1

    # Если пользователь отправил слишком много сообщений, считаем это спамом
    if message_count[user_id] > MAX_MESSAGES:
        return True

    return False

# Обработчик сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    username = message.from_user.username
    chat_id = message.chat.id
    user_data = get_user_data(user_id)

    # Если пользователь не найден в базе данных, прекращаем обработку сообщения
    if user_data is None:
        return

    # Проверяем, является ли сообщение спамом
    if is_spam(user_id):
        # Блокируем пользователя на определенное время
        until_date = int(time.time()) + BAN_TIME
        bot.kick_chat_member(chat_id, user_id, until_date=until_date)
        bot.send_message(chat_id, f"@{username}, вы были заблокированы за спам.")
        return

    # Проверяем, забанен ли пользователь
    if user_data.get("banned_until", datetime.now()) > datetime.now():
        return

    # Проверяем ссылку на Instagram
    if re.match(INSTAGRAM_LINK_REGEX, message.text):
      # Получаем количество ссылок, отправленных пользователем за последние 24 часа
      cursor.execute("""
          SELECT COUNT(*) FROM links
          WHERE user_id = ? AND time_sent > datetime('now', '-1 day')
      """, (user_id,))
      link_count = cursor.fetchone()[0]
  
      # Получаем максимальное количество ссылок, которое пользователь может отправить за день
      max_links_per_day = 10 if user_data.get("is_vip") else 2
  
      # Если пользователь отправил максимальное количество ссылок за последние 24 часа, удаляем сообщение
      if link_count >= max_links_per_day:
          bot.delete_message(chat_id, message.message_id)
          bot.send_message(chat_id, f"@{username}, вы можете оставить ссылку не более {max_links_per_day} раз за день.")
          return
  
      # Получаем количество сообщений, отправленных пользователем после последней ссылки
      cursor.execute("""
          SELECT COUNT(*) FROM messages
          WHERE user_id = ? AND message_time > (
              SELECT MAX(time_sent) FROM links WHERE user_id = ?
          )
      """, (user_id, user_id))
      messages_after_last_link = cursor.fetchone()[0]
  
      # Если пользователь отправил меньше 5 сообщений после последней ссылки, удаляем сообщение
      if messages_after_last_link < 5:
          bot.delete_message(chat_id, message.message_id)
          bot.send_message(chat_id, f"@{username}, вы должны отправить минимум 5 сообщений перед отправкой следующей ссылки.")
          return
  
      # Сохраняем ссылку в базе данных
      cursor.execute("INSERT INTO links (user_id, link) VALUES (?, ?)", (user_id, message.text))
      conn.commit()

# Функция для получения последних 6 сообщений
def get_last_six_posts(chat_id):
    cursor.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY message_time DESC LIMIT 6", (chat_id,))
    return cursor.fetchall()


# Команда для добавления VIP клиента
@bot.message_handler(func=lambda message: message.text == 'Добавить ВИП участника' and message.from_user.id in admin_ids)
def add_vip(message):
    user_id = message.from_user.id
    # Проверяем, является ли пользователь администратором
    if user_id in admin_ids:
        msg = bot.send_message(user_id, "Введите username пользователя, которого вы хотите сделать VIP клиентом.")
        bot.register_next_step_handler(msg, process_username_step)
    else:
        bot.send_message(user_id, "У вас нет прав на выполнение этой команды.")

def process_username_step(message):
    username = message.text
    user_id = message.from_user.id
    # Проверяем, является ли пользователь администратором
    if user_id in admin_ids:
        # Обновляем статус пользователя на VIP
        cursor.execute("UPDATE users SET is_vip = 1 WHERE username = ?", (username,))
        conn.commit()
        bot.send_message(user_id, f"Пользователь {username} теперь является VIP клиентом.")
    else:
        bot.send_message(user_id, "У вас нет прав на выполнение этой команды.")

# Обработчик команды 'Обновить ссылку от админа'
@bot.message_handler(func=lambda message: message.text == 'Обновить ссылку от админа' and message.from_user.id in admin_ids)
def update_admin_link(message):
    msg = bot.send_message(message.chat.id, "Введите новую ссылку.")
    bot.register_next_step_handler(msg, process_link_step)

def process_link_step(message):
  # Проверяем, является ли ссылка валидной
  if re.match(INSTAGRAM_LINK_REGEX, message.text):
      # Обновляем ссылку админа в базе данных
      cursor.execute("UPDATE users SET last_instagram_link = ? WHERE user_id = ?", (message.text, message.from_user.id))
      conn.commit()
      bot.send_message(message.chat.id, "Ссылка успешно обновлена.")
  else:
      bot.send_message(message.chat.id, "Введенная ссылка недействительна. Пожалуйста, попробуйте еще раз.")
  
# Запускаем бота
while True:
  try:
      bot.polling(none_stop=True)
  except Exception as e:
      print(f"Ошибка: {e}")
      time.sleep(1)
