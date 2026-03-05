import logging
import sqlite3
import os
import re
from datetime import datetime
from typing import Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ConversationHandler,
    filters, 
    ContextTypes
)


# Конфигурация
BOT_TOKEN = "8675966383:AAEMrgaxRGQnkgd2eB4YTnDLJvEjM8bvBiI"  
GROUP_ID = -1003744040637  
ADMIN_IDS = [214357942] 


# Состояния для ConversationHandler
(NAME, PHONE, CAR_NUMBER, MESSAGE) = range(4)


# Настройка логирования
logging.basicFormat = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(
    format=logging.basicFormat,
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class Database:
    """Класс для работы с SQLite базой данных"""
    
    def __init__(self, db_name='drivers.db'):
        self.db_name = db_name
        self.init_db()
        # Проверяем и обновляем структуру таблиц
        self.migrate_db()
    
    def migrate_db(self):
        """Обновление структуры базы данных (миграции)"""
        try:
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.cursor()
                
                # Проверяем, существует ли таблица drivers
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='drivers'")
                if cursor.fetchone():
                    # Проверяем, есть ли колонка phone
                    cursor.execute("PRAGMA table_info(drivers)")
                    columns = [column[1] for column in cursor.fetchall()]
                    
                    # Если нет колонки phone, добавляем её
                    if 'phone' not in columns:
                        logger.info("Добавляем колонку phone в таблицу drivers")
                        cursor.execute("ALTER TABLE drivers ADD COLUMN phone TEXT")
                    
                    # Проверяем и добавляем другие возможные отсутствующие колонки
                    if 'username' not in columns:
                        logger.info("Добавляем колонку username в таблицу drivers")
                        cursor.execute("ALTER TABLE drivers ADD COLUMN username TEXT")
                    
                    if 'topic_id' not in columns:
                        logger.info("Добавляем колонку topic_id в таблицу drivers")
                        cursor.execute("ALTER TABLE drivers ADD COLUMN topic_id INTEGER UNIQUE")
                    
                    if 'is_active' not in columns:
                        logger.info("Добавляем колонку is_active в таблицу drivers")
                        cursor.execute("ALTER TABLE drivers ADD COLUMN is_active BOOLEAN DEFAULT 1")
                    
                    if 'last_message' not in columns:
                        logger.info("Добавляем колонку last_message в таблицу drivers")
                        cursor.execute("ALTER TABLE drivers ADD COLUMN last_message TIMESTAMP")
                
                # Проверяем таблицу messages
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
                if cursor.fetchone():
                    cursor.execute("PRAGMA table_info(messages)")
                    columns = [column[1] for column in cursor.fetchall()]
                    
                    # Добавляем новые колонки если их нет
                    if 'message_type' not in columns:
                        logger.info("Добавляем колонку message_type в таблицу messages")
                        cursor.execute("ALTER TABLE messages ADD COLUMN message_type TEXT DEFAULT 'text'")
                    
                    if 'file_id' not in columns:
                        logger.info("Добавляем колонку file_id в таблицу messages")
                        cursor.execute("ALTER TABLE messages ADD COLUMN file_id TEXT")
                
                conn.commit()
                logger.info("Миграция базы данных завершена успешно")
                
        except Exception as e:
            logger.error(f"Ошибка при миграции базы данных: {e}")
    
    def init_db(self):
        """Инициализация таблиц в базе данных"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            
            # Таблица водителей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS drivers (
                    driver_id INTEGER PRIMARY KEY,
                    driver_name TEXT,
                    phone TEXT,
                    car_number TEXT,
                    username TEXT,
                    topic_id INTEGER UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    last_message TIMESTAMP
                )
            ''')
            
            # Таблица сообщений с поддержкой медиа
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    driver_id INTEGER,
                    sender_type TEXT,  -- 'driver' или 'admin'
                    message_type TEXT DEFAULT 'text',  -- 'text', 'photo', 'voice'
                    message_text TEXT,
                    file_id TEXT,  -- для хранения ID фото или голосового
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (driver_id) REFERENCES drivers (driver_id)
                )
            ''')
            
            # Таблица для закрепленных сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pinned_messages (
                    topic_id INTEGER PRIMARY KEY,
                    message_id INTEGER,
                    pinned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    def add_driver(self, driver_id: int, driver_name: str, phone: str, car_number: str, username: str, topic_id: int):
        """Добавление нового водителя"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO drivers (driver_id, driver_name, phone, car_number, username, topic_id, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 1)
            ''', (driver_id, driver_name, phone, car_number, username, topic_id))
            conn.commit()
    
    def update_driver_info(self, driver_id: int, driver_name: str, phone: str, car_number: str, username: str):
        """Обновление информации о водителе"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE drivers 
                SET driver_name = ?, phone = ?, car_number = ?, username = ?, last_message = CURRENT_TIMESTAMP
                WHERE driver_id = ?
            ''', (driver_name, phone, car_number, username, driver_id))
            conn.commit()
    
    def get_driver_by_topic(self, topic_id: int) -> Optional[Dict]:
        """Получение информации о водителе по ID темы"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT driver_id, driver_name, phone, car_number, username, is_active 
                FROM drivers 
                WHERE topic_id = ? AND is_active = 1
            ''', (topic_id,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'driver_id': row[0],
                    'driver_name': row[1],
                    'phone': row[2],
                    'car_number': row[3],
                    'username': row[4],
                    'is_active': row[5]
                }
            return None
    
    def get_driver_by_id(self, driver_id: int) -> Optional[Dict]:
        """Получение информации о водителе по его ID"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT driver_id, driver_name, phone, car_number, username, topic_id, is_active 
                FROM drivers 
                WHERE driver_id = ? AND is_active = 1
            ''', (driver_id,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'driver_id': row[0],
                    'driver_name': row[1],
                    'phone': row[2],
                    'car_number': row[3],
                    'username': row[4],
                    'topic_id': row[5],
                    'is_active': row[6]
                }
            return None
    
    def get_driver_by_car_number(self, car_number: str) -> Optional[Dict]:
        """Получение информации о водителе по номеру авто"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT driver_id, driver_name, phone, car_number, username, topic_id, is_active 
                FROM drivers 
                WHERE car_number = ? AND is_active = 1
            ''', (car_number,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'driver_id': row[0],
                    'driver_name': row[1],
                    'phone': row[2],
                    'car_number': row[3],
                    'username': row[4],
                    'topic_id': row[5],
                    'is_active': row[6]
                }
            return None
    
    def get_all_active_drivers(self) -> list:
        """Получение списка всех активных водителей"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT driver_id, driver_name, phone, car_number, username, topic_id, created_at 
                FROM drivers 
                WHERE is_active = 1 
                ORDER BY created_at DESC
            ''')
            rows = cursor.fetchall()
            
            drivers = []
            for row in rows:
                drivers.append({
                    'driver_id': row[0],
                    'driver_name': row[1],
                    'phone': row[2],
                    'car_number': row[3],
                    'username': row[4],
                    'topic_id': row[5],
                    'created_at': row[6]
                })
            return drivers
    
    def save_message(self, driver_id: int, sender_type: str, message_text: str, message_type: str = 'text', file_id: str = None):
        """Сохранение сообщения в историю"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (driver_id, sender_type, message_type, message_text, file_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (driver_id, sender_type, message_type, message_text, file_id))
            
            # Обновляем время последнего сообщения
            cursor.execute('''
                UPDATE drivers SET last_message = CURRENT_TIMESTAMP
                WHERE driver_id = ?
            ''', (driver_id,))
            
            conn.commit()
    
    def save_pinned_message(self, topic_id: int, message_id: int):
        """Сохранение ID закрепленного сообщения"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO pinned_messages (topic_id, message_id, pinned_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (topic_id, message_id))
            conn.commit()
    
    def get_pinned_message(self, topic_id: int) -> Optional[int]:
        """Получение ID закрепленного сообщения"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT message_id FROM pinned_messages WHERE topic_id = ?
            ''', (topic_id,))
            row = cursor.fetchone()
            return row[0] if row else None
    
    def get_driver_history(self, driver_id: int, limit: int = 50) -> list:
        """Получение истории сообщений водителя"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT sender_type, message_type, message_text, file_id, sent_at 
                FROM messages 
                WHERE driver_id = ? 
                ORDER BY sent_at DESC 
                LIMIT ?
            ''', (driver_id, limit))
            
            rows = cursor.fetchall()
            messages = []
            for row in rows:
                message_info = {
                    'sender': row[0],
                    'type': row[1],
                    'time': row[4]
                }
                
                if row[1] == 'photo':
                    message_info['text'] = f"[ФОТО]"
                    if row[2]:  # если есть подпись
                        message_info['caption'] = row[2]
                elif row[1] == 'voice':
                    message_info['text'] = f"[ГОЛОСОВОЕ СООБЩЕНИЕ]"
                    if row[2]:  # если есть подпись
                        message_info['caption'] = row[2]
                else:
                    message_info['text'] = row[2]
                
                messages.append(message_info)
            return messages
    
    def deactivate_driver(self, driver_id: int):
        """Деактивация водителя (закрытие темы)"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE drivers SET is_active = 0 
                WHERE driver_id = ?
            ''', (driver_id,))
            conn.commit()
    
    def delete_driver_messages(self, driver_id: int):
        """Удаление всех сообщений водителя"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM messages 
                WHERE driver_id = ?
            ''', (driver_id,))
            conn.commit()
    
    def delete_driver(self, driver_id: int):
        """Полное удаление водителя из базы"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # Сначала получаем topic_id
            cursor.execute('SELECT topic_id FROM drivers WHERE driver_id = ?', (driver_id,))
            row = cursor.fetchone()
            if row:
                # Удаляем закрепленное сообщение
                cursor.execute('DELETE FROM pinned_messages WHERE topic_id = ?', (row[0],))
            # Удаляем сообщения
            cursor.execute('DELETE FROM messages WHERE driver_id = ?', (driver_id,))
            # Затем удаляем водителя
            cursor.execute('DELETE FROM drivers WHERE driver_id = ?', (driver_id,))
            conn.commit()
    
    def get_stats(self) -> Dict:
        """Получение статистики"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            
            # Общее количество водителей
            cursor.execute('SELECT COUNT(*) FROM drivers')
            total_drivers = cursor.fetchone()[0]
            
            # Активные водители
            cursor.execute('SELECT COUNT(*) FROM drivers WHERE is_active = 1')
            active_drivers = cursor.fetchone()[0]
            
            # Всего сообщений
            cursor.execute('SELECT COUNT(*) FROM messages')
            total_messages = cursor.fetchone()[0]
            
            # Количество фото
            cursor.execute('SELECT COUNT(*) FROM messages WHERE message_type = "photo"')
            total_photos = cursor.fetchone()[0]
            
            # Количество голосовых
            cursor.execute('SELECT COUNT(*) FROM messages WHERE message_type = "voice"')
            total_voices = cursor.fetchone()[0]
            
            return {
                'total_drivers': total_drivers,
                'active_drivers': active_drivers,
                'total_messages': total_messages,
                'total_photos': total_photos,
                'total_voices': total_voices
            }


# Создаем глобальный экземпляр базы данных
db = Database()

def validate_phone(phone: str) -> bool:
    """Проверка формата номера телефона"""
    # Убираем все пробелы, скобки, тире
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    # Проверяем, что остались только цифры и возможно +
    if not re.match(r'^\+?\d{10,15}$', cleaned):
        return False
    return True

def format_phone(phone: str) -> str:
    """Форматирование номера телефона для красивого отображения"""
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    if len(cleaned) == 11 and cleaned.startswith('8'):
        # Российский номер: 8XXXYYYZZZZ -> +7 (XXX) YYY-ZZZZ
        return f"+7 ({cleaned[1:4]}) {cleaned[4:7]}-{cleaned[7:9]}-{cleaned[9:11]}"
    elif len(cleaned) == 12 and cleaned.startswith('7'):
        # Российский номер: 7XXXYYYZZZZ -> +7 (XXX) YYY-ZZZZ
        return f"+7 ({cleaned[1:4]}) {cleaned[4:7]}-{cleaned[7:9]}-{cleaned[9:11]}"
    elif len(cleaned) == 12 and cleaned.startswith('+7'):
        # Уже с +7
        return f"+7 ({cleaned[2:5]}) {cleaned[5:8]}-{cleaned[8:10]}-{cleaned[10:12]}"
    else:
        # Если не российский формат, возвращаем как есть
        return cleaned

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    chat_type = update.effective_chat.type
    
    logger.info(f"Команда /start от пользователя {user.id} в чате {chat_type}")
    
    # Если команда в группе
    if chat_type in ['group', 'supergroup']:
        if user.id in ADMIN_IDS:
            await show_admin_panel(update, context)
        else:
            await update.message.reply_text(
                "❌ У вас нет доступа к этой группе."
            )
    else:
        # Личные сообщения - регистрация
        try:
            driver_info = db.get_driver_by_id(user.id)
        except Exception as e:
            logger.error(f"Ошибка при получении информации о водителе: {e}")
            driver_info = None
        
        if driver_info:
            # Водитель уже зарегистрирован
            await update.message.reply_text(
                f"👋 **С возвращением, {driver_info['driver_name']}!**\n\n"
                f"📞 Телефон: {driver_info['phone']}\n"
                f"🚗 Автомобиль: {driver_info['car_number']}\n\n"
                "Напишите ваше сообщение, отправьте фото или голосовое сообщение, и они будут отправлены руководителю.",
                parse_mode='Markdown'
            )
        else:
            # Новый водитель
            await update.message.reply_text(
                "👋 **Добро пожаловать!**\n\n"
                "Для начала работы мне нужно узнать ваши данные.\n\n"
                "📝 **Шаг 1 из 3:** Введите ваше имя:",
                parse_mode='Markdown'
            )
            return NAME

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода имени"""
    context.user_data['driver_name'] = update.message.text
    
    await update.message.reply_text(
        f"✅ Имя сохранено: {context.user_data['driver_name']}\n\n"
        "📞 **Шаг 2 из 3:** Введите ваш номер телефона\n"
        "(например: +7 999 123-45-67 или 89991234567):",
        parse_mode='Markdown'
    )
    return PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода номера телефона"""
    phone_raw = update.message.text.strip()
    
    if not validate_phone(phone_raw):
        await update.message.reply_text(
            "❌ **Неверный формат номера телефона!**\n\n"
            "Пожалуйста, введите номер в формате:\n"
            "• +7 999 123-45-67\n"
            "• 89991234567\n"
            "• 79991234567\n\n"
            "Попробуйте еще раз:",
            parse_mode='Markdown'
        )
        return PHONE
    
    # Форматируем номер для красивого отображения
    formatted_phone = format_phone(phone_raw)
    context.user_data['phone'] = formatted_phone
    
    await update.message.reply_text(
        f"✅ Номер телефона сохранен: {formatted_phone}\n\n"
        "🚗 **Шаг 3 из 3:** Введите номер вашего автомобиля "
        "(например: А123ВВ 777 или 1234 AB-5):",
        parse_mode='Markdown'
    )
    return CAR_NUMBER

async def handle_car_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода номера авто"""
    user = update.effective_user
    car_number = update.message.text.strip().upper()
    driver_name = context.user_data.get('driver_name')
    phone = context.user_data.get('phone')
    
    # Сохраняем номер в user_data
    context.user_data['car_number'] = car_number
    
    # Проверяем, есть ли уже активная тема с таким номером
    existing_driver = db.get_driver_by_car_number(car_number)
    
    if existing_driver and existing_driver['is_active']:
        # Проверяем, совпадает ли имя
        if existing_driver['driver_name'].lower() == driver_name.lower():
            # Имя совпадает - перекидываем в существующую тему
            await update.message.reply_text(
                f"✅ **Добро пожаловать!**\n\n"
                f"Мы нашли вашу существующую тему.\n"
                f"👤 Имя: {driver_name}\n"
                f"📞 Телефон: {phone}\n"
                f"🚗 Автомобиль: {car_number}\n\n"
                f"Теперь напишите ваше сообщение, отправьте фото или голосовое, и они будут отправлены в вашу тему.",
                parse_mode='Markdown'
            )
            
            # Обновляем информацию о водителе (на случай, если изменился username или телефон)
            db.update_driver_info(user.id, driver_name, phone, car_number, user.username or "")
            
            # Очищаем данные
            context.user_data.clear()
            
            # Завершаем регистрацию
            return ConversationHandler.END
        else:
            # Имя НЕ совпадает - автоматически удаляем старую тему и создаем новую
            await update.message.reply_text(
                f"⚠️ **Внимание!**\n\n"
                f"Номер автомобиля **{car_number}** уже зарегистрирован на другого водителя.\n"
                f"Текущий водитель: {existing_driver['driver_name']}\n"
                f"Вы указали имя: {driver_name}\n\n"
                f"🔄 **Автоматически удаляю старую тему и создаю новую для вас...**",
                parse_mode='Markdown'
            )
            
            # Удаляем старую тему и создаем новую
            result = await replace_topic_and_create_new(context, user, driver_name, phone, car_number, existing_driver)
            
            if result:
                await update.message.reply_text(
                    f"✅ **Новая тема успешно создана!**\n\n"
                    f"Старая тема с номером {car_number} была удалена.\n\n"
                    f"👤 Ваше имя: {driver_name}\n"
                    f"📞 Телефон: {phone}\n"
                    f"🚗 Номер авто: {car_number}\n\n"
                    f"Теперь напишите ваше первое сообщение, отправьте фото или голосовое руководителю.",
                    parse_mode='Markdown'
                )
                
                # Очищаем данные
                context.user_data.clear()
                
                # Завершаем регистрацию
                return ConversationHandler.END
            else:
                await update.message.reply_text(
                    "❌ Не удалось создать новую тему. Пожалуйста, попробуйте позже."
                )
                return ConversationHandler.END
    
    # Если номер свободен - запрашиваем первое сообщение
    await update.message.reply_text(
        f"✅ Номер авто сохранен: {car_number}\n\n"
        "📝 **Отлично!** Теперь напишите ваше первое сообщение, отправьте фото или голосовое руководителю:",
        parse_mode='Markdown'
    )
    return MESSAGE

async def replace_topic_and_create_new(context: ContextTypes.DEFAULT_TYPE, user, driver_name: str, phone: str, car_number: str, existing_driver: Dict) -> bool:
    """Функция для удаления старой темы и создания новой"""
    try:
        # Уведомляем старого водителя (если это другой пользователь)
        if existing_driver['driver_id'] != user.id:
            try:
                await context.bot.send_message(
                    chat_id=existing_driver['driver_id'],
                    text="⚠️ Ваша тема была закрыта, так как ваш номер автомобиля зарегистрирован другим водителем."
                )
            except:
                pass
        
        # Закрываем старую тему в группе
        try:
            await context.bot.close_forum_topic(
                chat_id=GROUP_ID,
                message_thread_id=existing_driver['topic_id']
            )
        except Exception as e:
            logger.error(f"Ошибка при закрытии старой темы: {e}")
        
        # Удаляем старого водителя из базы полностью
        db.delete_driver(existing_driver['driver_id'])
        
        # Создаем новую тему
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        topic_name = f"🚗 {driver_name} | {car_number}"
        
        result = await context.bot.create_forum_topic(
            chat_id=GROUP_ID,
            name=topic_name
        )
        
        topic_id = result.message_thread_id
        
        # Создаем красивое информационное сообщение для закрепления
        info_message = (
            f"📌 **ИНФОРМАЦИЯ О ВОДИТЕЛЕ** 📌\n\n"
            f"👤 **Имя:** {driver_name}\n"
            f"📞 **Телефон:** {phone}\n"
            f"🚗 **Автомобиль:** {car_number}\n"
            f"🆔 **ID:** `{user.id}`\n"
            f"📅 **Дата регистрации:** {current_time}\n\n"
            f"---\n"
            f"📝 *Это сообщение закреплено. Вся важная информация о водителе находится здесь.*"
        )
        
        # Отправляем информационное сообщение
        info_msg = await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=info_message,
            parse_mode='Markdown'
        )
        
        # Закрепляем сообщение
        try:
            await context.bot.pin_chat_message(
                chat_id=GROUP_ID,
                message_id=info_msg.message_id,
                message_thread_id=topic_id
            )
            # Сохраняем ID закрепленного сообщения
            db.save_pinned_message(topic_id, info_msg.message_id)
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения: {e}")
        
        # Отправляем приветственное сообщение о новом обращении
        welcome_text = (
            f"✅ **Новое обращение!**\n\n"
            f"**Водитель:** {driver_name}\n"
            f"**Телефон:** {phone}\n"
            f"**Автомобиль:** {car_number}\n"
            f"**Время:** {current_time}\n\n"
            f"**Первое сообщение:**\nНовая регистрация\n\n"
            f"---\n"
            f"📝 *Чтобы ответить водителю, просто напишите сообщение, отправьте фото или голосовое в эту тему*\n"
            f"⚠️ *Старая тема с этим номером была автоматически удалена*"
        )
        
        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=welcome_text,
            parse_mode='Markdown'
        )
        
        # Сохраняем нового водителя
        db.add_driver(
            driver_id=user.id,
            driver_name=driver_name,
            phone=phone,
            car_number=car_number,
            username=user.username or "",
            topic_id=topic_id
        )
        
        # Сохраняем приветственное сообщение
        db.save_message(user.id, 'driver', "Новая регистрация")
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 **Новый водитель!**\n\n"
                         f"👤 {driver_name}\n"
                         f"📞 {phone}\n"
                         f"🚗 {car_number}\n"
                         f"Тема создана: {topic_name}\n"
                         f"⚠️ Старая тема с этим номером удалена",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при замене темы: {e}")
        return False

async def handle_first_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка первого сообщения и создание темы"""
    user = update.effective_user
    message = update.message
    
    # Получаем данные из контекста
    driver_name = context.user_data.get('driver_name')
    phone = context.user_data.get('phone')
    car_number = context.user_data.get('car_number')
    
    if not driver_name or not phone or not car_number:
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, начните заново с команды /start"
        )
        return ConversationHandler.END
    
    await update.message.reply_text("🔄 Создаю тему для вашего обращения...")
    
    # Определяем тип сообщения (текст, фото или голосовое)
    if message.photo:
        # Это фото
        photo = message.photo[-1]  # Берем фото максимального размера
        file_id = photo.file_id
        caption = message.caption or ""
        topic_id = await create_driver_topic_with_photo(context, user, driver_name, phone, car_number, file_id, caption)
        message_text = f"[ФОТО]"
        if caption:
            message_text += f" - {caption}"
        message_type = 'photo'
    elif message.voice:
        # Это голосовое сообщение
        file_id = message.voice.file_id
        caption = message.caption or ""
        topic_id = await create_driver_topic_with_voice(context, user, driver_name, phone, car_number, file_id, caption)
        message_text = f"[ГОЛОСОВОЕ]"
        if caption:
            message_text += f" - {caption}"
        message_type = 'voice'
    else:
        # Это текст
        topic_id = await create_driver_topic(context, user, driver_name, phone, car_number, message.text)
        message_text = message.text
        message_type = 'text'
    
    if topic_id:
        # Сохраняем водителя в базу
        db.add_driver(
            driver_id=user.id,
            driver_name=driver_name,
            phone=phone,
            car_number=car_number,
            username=user.username or "",
            topic_id=topic_id
        )
        
        # Сохраняем сообщение в историю
        if message_type in ['photo', 'voice']:
            db.save_message(user.id, 'driver', message_text, message_type, file_id)
        else:
            db.save_message(user.id, 'driver', message_text)
        
        # Очищаем данные
        context.user_data.clear()
        
        await update.message.reply_text(
            "✅ **Тема успешно создана!**\n\n"
            f"👤 Ваше имя: {driver_name}\n"
            f"📞 Телефон: {phone}\n"
            f"🚗 Номер авто: {car_number}\n\n"
            "Все ваши сообщения, фото и голосовые теперь будут сохраняться в отдельной теме.\n"
            "Руководитель ответит вам в ближайшее время.\n\n"
            "Вы можете продолжать писать, отправлять фото и голосовые сюда.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ Не удалось создать тему. Пожалуйста, попробуйте позже или обратитесь к руководителю."
        )
    
    return ConversationHandler.END

async def create_driver_topic(context: ContextTypes.DEFAULT_TYPE, driver_user, driver_name: str, phone: str, car_number: str, first_message: str):
    """Создание новой темы для водителя (текстовое сообщение)"""
    try:
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        topic_name = f"🚗 {driver_name} | {car_number}"
        
        result = await context.bot.create_forum_topic(
            chat_id=GROUP_ID,
            name=topic_name
        )
        
        topic_id = result.message_thread_id
        
        # Создаем красивое информационное сообщение для закрепления
        info_message = (
            f"📌 **ИНФОРМАЦИЯ О ВОДИТЕЛЕ** 📌\n\n"
            f"👤 **Имя:** {driver_name}\n"
            f"📞 **Телефон:** {phone}\n"
            f"🚗 **Автомобиль:** {car_number}\n"
            f"🆔 **ID:** `{driver_user.id}`\n"
            f"📅 **Дата регистрации:** {current_time}\n\n"
            f"---\n"
            f"📝 *Это сообщение закреплено. Вся важная информация о водителе находится здесь.*"
        )
        
        # Отправляем информационное сообщение
        info_msg = await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=info_message,
            parse_mode='Markdown'
        )
        
        # Закрепляем сообщение
        try:
            await context.bot.pin_chat_message(
                chat_id=GROUP_ID,
                message_id=info_msg.message_id,
                message_thread_id=topic_id
            )
            # Сохраняем ID закрепленного сообщения
            db.save_pinned_message(topic_id, info_msg.message_id)
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения: {e}")
        
        # Отправляем приветственное сообщение о новом обращении
        welcome_text = (
            f"✅ **Новое обращение!**\n\n"
            f"**Водитель:** {driver_name}\n"
            f"**Телефон:** {phone}\n"
            f"**Автомобиль:** {car_number}\n"
            f"**Время:** {current_time}\n\n"
            f"**Первое сообщение:**\n{first_message}\n\n"
            f"---\n"
            f"📝 *Чтобы ответить водителю, просто напишите сообщение, отправьте фото или голосовое в эту тему*\n"
            f"📌 *Информация о водителе закреплена выше*"
        )
        
        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=welcome_text,
            parse_mode='Markdown'
        )
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 **Новый водитель!**\n\n"
                         f"👤 {driver_name}\n"
                         f"📞 {phone}\n"
                         f"🚗 {car_number}\n"
                         f"Тема создана: {topic_name}",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        return topic_id
        
    except Exception as e:
        logger.error(f"Ошибка при создании темы: {e}")
        return None

async def create_driver_topic_with_photo(context: ContextTypes.DEFAULT_TYPE, driver_user, driver_name: str, phone: str, car_number: str, file_id: str, caption: str = ""):
    """Создание новой темы для водителя с фото"""
    try:
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        topic_name = f"🚗 {driver_name} | {car_number}"
        
        result = await context.bot.create_forum_topic(
            chat_id=GROUP_ID,
            name=topic_name
        )
        
        topic_id = result.message_thread_id
        
        # Создаем красивое информационное сообщение для закрепления
        info_message = (
            f"📌 **ИНФОРМАЦИЯ О ВОДИТЕЛЕ** 📌\n\n"
            f"👤 **Имя:** {driver_name}\n"
            f"📞 **Телефон:** {phone}\n"
            f"🚗 **Автомобиль:** {car_number}\n"
            f"🆔 **ID:** `{driver_user.id}`\n"
            f"📅 **Дата регистрации:** {current_time}\n\n"
            f"---\n"
            f"📝 *Это сообщение закреплено. Вся важная информация о водителе находится здесь.*"
        )
        
        # Отправляем информационное сообщение
        info_msg = await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=info_message,
            parse_mode='Markdown'
        )
        
        # Закрепляем сообщение
        try:
            await context.bot.pin_chat_message(
                chat_id=GROUP_ID,
                message_id=info_msg.message_id,
                message_thread_id=topic_id
            )
            # Сохраняем ID закрепленного сообщения
            db.save_pinned_message(topic_id, info_msg.message_id)
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения: {e}")
        
        # Отправляем фото в тему
        photo_caption = f"📸 **Первое сообщение от {driver_name}:**\n\n{caption}" if caption else f"📸 **Первое сообщение от {driver_name}:**"
        await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            photo=file_id,
            caption=photo_caption,
            parse_mode='Markdown'
        )
        
        # Отправляем приветственное сообщение о новом обращении
        welcome_text = (
            f"✅ **Новое обращение с фото!**\n\n"
            f"**Водитель:** {driver_name}\n"
            f"**Телефон:** {phone}\n"
            f"**Автомобиль:** {car_number}\n"
            f"**Время:** {current_time}\n\n"
            f"---\n"
            f"📝 *Чтобы ответить водителю, просто напишите сообщение, отправьте фото или голосовое в эту тему*\n"
            f"📌 *Информация о водителе закреплена выше*"
        )
        
        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=welcome_text,
            parse_mode='Markdown'
        )
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 **Новый водитель с фото!**\n\n"
                         f"👤 {driver_name}\n"
                         f"📞 {phone}\n"
                         f"🚗 {car_number}\n"
                         f"Тема создана: {topic_name}",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        return topic_id
        
    except Exception as e:
        logger.error(f"Ошибка при создании темы с фото: {e}")
        return None

async def create_driver_topic_with_voice(context: ContextTypes.DEFAULT_TYPE, driver_user, driver_name: str, phone: str, car_number: str, file_id: str, caption: str = ""):
    """Создание новой темы для водителя с голосовым сообщением"""
    try:
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        topic_name = f"🚗 {driver_name} | {car_number}"
        
        result = await context.bot.create_forum_topic(
            chat_id=GROUP_ID,
            name=topic_name
        )
        
        topic_id = result.message_thread_id
        
        # Создаем красивое информационное сообщение для закрепления
        info_message = (
            f"📌 **ИНФОРМАЦИЯ О ВОДИТЕЛЕ** 📌\n\n"
            f"👤 **Имя:** {driver_name}\n"
            f"📞 **Телефон:** {phone}\n"
            f"🚗 **Автомобиль:** {car_number}\n"
            f"🆔 **ID:** `{driver_user.id}`\n"
            f"📅 **Дата регистрации:** {current_time}\n\n"
            f"---\n"
            f"📝 *Это сообщение закреплено. Вся важная информация о водителе находится здесь.*"
        )
        
        # Отправляем информационное сообщение
        info_msg = await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=info_message,
            parse_mode='Markdown'
        )
        
        # Закрепляем сообщение
        try:
            await context.bot.pin_chat_message(
                chat_id=GROUP_ID,
                message_id=info_msg.message_id,
                message_thread_id=topic_id
            )
            # Сохраняем ID закрепленного сообщения
            db.save_pinned_message(topic_id, info_msg.message_id)
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения: {e}")
        
        # Отправляем голосовое в тему
        voice_caption = f"🎤 **Первое голосовое от {driver_name}:**\n\n{caption}" if caption else f"🎤 **Первое голосовое от {driver_name}:**"
        await context.bot.send_voice(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            voice=file_id,
            caption=voice_caption,
            parse_mode='Markdown'
        )
        
        # Отправляем приветственное сообщение о новом обращении
        welcome_text = (
            f"✅ **Новое обращение с голосовым!**\n\n"
            f"**Водитель:** {driver_name}\n"
            f"**Телефон:** {phone}\n"
            f"**Автомобиль:** {car_number}\n"
            f"**Время:** {current_time}\n\n"
            f"---\n"
            f"📝 *Чтобы ответить водителю, просто напишите сообщение, отправьте фото или голосовое в эту тему*\n"
            f"📌 *Информация о водителе закреплена выше*"
        )
        
        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=welcome_text,
            parse_mode='Markdown'
        )
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🆕 **Новый водитель с голосовым!**\n\n"
                         f"👤 {driver_name}\n"
                         f"📞 {phone}\n"
                         f"🚗 {car_number}\n"
                         f"Тема создана: {topic_name}",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        return topic_id
        
    except Exception as e:
        logger.error(f"Ошибка при создании темы с голосовым: {e}")
        return None

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена регистрации"""
    await update.message.reply_text(
        "❌ Регистрация отменена. Для начала заново введите /start"
    )
    return ConversationHandler.END

async def handle_driver_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений от зарегистрированных водителей"""
    user = update.effective_user
    message = update.message
    
    driver_info = db.get_driver_by_id(user.id)
    
    if driver_info:
        topic_id = driver_info['topic_id']
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                message_thread_id=topic_id,
                text=f"📨 **Сообщение от {driver_info['driver_name']} ({driver_info['phone']}, {driver_info['car_number']}):**\n\n{message.text}",
                parse_mode='Markdown'
            )
            
            # Сохраняем в историю
            db.save_message(user.id, 'driver', message.text)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке в тему: {e}")
            await message.reply_text(
                "❌ Ошибка при отправке. Пожалуйста, попробуйте позже."
            )
    else:
        # Незарегистрированный пользователь
        await message.reply_text(
            "❌ Вы не зарегистрированы. Пожалуйста, введите /start для регистрации."
        )

async def handle_driver_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото от зарегистрированных водителей"""
    user = update.effective_user
    message = update.message
    
    driver_info = db.get_driver_by_id(user.id)
    
    if driver_info:
        topic_id = driver_info['topic_id']
        photo = message.photo[-1]  # Берем фото максимального размера
        file_id = photo.file_id
        caption = message.caption or ""
        
        try:
            # Отправляем фото в тему группы
            photo_caption = f"📸 **Фото от {driver_info['driver_name']}:**\n\n{caption}" if caption else f"📸 **Фото от {driver_info['driver_name']}:**"
            await context.bot.send_photo(
                chat_id=GROUP_ID,
                message_thread_id=topic_id,
                photo=file_id,
                caption=photo_caption,
                parse_mode='Markdown'
            )
            
            # Сохраняем в историю
            message_text = f"[ФОТО]"
            if caption:
                message_text += f" - {caption}"
            db.save_message(user.id, 'driver', message_text, 'photo', file_id)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке фото в тему: {e}")
            await message.reply_text(
                "❌ Ошибка при отправке фото. Пожалуйста, попробуйте позже."
            )
    else:
        # Незарегистрированный пользователь
        await message.reply_text(
            "❌ Вы не зарегистрированы. Пожалуйста, введите /start для регистрации."
        )

async def handle_driver_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых сообщений от зарегистрированных водителей"""
    user = update.effective_user
    message = update.message
    
    driver_info = db.get_driver_by_id(user.id)
    
    if driver_info:
        topic_id = driver_info['topic_id']
        file_id = message.voice.file_id
        caption = message.caption or ""
        
        try:
            # Отправляем голосовое в тему группы
            voice_caption = f"🎤 **Голосовое от {driver_info['driver_name']}:**\n\n{caption}" if caption else f"🎤 **Голосовое от {driver_info['driver_name']}:**"
            await context.bot.send_voice(
                chat_id=GROUP_ID,
                message_thread_id=topic_id,
                voice=file_id,
                caption=voice_caption,
                parse_mode='Markdown'
            )
            
            # Сохраняем в историю
            message_text = f"[ГОЛОСОВОЕ]"
            if caption:
                message_text += f" - {caption}"
            db.save_message(user.id, 'driver', message_text, 'voice', file_id)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке голосового в тему: {e}")
            await message.reply_text(
                "❌ Ошибка при отправке голосового. Пожалуйста, попробуйте позже."
            )
    else:
        # Незарегистрированный пользователь
        await message.reply_text(
            "❌ Вы не зарегистрированы. Пожалуйста, введите /start для регистрации."
        )

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ панели администратора в группе"""
    keyboard = [
        [InlineKeyboardButton("📋 Список активных тем", callback_data="list_topics")],
        [InlineKeyboardButton("📊 Статистика", callback_data="show_stats")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="admin_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 **Панель администратора**\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых ответов администратора в теме"""
    message = update.message
    
    # Проверяем, что сообщение из темы
    if not message.message_thread_id:
        return
    
    topic_id = message.message_thread_id
    # Получаем информацию о водителе по теме
    driver_info = db.get_driver_by_topic(topic_id)
    
    if driver_info:
        driver_id = driver_info['driver_id']
        
        try:
            await context.bot.send_message(
                chat_id=driver_id,
                text=f"📨 **Ответ от руководителя:**\n\n{message.text}",
                parse_mode='Markdown'
            )
            
            # Сохраняем в историю
            db.save_message(driver_id, 'admin', message.text)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке ответа водителю: {e}")
    else:
        # Это не тема водителя
        pass

async def handle_admin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото от администратора в теме"""
    message = update.message
    
    # Проверяем, что сообщение из темы
    if not message.message_thread_id:
        return
    
    topic_id = message.message_thread_id
    # Получаем информацию о водителе по теме
    driver_info = db.get_driver_by_topic(topic_id)
    
    if driver_info:
        driver_id = driver_info['driver_id']
        photo = message.photo[-1]  # Берем фото максимального размера
        file_id = photo.file_id
        caption = message.caption or ""
        
        try:
            # Отправляем фото водителю
            photo_caption = f"📸 **Ответ от руководителя (фото):**\n\n{caption}" if caption else f"📸 **Ответ от руководителя (фото):**"
            await context.bot.send_photo(
                chat_id=driver_id,
                photo=file_id,
                caption=photo_caption,
                parse_mode='Markdown'
            )
            
            # Сохраняем в историю
            message_text = f"[ФОТО]"
            if caption:
                message_text += f" - {caption}"
            db.save_message(driver_id, 'admin', message_text, 'photo', file_id)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке фото водителю: {e}")
    else:
        # Это не тема водителя
        pass

async def handle_admin_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых сообщений от администратора в теме"""
    message = update.message
    
    # Проверяем, что сообщение из темы
    if not message.message_thread_id:
        return
    
    topic_id = message.message_thread_id
    # Получаем информацию о водителе по теме
    driver_info = db.get_driver_by_topic(topic_id)
    
    if driver_info:
        driver_id = driver_info['driver_id']
        file_id = message.voice.file_id
        caption = message.caption or ""
        
        try:
            # Отправляем голосовое водителю
            voice_caption = f"🎤 **Ответ от руководителя (голосовое):**\n\n{caption}" if caption else f"🎤 **Ответ от руководителя (голосовое):**"
            await context.bot.send_voice(
                chat_id=driver_id,
                voice=file_id,
                caption=voice_caption,
                parse_mode='Markdown'
            )
            
            # Сохраняем в историю
            message_text = f"[ГОЛОСОВОЕ]"
            if caption:
                message_text += f" - {caption}"
            db.save_message(driver_id, 'admin', message_text, 'voice', file_id)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке голосового водителю: {e}")
    else:
        # Это не тема водителя
        pass

async def close_topic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для закрытия темы /close"""
    user = update.effective_user
    message = update.message
    
    # Проверяем права администратора
    if user.id not in ADMIN_IDS:
        await message.reply_text("❌ У вас нет прав для этой команды")
        return
    
    if not message.message_thread_id:
        await message.reply_text("❌ Эта команда работает только в темах")
        return
    
    topic_id = message.message_thread_id
    driver_info = db.get_driver_by_topic(topic_id)
    
    if driver_info:
        driver_id = driver_info['driver_id']
        
        # Кнопки подтверждения
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, закрыть", callback_data=f"confirm_close_{driver_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_close")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.reply_text(
            f"Вы уверены, что хотите закрыть тему?\n"
            f"Водитель: {driver_info['driver_name']}\n"
            f"Телефон: {driver_info['phone']}\n"
            f"Автомобиль: {driver_info['car_number']}",
            reply_markup=reply_markup
        )
    else:
        await message.reply_text("❌ Это не тема водителя или тема уже закрыта")

async def driver_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра истории /history"""
    user = update.effective_user
    message = update.message
    
    # Проверяем права администратора
    if user.id not in ADMIN_IDS:
        await message.reply_text("❌ У вас нет прав для этой команды")
        return
    
    # Определяем ID водителя
    driver_id = None
    
    if context.args:
        # Если передан аргумент
        try:
            driver_id = int(context.args[0])
        except:
            await message.reply_text("❌ Неверный формат ID. Используйте: /history [ID_водителя]")
            return
    elif message.message_thread_id:
        # Если команда вызвана в теме
        topic_id = message.message_thread_id
        driver_info = db.get_driver_by_topic(topic_id)
        if driver_info:
            driver_id = driver_info['driver_id']
    
    if not driver_id:
        await message.reply_text(
            "❌ Укажите ID водителя или используйте команду в его теме.\n"
            "Пример: /history 123456789"
        )
        return
    
    # Получаем историю
    history = db.get_driver_history(driver_id, limit=20)
    
    if not history:
        await message.reply_text("📭 История сообщений пуста")
        return
    
    driver_info = db.get_driver_by_id(driver_id)
    if not driver_info:
        await message.reply_text("❌ Водитель не найден")
        return
    
    # Формируем текст истории
    history_text = f"**История сообщений с {driver_info['driver_name']} ({driver_info['phone']}, {driver_info['car_number']}):**\n\n"
    
    for msg in reversed(history):  # От старых к новым
        sender = "🚗 Водитель" if msg['sender'] == 'driver' else "👨‍💼 Руководитель"
        time = datetime.strptime(msg['time'], '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
        
        if msg.get('type') == 'photo':
            history_text += f"**{sender}** ({time}): 📸 {msg['text']}\n"
            if msg.get('caption'):
                history_text += f"   *Подпись: {msg['caption']}*\n"
        elif msg.get('type') == 'voice':
            history_text += f"**{sender}** ({time}): 🎤 {msg['text']}\n"
            if msg.get('caption'):
                history_text += f"   *Подпись: {msg['caption']}*\n"
        else:
            history_text += f"**{sender}** ({time}):\n{msg['text']}\n"
        history_text += "\n"
    
    # Разбиваем на части если слишком длинное
    if len(history_text) > 4000:
        for i in range(0, len(history_text), 4000):
            await message.reply_text(history_text[i:i+4000], parse_mode='Markdown')
    else:
        await message.reply_text(history_text, parse_mode='Markdown')

async def list_drivers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра всех активных водителей /list"""
    user = update.effective_user
    
    # Проверяем права администратора
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для этой команды")
        return
    
    drivers = db.get_all_active_drivers()
    
    if not drivers:
        await update.message.reply_text("📭 Нет активных водителей")
        return
    
    text = "**Активные водители:**\n\n"
    for driver in drivers:
        created = datetime.strptime(driver['created_at'], '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
        text += (
            f"🚗 **{driver['driver_name']}**\n"
            f"└ 📞 Телефон: {driver['phone']}\n"
            f"└ 🚗 Авто: {driver['car_number']}\n"
            f"└ 📅 Создан: {created}\n"
            f"└ 🆔 Тема: {driver['topic_id']}\n\n"
        )
    
    # Кнопка обновления
    keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data="refresh_list")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра статистики /stats"""
    user = update.effective_user
    
    # Проверяем права администратора
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для этой команды")
        return
    
    stats = db.get_stats()
    
    text = (
        "📊 **Статистика бота:**\n\n"
        f"👥 Всего водителей: **{stats['total_drivers']}**\n"
        f"✅ Активных сейчас: **{stats['active_drivers']}**\n"
        f"💬 Всего сообщений: **{stats['total_messages']}**\n"
        f"📸 Всего фото: **{stats['total_photos']}**\n"
        f"🎤 Всего голосовых: **{stats['total_voices']}**\n"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи /help"""
    user = update.effective_user
    
    if user.id in ADMIN_IDS:
        text = (
            "**🔧 Команды администратора:**\n\n"
            "`/list` - список активных водителей\n"
            "`/history [ID]` - история сообщений\n"
            "`/stats` - статистика\n"
            "`/close` - закрыть текущую тему\n"
            "`/help` - это сообщение\n\n"
            "**📝 Как работать:**\n"
            "• Для ответа водителю просто пишите в его тему\n"
            "• Можно отправлять фото и голосовые в ответ - они уйдут водителю\n"
            "• В теме закреплена информация о водителе\n"
            "• В названии темы указаны имя и номер авто\n"
            "• Все ответы автоматически пересылаются водителю\n"
            "• Используйте /history для просмотра истории\n"
            "• Закрывайте тему после решения вопроса"
        )
    else:
        text = (
            "**👋 Помощь для водителя:**\n\n"
            "1️⃣ Введите /start для регистрации\n"
            "2️⃣ Укажите ваше имя\n"
            "3️⃣ Укажите номер телефона\n"
            "4️⃣ Укажите номер автомобиля\n"
            "5️⃣ Напишите сообщение, отправьте фото или голосовое руководителю\n\n"
            "После регистрации все ваши сообщения, фото и голосовые "
            "будут пересылаться в вашу личную тему.\n\n"
            "Если номер авто уже занят другим водителем, старая тема автоматически удаляется."
        )
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "list_topics":
        drivers = db.get_all_active_drivers()
        if not drivers:
            await query.edit_message_text("📭 Нет активных тем")
            return
        
        text = "**📋 Активные темы:**\n\n"
        keyboard = []
        
        for driver in drivers:
            text += f"🚗 {driver['driver_name']} ({driver['phone']}, {driver['car_number']}) - с {driver['created_at'][:10]}\n"
            button = [InlineKeyboardButton(
                f"📝 {driver['driver_name']} - {driver['car_number']}", 
                callback_data=f"goto_topic_{driver['topic_id']}"
            )]
            keyboard.append(button)
        
        keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="refresh_list")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "show_stats":
        stats = db.get_stats()
        text = (
            "📊 **Статистика:**\n\n"
            f"👥 Всего водителей: {stats['total_drivers']}\n"
            f"✅ Активных: {stats['active_drivers']}\n"
            f"💬 Сообщений: {stats['total_messages']}\n"
            f"📸 Фото: {stats['total_photos']}\n"
            f"🎤 Голосовых: {stats['total_voices']}"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "admin_help":
        text = (
            "**📚 Как пользоваться ботом:**\n\n"
            "1️⃣ Водитель пишет боту в личку\n"
            "2️⃣ Водитель проходит регистрацию (имя, телефон, номер авто)\n"
            "3️⃣ Бот создает тему с именем и номером авто\n"
            "4️⃣ В теме закрепляется сообщение с контактами водителя\n"
            "5️⃣ Вы отвечаете в теме - ответ уходит водителю\n"
            "6️⃣ Можно отправлять фото и голосовые - они тоже уходят водителю\n"
            "7️⃣ Вся история сохраняется в базе данных\n\n"
            "**Команды:**\n"
            "/list - список водителей\n"
            "/history - история сообщений\n"
            "/stats - статистика\n"
            "/close - закрыть тему"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "back_to_admin":
        await show_admin_panel_from_callback(query)
    
    elif data == "refresh_list":
        # Обновляем список
        drivers = db.get_all_active_drivers()
        text = "**📋 Активные темы:**\n\n"
        for driver in drivers:
            text += f"🚗 {driver['driver_name']} ({driver['phone']}, {driver['car_number']}) - с {driver['created_at'][:10]}\n"
        
        await query.edit_message_text(text, parse_mode='Markdown')
        
        # Показываем панель
        await show_admin_panel_from_callback(query)
    
    elif data.startswith("goto_topic_"):
        topic_id = int(data.split("_")[2])
        driver_info = db.get_driver_by_topic(topic_id)
        if driver_info:
            await query.edit_message_text(
                f"🔗 **Тема водителя {driver_info['driver_name']}**\n\n"
                f"📞 Телефон: {driver_info['phone']}\n"
                f"🚗 Автомобиль: {driver_info['car_number']}\n"
                f"🆔 ID темы: `{topic_id}`\n\n"
                f"Найдите эту тему в списке тем группы. Там закреплена вся информация."
            )
    
    elif data.startswith("confirm_close_"):
        driver_id = int(data.split("_")[2])
        driver_info = db.get_driver_by_id(driver_id)
        
        if driver_info:
            # Деактивируем водителя
            db.deactivate_driver(driver_id)
            
            # Уведомляем водителя
            try:
                await context.bot.send_message(
                    chat_id=driver_id,
                    text="🔒 Ваша тема закрыта. Для нового обращения просто напишите сюда и начните заново."
                )
            except:
                pass
            
            # Закрываем тему в группе
            try:
                await context.bot.close_forum_topic(
                    chat_id=GROUP_ID,
                    message_thread_id=driver_info['topic_id']
                )
            except:
                pass
            
            await query.edit_message_text(
                f"✅ Тема водителя {driver_info['driver_name']} ({driver_info['phone']}, {driver_info['car_number']}) закрыта"
            )
    
    elif data == "cancel_close":
        await query.edit_message_text("❌ Закрытие отменено")

async def show_admin_panel_from_callback(query):
    """Показ панели администратора из callback"""
    keyboard = [
        [InlineKeyboardButton("📋 Список активных тем", callback_data="list_topics")],
        [InlineKeyboardButton("📊 Статистика", callback_data="show_stats")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="admin_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "👋 **Панель администратора**\n\nВыберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


def main():
    """Запуск бота"""
    
    logger.info("Запуск бота...")
    
    # Проверка токена
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("ОШИБКА: Не забудьте заменить BOT_TOKEN на реальный токен!")
        return
    
    if GROUP_ID == -1001234567890:
        logger.error("ОШИБКА: Не забудьте заменить GROUP_ID на реальный ID группы!")
        return
    
    if ADMIN_IDS == [123456789]:
        logger.error("ОШИБКА: Не забудьте заменить ADMIN_IDS на ваш Telegram ID!")
        return
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчик регистрации
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            CAR_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_car_number)],
            MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_first_message),
                MessageHandler(filters.PHOTO, handle_first_message),
                MessageHandler(filters.VOICE, handle_first_message)  # Добавляем обработку голосовых
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(conv_handler)
    
    # Обработчики для личных сообщений
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, 
        handle_driver_message
    ))
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        handle_driver_photo
    ))
    application.add_handler(MessageHandler(
        filters.VOICE & filters.ChatType.PRIVATE,
        handle_driver_voice
    ))
    
    # Обработчики для группы
    application.add_handler(CommandHandler("start", start, filters.ChatType.SUPERGROUP))
    application.add_handler(CommandHandler("help", help_command, filters.ChatType.SUPERGROUP))
    application.add_handler(CommandHandler("list", list_drivers_command, filters.ChatType.SUPERGROUP))
    application.add_handler(CommandHandler("history", driver_history_command, filters.ChatType.SUPERGROUP))
    application.add_handler(CommandHandler("stats", stats_command, filters.ChatType.SUPERGROUP))
    application.add_handler(CommandHandler("close", close_topic_command, filters.ChatType.SUPERGROUP))
    
    # Обработчики сообщений в темах
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.SUPERGROUP, 
        handle_admin_reply
    ))
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.SUPERGROUP,
        handle_admin_photo
    ))
    application.add_handler(MessageHandler(
        filters.VOICE & filters.ChatType.SUPERGROUP,
        handle_admin_voice
    ))
    
    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Запускаем бота
    logger.info("Бот успешно запущен и готов к работе!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
