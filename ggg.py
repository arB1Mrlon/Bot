import telebot
from telebot.types import ChatMemberUpdated, ChatMember
import logging
from collections import defaultdict

# Конфигурация
TOKEN = "7862694945:AAEm9g5gUa5Mrhe8L-Jszst_pDBeBWtYicc"
MAX_KICKS_BEFORE_BAN = 3  # Максимальное число удалений перед баном
ADMIN_USER_IDS = [7734536630,8074015868]  # Ваш ID для доступа к командам
LOG_CHAT_ID = -100123456789  # Чат для логов ошибок (опционально)

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# База данных (в реальном проекте используйте БД)
channels = {}  # {channel_id: {"title": str, "admin_chat": int, "admins": {admin_id: int}}}

def is_bot_admin(chat_id):
    try:
        member = bot.get_chat_member(chat_id, bot.get_me().id)
        return member.status == "administrator" and member.can_restrict_members
    except Exception as e:
        logger.error(f"Ошибка проверки прав бота: {e}")
        return False

@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id not in ADMIN_USER_IDS:
        return
    
    bot.reply_to(message, 
        "👮‍♂️ <b>Бот контроля администраторов</b>\n\n"
        "Я отслеживаю действия админов в каналах и автоматически снимаю тех, кто злоупотребляет правами.\n\n"
        "<b>Основные команды:</b>\n"
        "/add_channel - добавить канал для мониторинга\n"
        "/set_notify - установить чат для уведомлений\n"
        "/check_bot - проверить права бота\n"
        "/stats - статистика удалений\n"
        "/help - справка"
    )

@bot.message_handler(commands=['add_channel'])
def add_channel(message):
    if message.from_user.id not in ADMIN_USER_IDS:
        return
    
    if message.forward_from_chat and message.forward_from_chat.type == "channel":
        channel = message.forward_from_chat
        if not is_bot_admin(channel.id):
            bot.reply_to(message, 
                "❌ Бот не является администратором в этом канале или не имеет прав на бан! "
                "Добавьте бота как администратора с правом <code>ban users</code>."
            )
            return
            
        channels[channel.id] = {
            "title": channel.title,
            "admin_chat": None,
            "admins": defaultdict(int)
        }
        bot.reply_to(message, f"✅ Канал <b>{channel.title}</b> добавлен. Теперь установите чат для уведомлений.")
    else:
        bot.reply_to(message, "❗ <b>Перешлите сообщение из нужного канала</b> или укажите его ID.")

@bot.message_handler(commands=['set_notify'])
def set_notify_chat(message):
    if message.from_user.id not in ADMIN_USER_IDS:
        return
    
    if message.forward_from_chat:
        chat = message.forward_from_chat
        for channel_id in channels:
            channels[channel_id]["admin_chat"] = chat.id
        bot.reply_to(message, f"✅ Чат <b>{chat.title}</b> установлен для уведомлений.")
    else:
        bot.reply_to(message, "❗ <b>Перешлите сообщение из чата</b> для уведомлений.")

@bot.message_handler(commands=['check_bot'])
def check_bot_rights(message):
    if message.from_user.id not in ADMIN_USER_IDS:
        return
    
    try:
        chat_id = message.chat.id
        bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
        
        if bot_member.status != "administrator":
            bot.reply_to(message, "❌ Бот не является администратором в этом чате!")
            return
            
        required_rights = {
            "can_restrict_members": "Бан пользователей",
            "can_post_messages": "Отправка сообщений",
            "can_delete_messages": "Удаление сообщений"
        }
        
        missing = [desc for right, desc in required_rights.items() if not getattr(bot_member, right, False)]
        
        if missing:
            bot.reply_to(message, f"⚠ <b>Не хватает прав:</b>\n" + "\n".join(missing))
        else:
            bot.reply_to(message, "✅ <b>Все необходимые права есть!</b>")
    except Exception as e:
        logger.error(f"Ошибка проверки прав: {e}")
        bot.reply_to(message, f"❌ <b>Ошибка:</b> {e}")

def ban_admin(channel_id, admin_id, reason):
    try:
        # Сначала снимаем права админа
        bot.promote_chat_member(
            channel_id,
            admin_id,
            can_change_info=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False
        )
        
        # Затем баним
        bot.ban_chat_member(channel_id, admin_id)
        
        # Удаляем из списка админов канала
        if channel_id in channels and admin_id in channels[channel_id]["admins"]:
            del channels[channel_id]["admins"][admin_id]
            
        return True
    except Exception as e:
        logger.error(f"Ошибка бана админа {admin_id}: {e}")
        if LOG_CHAT_ID:
            bot.send_message(
                LOG_CHAT_ID,
                f"🚨 <b>Ошибка бана админа</b>\n"
                f"Канал: {channel_id}\n"
                f"Админ: {admin_id}\n"
                f"Ошибка: {e}"
            )
        return False

