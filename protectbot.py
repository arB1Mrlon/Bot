import telebot
from telebot import types
from collections import defaultdict
import logging
import json
import os

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен вашего бота
TOKEN = '7862694945:AAEm9g5gUa5Mrhe8L-Jszst_pDBeBWtYicc'

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

# Файл для хранения настроек
CONFIG_FILE = 'bot_config.json'

# Загрузка конфигурации
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"admin_chat_id": None, "deletion_limit": 3}

# Сохранение конфигурации
def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

config = load_config()

# Словарь для отслеживания количества удалений каждого администратора
admin_deletion_counts = defaultdict(int)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Обработчик команды /start"""
    bot.reply_to(message, "👮‍♂️ Бот для защиты активирован.\n"
                         "Используйте /set_admin_chat чтобы установить чат для логов.\n"
                         "Используйте /set_limit чтобы изменить лимит удалений (по умолчанию 3).")

@bot.message_handler(commands=['set_admin_chat'])
def set_admin_chat(message):
    """Установка чата для логов администраторов"""
    if message.chat.type in ['group', 'supergroup']:
        config['admin_chat_id'] = message.chat.id
        save_config(config)
        bot.reply_to(message, f"✅ Этот чат теперь используется для логов администраторов. ID: {message.chat.id}")
        log_to_admin_chat(f"📌 Этот чат теперь используется для логов о действиях администраторов.")
    else:
        bot.reply_to(message, "❌ Эта команда работает только в группах и супергруппах.")

@bot.message_handler(commands=['set_limit'])
def set_limit(message):
    """Установка лимита удалений перед разжалованием"""
    try:
        # Получаем число из аргументов команды
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "❌ Укажите лимит удалений. Пример: /set_limit 3")
            return
        
        new_limit = int(args[1])
        if new_limit < 1:
            bot.reply_to(message, "❌ Лимит должен быть положительным числом.")
            return
        
        config['deletion_limit'] = new_limit
        save_config(config)
        bot.reply_to(message, f"✅ Лимит удалений перед разжалованием установлен: {new_limit}")
        log_to_admin_chat(f"♻️ Лимит удалений изменён на {new_limit}")
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат числа. Пример: /set_limit 3")

def log_to_admin_chat(text):
    """Отправка сообщения в чат администраторов"""
    if config.get('admin_chat_id'):
        try:
            bot.send_message(config['admin_chat_id'], text)
        except Exception as e:
            logger.error(f"Ошибка при отправке лога: {e}")

@bot.message_handler(content_types=['left_chat_member'])
def track_deletions(message):
    """Отслеживание удалений участников"""
    try:
        # Проверяем, что сообщение об удалении пришло из группы/канала
        if message.chat.type not in ['group', 'supergroup']:
            return

        # Получаем информацию об удаленном пользователе и администраторе
        deleted_user = message.left_chat_member
        deleting_admin = message.from_user

        # Пропускаем, если пользователь вышел сам
        if deleting_admin.id == deleted_user.id:
            return

        # Получаем информацию об администраторе
        admin_info = bot.get_chat_member(message.chat.id, deleting_admin.id)

        # Проверяем, является ли отправитель администратором
        if admin_info.status in ['administrator', 'creator']:
            # Увеличиваем счетчик удалений для этого администратора
            admin_deletion_counts[deleting_admin.id] += 1
            
            log_text = (
                f"⚠️ Админ <a href='tg://user?id={deleting_admin.id}'>{deleting_admin.full_name}</a> "
                f"удалил пользователя <a href='tg://user?id={deleted_user.id}'>{deleted_user.full_name}</a>.\n"
                f"📊 Всего удалений: {admin_deletion_counts[deleting_admin.id]}/{config['deletion_limit']}\n"
                f"💬 Чат: {message.chat.title}"
            )
            logger.info(log_text)
            log_to_admin_chat(log_text)

            # Если администратор достиг лимита удалений
            if admin_deletion_counts[deleting_admin.id] >= config['deletion_limit']:
                try:
                    # Разжалование администратора (если он не создатель чата)
                    if admin_info.status == 'administrator':
                        bot.promote_chat_member(
                            chat_id=message.chat.id,
                            user_id=deleting_admin.id,
                            can_change_info=False,
                            can_post_messages=False,
                            can_edit_messages=False,
                            can_delete_messages=False,
                            can_invite_users=False,
                            can_restrict_members=False,
                            can_pin_messages=False,
                            can_promote_members=False,
                            can_manage_chat=False,
                            can_manage_video_chats=False,
                            can_manage_topics=False
                        )
                        action_text = (
                            f"🚨 Администратор <a href='tg://user?id={deleting_admin.id}'>{deleting_admin.full_name}</a> "
                            f"был разжалован за удаление {admin_deletion_counts[deleting_admin.id]} участников.\n"
                            f"💬 Чат: {message.chat.title}"
                        )
                        bot.send_message(message.chat.id, action_text, parse_mode='HTML')
                        log_to_admin_chat(action_text)
                    else:
                        action_text = (
                            f"⚠️ Создатель чата <a href='tg://user?id={deleting_admin.id}'>{deleting_admin.full_name}</a> "
                            f"удалил {admin_deletion_counts[deleting_admin.id]} участников, "
                            f"но я не могу разжаловать создателя.\n"
                            f"💬 Чат: {message.chat.title}"
                        )
                        log_to_admin_chat(action_text)

                    # Сбрасываем счетчик после разжалования
                    admin_deletion_counts[deleting_admin.id] = 0
                except Exception as e:
                    error_text = f"❌ Ошибка при разжаловании администратора: {e}"
                    logger.error(error_text)
                    bot.send_message(message.chat.id, error_text)
                    log_to_admin_chat(error_text)

    except Exception as e:
        error_text = f"❌ Ошибка в обработчике track_deletions: {e}"
        logger.error(error_text)
        log_to_admin_chat(error_text)

if __name__ == '__main__':
    logger.info("Бот запущен и работает...")
    bot.infinity_polling()