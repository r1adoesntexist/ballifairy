import telebot
from telebot import types
import sqlite3
from datetime import datetime
import html
import re
import os
from pathlib import Path

TOKEN = os.environ.get('TOKEN')

if not TOKEN:
    raise ValueError("Токен не найден! Проверьте переменную окружения TOKEN")

bot = telebot.TeleBot(TOKEN)

DB_PATH = os.path.join(os.path.dirname(__file__), 'points.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  last_name TEXT,
                  points REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  admin_id INTEGER,
                  admin_name TEXT,
                  user_id INTEGER,
                  user_name TEXT,
                  points_change REAL,
                  reason TEXT,
                  timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY,
                  value TEXT)''')
    conn.commit()
    conn.close()

def escape_markdown(text):
    if not text:
        return ""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def get_norm():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'norm'")
    result = c.fetchone()
    conn.close()
    return float(result[0]) if result else 0

def set_norm(norm_value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
              ('norm', str(norm_value)))
    conn.commit()
    conn.close()

def is_chat_admin(chat_id, user_id):
    try:
        chat_member = bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except:
        return False

def is_bot(user):
    return hasattr(user, 'is_bot') and user.is_bot

def extract_identifiers_from_text(text):
    if not text:
        return []
    
    words = text.split()
    identifiers = []
    
    for word in words:
        clean_word = word.strip('.,!?;:()[]{}"\'')
        
        if clean_word.startswith('@'):
            identifiers.append(clean_word)
        elif clean_word.replace('.', '').replace('-', '').isdigit():
            if len(clean_word) < 15:  # IDs обычно не длиннее 14 цифр
                identifiers.append(clean_word)
    
    return identifiers

def get_user_by_identifier(chat_id, identifier):
    clean_id = str(identifier).strip()
    
    if clean_id.replace('.', '').replace('-', '').isdigit():
        try:
            user_id = int(float(clean_id))
            try:
                chat_member = bot.get_chat_member(chat_id, user_id)
                if not is_bot(chat_member.user):
                    return user_id
            except:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
                result = c.fetchone()
                conn.close()
                if result:
                    return user_id
        except:
            pass
        return None
    
    if clean_id.startswith('@'):
        username = clean_id[1:].lower()
        try:
            chat_member = bot.get_chat_member(chat_id, clean_id)
            if not is_bot(chat_member.user):
                return chat_member.user.id
        except:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id FROM users WHERE LOWER(username) = ?", (username,))
            result = c.fetchone()
            conn.close()
            if result:
                return result[0]
    
    return None

def update_user(user_id, username=None, first_name=None, last_name=None, is_bot_user=False):
    if is_bot_user:
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    current_points = result[0] if result else 0
    
    c.execute('''INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, points)
                 VALUES (?, ?, ?, ?, ?)''',
                 (user_id, username, first_name, last_name, current_points))
    
    conn.commit()
    conn.close()

def change_points(user_id, points_change, reason="", admin_id=None, admin_name=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''UPDATE users 
                 SET points = points + ? 
                 WHERE user_id = ?''', (points_change, user_id))
    
    c.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
    new_points = c.fetchone()
    
    c.execute('SELECT username, first_name, last_name FROM users WHERE user_id = ?', (user_id,))
    user_data = c.fetchone()
    if user_data:
        username, first_name, last_name = user_data
        user_name = format_user_name(user_id, username, first_name, last_name)
    else:
        user_name = f"ID: {user_id}"
    
    if reason or points_change != 0:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute('''INSERT INTO history (admin_id, admin_name, user_id, user_name, points_change, reason, timestamp)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                     (admin_id, admin_name, user_id, user_name, points_change, reason, timestamp))
    
    conn.commit()
    conn.close()
    
    return new_points[0] if new_points else None

def change_points_multiple(user_ids, points_change, reason="", admin_id=None, admin_name=""):
    results = []
    for user_id in user_ids:
        try:
            new_points = change_points(user_id, points_change, reason, admin_id, admin_name)
            results.append((user_id, new_points, True))
        except Exception as e:
            results.append((user_id, None, False))
    return results

def get_user_points(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    
    conn.close()
    return result[0] if result else 0

def get_all_users_points():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''SELECT user_id, username, first_name, last_name, points 
                 FROM users 
                 ORDER BY points DESC''')
    
    users = c.fetchall()
    conn.close()
    return users