@bot.chat_member_handler()
def handle_chat_member(update: ChatMemberUpdated):
    try:
        channel_id = update.chat.id
        if channel_id not in channels:
            return
            
        old_status = update.old_chat_member.status
        new_status = update.new_chat_member.status
        
        # Фиксируем только кики (не добровольные выходы)
        if old_status in ["member", "administrator"] and new_status == "kicked":
            admin = update.from_user
            user = update.new_chat_member.user
            
            # Игнорируем самоудаления и действия других ботов
            if admin.id == user.id or admin.is_bot:
                return
                
            # Увеличиваем счетчик
            channels[channel_id]["admins"][admin.id] += 1
            count = channels[channel_id]["admins"][admin.id]
            
            logger.info(f"Админ {admin.id} удалил {user.id} в {channel_id} (Всего: {count})")
            
            # Отправляем уведомление
            notify_chat = channels[channel_id]["admin_chat"]
            if notify_chat:
                try:
                    bot.send_message(
                        notify_chat,
                        f"🚨 <b>Зафиксировано удаление</b>\n"
                        f"Канал: {update.chat.title}\n"
                        f"Админ: {admin.mention} (ID: {admin.id})\n"
                        f"Удалён: {user.mention} (ID: {user.id})\n"
                        f"Всего удалений: {count}/{MAX_KICKS_BEFORE_BAN}",
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления: {e}")
            
            # Бан при превышении лимита
            if count >= MAX_KICKS_BEFORE_BAN:
                if ban_admin(channel_id, admin.id, "Превышение лимита удалений"):
                    if notify_chat:
                        bot.send_message(
                            notify_chat,
                            f"⛔ <b>Админ {admin.mention} был снят и забанен!</b>\n"
                            f"Причина: удаление {count} пользователей",
                            disable_web_page_preview=True
                        )
                    logger.warning(f"Админ {admin.id} снят и забанен в {channel_id}")
                else:
                    if notify_chat:
                        bot.send_message(
                            notify_chat,
                            f"❌ <b>Не удалось снять админа {admin.mention}!</b>\n"
                            "Проверьте права бота в канале.",
                            disable_web_page_preview=True
                        )
    except Exception as e:
        logger.error(f"Ошибка обработки обновления: {e}")
        if LOG_CHAT_ID:
            bot.send_message(LOG_CHAT_ID, f"🚨 Ошибка: {e}")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.from_user.id not in ADMIN_USER_IDS:
        return
    
    if not channels:
        bot.reply_to(message, "Нет отслеживаемых каналов")
        return
        
    stats = ["📊 <b>Статистика удалений</b>"]
    for channel_id, data in channels.items():
        stats.append(f"\n🔹 <b>{data.get('title', channel_id)}</b>")
        if not data["admins"]:
            stats.append("Нет зафиксированных удалений")
            continue
            
        for admin_id, count in data["admins"].items():
            try:
                admin = bot.get_chat_member(channel_id, admin_id).user
                name = admin.mention if admin else f"ID:{admin_id}"
            except:
                name = f"ID:{admin_id}"
            stats.append(f"👤 {name}: {count} удалений")
    
    bot.reply_to(message, "\n".join(stats), disable_web_page_preview=True)

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "🆘 <b>Помощь по боту контроля админов</b>\n\n"
        "1. Добавьте бота в канал как <b>администратора</b> (с правом бана)\n"
        "2. Перешлите сообщение из канала с командой <code>/add_channel</code>\n"
        "3. Перешлите сообщение из чата для уведомлений с <code>/set_notify</code>\n"
        "4. Проверьте права бота командой <code>/check_bot</code>\n\n"
        f"<b>Автоматический бан:</b> при {MAX_KICKS_BEFORE_BAN}+ удалениях\n"
        "<b>Логирование:</b> все действия записываются в bot.log"
    )
    bot.reply_to(message, help_text, disable_web_page_preview=True)

if __name__ == "__main__":
    logger.info("Запуск бота...")
    bot.infinity_polling(allowed_updates=["message", "chat_member"])