def get_user_history(user_id, limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''SELECT admin_name, points_change, reason, timestamp 
                 FROM history 
                 WHERE user_id = ? 
                 ORDER BY timestamp DESC 
                 LIMIT ?''', (user_id, limit))
    
    history = c.fetchall()
    conn.close()
    return history

def reset_all_points():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('UPDATE users SET points = 0')
    c.execute('DELETE FROM history')
    
    conn.commit()
    conn.close()

def format_user_name(user_id, username, first_name, last_name):
    if username:
        return f"@{username}"
    elif first_name:
        return f"{first_name} {last_name or ''}".strip()
    else:
        return f"ID: {user_id}"

def get_user_display_name(user_id, chat_id=None):
    try:
        if chat_id:
            chat_member = bot.get_chat_member(chat_id, user_id)
            user = chat_member.user
            if user.username:
                return f"@{user.username}"
            else:
                return f"{user.first_name or ''} {user.last_name or ''}".strip()
    except:
        pass
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username, first_name, last_name FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        username, first_name, last_name = result
        return format_user_name(user_id, username, first_name, last_name)
    
    return f"ID: {user_id}"

@bot.message_handler(commands=['start'])
def start(message):
    if not is_bot(message.from_user):
        update_user(message.from_user.id, 
                   message.from_user.username,
                   message.from_user.first_name,
                   message.from_user.last_name)
    
    bot.reply_to(message, 
                 "👋 Добро пожаловать в бот для учёта баллов!\n\n"
                 "📝 **Доступные команды:**\n\n"
                 "👤 **Для всех пользователей:**\n"
                 "`.баллы` - показать ваши текущие баллы\n"
                 "`.история` - показать историю ваших транзакций\n\n"
                 "👑 **Для администраторов:**\n"
                 "• `+баллы [число] [причина]` - добавить баллы (ответом на сообщение)\n"
                 "• `-баллы [число] [причина]` - отнять баллы (ответом на сообщение)\n"
                 "• `+баллы @username [число] [причина]` - добавить баллы по username\n"
                 "• `-баллы 123456789 [число] [причина]` - отнять баллы по ID\n"
                 "• `+мбаллы [число] [причина]` - добавить баллы нескольким пользователям (ответом на сообщение с ID/username)\n"
                 "• `-мбаллы [число] [причина]` - отнять баллы у нескольких пользователей (ответом на сообщение с ID/username)\n"
                 "• `.баллывсе` - показать баллы всех пользователей\n"
                 "• `.норма [число]` - установить норму баллов для этапа\n"
                 "• `новый_этап` - сбросить все баллы и показать не выполнивших норму\n\n"
                 "📌 **Примеры массового начисления:**\n"
                 "• Ответьте на сообщение с текстом `@user1 12345 @user2` и напишите: `+мбаллы 5 За активность`\n"
                 "• Ответьте на сообщение с ID пользователей: `+мбаллы 3`\n"
                 "• ID в сообщении могут быть в любом формате: `12345 @user1 67890 @user2`")

@bot.message_handler(commands=['баллы'])
@bot.message_handler(func=lambda message: message.text == '.баллы')
def show_my_points(message):
    points = get_user_points(message.from_user.id)
    
    if message.from_user.username:
        user_display = f"@{message.from_user.username}"
    else:
        user_display = message.from_user.first_name
    
    user_display = escape_markdown(user_display)
    
    keyboard = types.InlineKeyboardMarkup()
    history_button = types.InlineKeyboardButton("📜 История операций", callback_data=f"history_{message.from_user.id}")
    keyboard.add(history_button)
    
    response = f"👤 **{user_display}**, ваш текущий баланс: **{points}** баллов"
    
    bot.reply_to(message, response, parse_mode='Markdown', reply_markup=keyboard)

@bot.message_handler(commands=['история'])
@bot.message_handler(func=lambda message: message.text == '.история')
def show_history(message):
    show_user_history(message, message.from_user.id)

def show_user_history(message, user_id):
    history = get_user_history(user_id)
    
    if not history:
        bot.reply_to(message, "📜 У вас пока нет истории операций")
        return
    
    response = f"📜 **История операций**\n\n"
    
    for admin_name, points_change, reason, timestamp in history:
        action = "✅ +" if points_change > 0 else "❌ "
        response += f"{action}{abs(points_change)} баллов"
        if reason:
            reason = escape_markdown(reason)
            response += f" ({reason})"
        admin_name = escape_markdown(admin_name)
        response += f"\n👑 Админ: {admin_name}"
        response += f"\n🕐 {timestamp}\n\n"
    
    bot.reply_to(message, response, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('history_'))
def history_callback(call):
    user_id = int(call.data.split('_')[1])
    show_user_history(call.message, user_id)
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['баллывсе'])
@bot.message_handler(func=lambda message: message.text == '.баллывсе')
def show_all_points(message):
    if message.chat.type == 'private':
        bot.reply_to(message, "❌ Эта команда работает только в групповых чатах!")
        return
    
    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Только администраторы могут просматривать баллы всех пользователей!")
        return
    
    users = get_all_users_points()
    
    if not users:
        bot.reply_to(message, "📊 Пока нет пользователей с баллами")
        return
    
    response = "📊 **Все пользователи по баллам:**\n\n"
    
    for user_id, username, first_name, last_name, points in users:
        name_display = format_user_name(user_id, username, first_name, last_name)
        name_display = escape_markdown(name_display)
        response += f"• {name_display}: **{points}** баллов\n"
    
    bot.reply_to(message, response, parse_mode='Markdown')

@bot.message_handler(commands=['норма'])
@bot.message_handler(func=lambda message: message.text.startswith('.норма'))
def set_norm_command(message):
    if message.chat.type == 'private':
        bot.reply_to(message, "❌ Эта команда работает только в групповых чатах!")
        return
    
    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Только администраторы могут устанавливать норму!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            current_norm = get_norm()
            bot.reply_to(message, f"📊 Текущая норма: **{current_norm}** баллов\n\n"
                                  f"Для изменения нормы используйте: `.норма [число]`")
            return
        
        norm_value = float(parts[1])
        if norm_value <= 0:
            bot.reply_to(message, "❌ Норма должна быть положительным числом!")
            return
        
        set_norm(norm_value)
        bot.reply_to(message, f"✅ Установлена норма: **{norm_value}** баллов")
        
    except ValueError:
        bot.reply_to(message, "❌ Пожалуйста, укажите корректное число")

@bot.message_handler(func=lambda message: message.text and 
                     (message.text.lower().startswith('+баллы') or message.text.lower().startswith('-баллы')))
def handle_points_change(message):
    if is_bot(message.from_user):
        return
    
    if message.chat.type == 'private':
        bot.reply_to(message, "❌ Эта команда работает только в групповых чатах!")
        return
    
    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Только администраторы чата могут изменять баллы!")
        return
    
    try:
        text = message.text.strip()
        text_lower = text.lower()
        parts = text.split()
        
        is_positive = text_lower.startswith('+баллы')
        
        target_user_id = None
        target_user_info = None
        points_change = None
        reason = ""
        
        if len(parts) >= 2:
            if message.reply_to_message:
                if is_bot(message.reply_to_message.from_user):
                    bot.reply_to(message, "❌ Нельзя изменять баллы ботов!")
                    return
                
                try:
                    points_change = float(parts[1])
                    if len(parts) > 2:
                        reason = ' '.join(parts[2:])
                    target_user = message.reply_to_message.from_user
                    target_user_id = target_user.id
                    target_user_info = target_user
                except ValueError:
                    bot.reply_to(message, "❌ Неверный формат числа баллов")
                    return
                    
            elif len(parts) >= 3:
                identifier = parts[1]
                try:
                    points_change = float(parts[2])
                    if len(parts) > 3:
                        reason = ' '.join(parts[3:])
                except ValueError:
                    bot.reply_to(message, "❌ Неверный формат числа баллов")
                    return
                
                target_user_id = get_user_by_identifier(message.chat.id, identifier)
                
                if target_user_id:
                    try:
                        chat_member = bot.get_chat_member(message.chat.id, target_user_id)
                        if is_bot(chat_member.user):
                            bot.reply_to(message, "❌ Нельзя изменять баллы ботов!")
                            return
                        target_user_info = chat_member.user
                        
                        update_user(target_user_id,
                                   target_user_info.username,
                                   target_user_info.first_name,
                                   target_user_info.last_name)
                    except:
                        target_user_info = None
                else:
                    bot.reply_to(message, f"❌ Пользователь {identifier} не найден в этом чате!")
                    return
            else:
                bot.reply_to(message, "❌ Неправильный формат команды")
                return
        else:
            bot.reply_to(message, "❌ Неправильный формат команды")
            return
        
        if not target_user_id:
            bot.reply_to(message, "❌ Не удалось определить пользователя!")
            return
        
        if not is_positive:
            points_change = -points_change
        
        admin_name = format_user_name(message.from_user.id, 
                                     message.from_user.username,
                                     message.from_user.first_name,
                                     message.from_user.last_name)
        
        new_points = change_points(target_user_id, points_change, reason, 
                                  message.from_user.id, admin_name)
        
        if new_points is not None:
            if target_user_info:
                if target_user_info.username:
                    user_mention = f"@{target_user_info.username}"
                else:
                    user_mention = target_user_info.first_name
            else:
                user_mention = f"ID: {target_user_id}"
            
            action = "добавлено" if points_change > 0 else "снято"
            abs_points = abs(points_change)
            
            response = f"✅ {action} {abs_points} баллов для {user_mention}\n"
            response += f"💰 Текущий баланс: {new_points} баллов"
            
            if reason:
                response += f"\n📝 Причина: {reason}"
            
            bot.reply_to(message, response)
        else:
            bot.reply_to(message, "❌ Ошибка при изменении баллов")
            
    except ValueError:
        bot.reply_to(message, "❌ Пожалуйста, укажите корректное число баллов")
    except Exception as e:
        bot.reply_to(message, f"❌ Произошла ошибка: {str(e)}")

@bot.message_handler(func=lambda message: message.text and 
                     (message.text.lower().startswith('+мбаллы') or message.text.lower().startswith('-мбаллы')))
def handle_mass_points_change(message):
    if is_bot(message.from_user):
        return
    
    if message.chat.type == 'private':
        bot.reply_to(message, "❌ Эта команда работает только в групповых чатах!")
        return
    
    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Только администраторы чата могут изменять баллы!")
        return
    
    if not message.reply_to_message:
        bot.reply_to(message, "❌ Эта команда должна быть ответом на сообщение с ID/username пользователей!\n"
                              "Пример: ответьте на сообщение с текстом '@user1 12345 @user2' и напишите '+мбаллы 5'")
        return
    
    try:
        text = message.text.strip()
        text_lower = text.lower()
        
        is_positive = text_lower.startswith('+мбаллы')
        command_length = 7
        
        args_text = text[command_length:].strip()
        
        if not args_text:
            bot.reply_to(message, "❌ Укажите количество баллов!\n"
                                  "Пример: +мбаллы 5 За активность")
            return
        
        args_parts = args_text.split()
        
        try:
            points_change = float(args_parts[0])
        except ValueError:
            bot.reply_to(message, "❌ Первым аргументом должно быть количество баллов!\n"
                                  "Пример: +мбаллы 5 За активность")
            return
        
        reason = ' '.join(args_parts[1:]) if len(args_parts) > 1 else ""
        
        if not is_positive:
            points_change = -points_change
        
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        
        if not replied_text:
            bot.reply_to(message, "❌ В сообщении, на которое вы отвечаете, нет текста!")
            return
        
        identifiers = extract_identifiers_from_text(replied_text)
        
        if not identifiers:
            bot.reply_to(message, "❌ В сообщении не найдено ID или username пользователей!\n"
                                  "Убедитесь, что в сообщении есть @username или числовые ID.")
            return
        
        user_ids = []
        not_found = []
        
        for identifier in identifiers:
            user_id = get_user_by_identifier(message.chat.id, identifier)
            if user_id:
                user_ids.append(user_id)
                try:
                    chat_member = bot.get_chat_member(message.chat.id, user_id)
                    update_user(user_id,
                               chat_member.user.username,
                               chat_member.user.first_name,
                               chat_member.user.last_name)
                except:
                    pass
            else:
                not_found.append(identifier)
        
        if not user_ids:
            bot.reply_to(message, "❌ Не удалось найти ни одного пользователя из списка!")
            return
        
        user_ids = list(dict.fromkeys(user_ids))
        
        admin_name = format_user_name(message.from_user.id, 
                                     message.from_user.username,
                                     message.from_user.first_name,
                                     message.from_user.last_name)
        
        results = change_points_multiple(user_ids, points_change, reason, 
                                        message.from_user.id, admin_name)
        
        action = "добавлено" if points_change > 0 else "снято"
        abs_points = abs(points_change)
        
        successful = len([r for r in results if r[2]])
        
        # Формируем ответ
        response = f"📊 **Результаты массового начисления:**\n\n"
        response += f"✅ {action} {abs_points} баллов для {successful} из {len(user_ids)} пользователей\n\n"
        
        response += "**Список пользователей:**\n"
        for i, (user_id, new_points, success) in enumerate(results, 1):
            user_display = get_user_display_name(user_id, message.chat.id)
            user_display = escape_markdown(user_display)
            status = "✅" if success else "❌"
            response += f"{i}. {status} {user_display}"
            if success:
                response += f" → {new_points} баллов"
            response += "\n"
        
        if not_found:
            response += f"\n❌ **Не найдены ({len(not_found)}):**\n"
            for identifier in not_found[:5]:
                response += f"• {identifier}\n"
            if len(not_found) > 5:
                response += f"• ...и еще {len(not_found) - 5}\n"
        
        if reason:
            reason_escaped = escape_markdown(reason)
            response += f"\n📝 Причина: {reason_escaped}"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except ValueError:
        bot.reply_to(message, "❌ Пожалуйста, укажите корректное число баллов")
    except Exception as e:
        bot.reply_to(message, f"❌ Произошла ошибка: {str(e)}")

@bot.message_handler(commands=['новый_этап'])
@bot.message_handler(func=lambda message: message.text == 'новый_этап')
def reset_points(message):
    if message.chat.type == 'private':
        bot.reply_to(message, "❌ Эта команда работает только в групповых чатах!")
        return
    
    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Только администраторы чата могут сбрасывать баллы!")
        return
    
    keyboard = types.InlineKeyboardMarkup()
    yes_button = types.InlineKeyboardButton("✅ Да, сбросить все баллы", callback_data="reset_confirm")
    no_button = types.InlineKeyboardButton("❌ Отмена", callback_data="reset_cancel")
    keyboard.add(yes_button, no_button)
    
    norm = get_norm()
    norm_text = f" (норма: {norm} баллов)" if norm > 0 else ""
    
    bot.reply_to(message, 
                f"⚠️ Вы уверены, что хотите начать новый этап?{norm_text}\n"
                f"Будут показаны участники, не выполнившие норму. Это действие нельзя отменить!",
                reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "reset_confirm":
        if not is_chat_admin(call.message.chat.id, call.from_user.id):
            bot.answer_callback_query(call.id, "❌ У вас нет прав для этого действия!")
            return
        
        norm = get_norm()
        
        users = get_all_users_points()
        
        if norm > 0 and users:
            not_completed = []
            completed = []
            
            for user_id, username, first_name, last_name, points in users:
                name_display = format_user_name(user_id, username, first_name, last_name)
                name_display = escape_markdown(name_display)
                
                if points < norm:
                    not_completed.append(f"• {name_display}: **{points}** баллов (не хватает {norm - points})")
                else:
                    completed.append(f"• {name_display}: **{points}** баллов")
            
            result_message = f"📊 **Итоги этапа**\n\n"
            
            if not_completed:
                not_completed_text = "\n".join(not_completed)
                result_message += f"❌ **Не выполнили норму ({norm} баллов):**\n{not_completed_text}\n\n"
            else:
                result_message += "✅ **Все участники выполнили норму!**\n\n"
            
            if completed:
                completed_text = "\n".join(completed)
                result_message += f"✅ **Выполнили норму:**\n{completed_text}\n\n"
            
            result_message += "🔄 **Начинаем новый этап!** Все баллы сброшены."
        else:
            if norm == 0:
                result_message = "⚠️ Норма не была установлена. Используйте `.норма [число]` для установки нормы.\n\n🔄 Все баллы сброшены."
            else:
                result_message = "🔄 Начинаем новый этап! Все баллы сброшены."
        
        reset_all_points()
        
        bot.edit_message_text(
            result_message,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown'
        )
    elif call.data == "reset_cancel":
        bot.edit_message_text(
            "❌ Сброс баллов отменён.",
            call.message.chat.id,
            call.message.message_id
        )

@bot.message_handler(commands=['check_admin'])
def check_admin(message):
    if message.chat.type == 'private':
        bot.reply_to(message, "❌ Эта команда работает только в группах")
        return
    
    is_admin = is_chat_admin(message.chat.id, message.from_user.id)
    status = "✅ Вы администратор этого чата" if is_admin else "❌ Вы НЕ администратор этого чата"
    bot.reply_to(message, status)

@bot.message_handler(func=lambda message: True)
def register_user(message):
    if not is_bot(message.from_user):
        update_user(message.from_user.id, 
                   message.from_user.username,
                   message.from_user.first_name,
                   message.from_user.last_name)

if __name__ == '__main__':
    print("🤖 Бот запускается...")
    init_db()
    print(f"✅ База данных инициализирована по пути: {DB_PATH}")
    print("📝 Инструкция:")
    print("1. Добавьте бота в группу")
    print("2. Сделайте бота администратором группы")
    print("\n📌 Доступные команды:")
    print("   👤 Для всех:")
    print("   • .баллы - показать свои баллы")
    print("   • .история - показать историю операций")
    print("   👑 Для админов:")
    print("   • +баллы [число] [причина] (ответом) - добавить баллы одному пользователю")
    print("   • -баллы [число] [причина] (ответом) - отнять баллы у одного пользователя")
    print("   • +баллы @username [число] [причина] - добавить баллы по username")
    print("   • +баллы 123456789 [число] [причина] - добавить баллы по ID")
    print("   • +мбаллы [число] [причина] (ответом на сообщение с ID/username) - добавить баллы нескольким пользователям")
    print("   • -мбаллы [число] [причина] (ответом на сообщение с ID/username) - отнять баллы у нескольких пользователей")
    print("   • .баллывсе - показать баллы всех пользователей")
    print("   • .норма [число] - установить норму баллов")
    print("   • новый_этап - сбросить баллы и показать не выполнивших норму")
    print("\n📌 Причина необязательна")
    print(f"📌 База данных: {DB_PATH}")
    print("🚀 Бот готов к работе!")
    bot.infinity_polling()
