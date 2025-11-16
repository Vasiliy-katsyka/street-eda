import asyncio
import logging
import os
import re
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, 
                           ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData
from dotenv import load_dotenv

# --- 1. CONFIGURATION ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_API_TOKEN")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.isdigit()]
DB_NAME = 'streeteda.db'

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 2. DATABASE (aiosqlite for async) ---
async def db_query(query, params=(), fetchone=False, commit=False, fetchall=False):
    """Asynchronous database query function."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(query, params)
        if commit:
            await db.commit()
            return None
        if fetchone:
            return await cursor.fetchone()
        if fetchall:
            return await cursor.fetchall()
        return await cursor.fetchall()

async def populate_db():
    """Populates the database with initial data if it's empty."""
    count = await db_query("SELECT COUNT(*) FROM categories", fetchone=True)
    if count and count[0] > 0:
        logging.info("Database already populated. Skipping.")
        return

    logging.info("Populating database with initial menu data...")
    categories_to_add = [('Шаурма',), ('Люля-кебаб',), ('Гарниры',), ('Добавки',), ('Другое',)]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executemany("INSERT INTO categories (name) VALUES (?)", categories_to_add)
        cursor = await db.execute("SELECT id, name FROM categories")
        cat_map = {name: id for id, name in await cursor.fetchall()}
        items_to_add = [
            ('Стандартная (400 грамм)', 'Классическая шаурма', 230, cat_map['Шаурма']), ('Мини (300 грамм)', 'Уменьшенная порция классики', 200, cat_map['Шаурма']), ('Сырная шаурма (500 грамм)', 'Шаурма с добавлением сыра', 250, cat_map['Шаурма']), ('Барбекю шаурма (500 грамм)', 'С фирменным соусом барбекю', 250, cat_map['Шаурма']), ('Гранатовая шаурма (500 грамм)', 'С пикантным гранатовым соусом', 250, cat_map['Шаурма']), ('По-мексикански шаурма (500 грамм)', 'Острая шаурма с халапеньо', 250, cat_map['Шаурма']), ('ХХЛ шаурма (600 грамм)', 'Огромная и сытная', 290, cat_map['Шаурма']), ('Шаурма без мяса (Веган)', 'Свежие овощи и соус в лаваше', 180, cat_map['Шаурма']), ('Гиро (500 грамм)', 'Греческая шаурма с картофелем фри внутри', 250, cat_map['Шаурма']), ('Сосиска в лаваше', 'Сосиска с овощами и соусом', 170, cat_map['Шаурма']), ('Шаурма с наггетсами', 'Шаурма с куриными наггетсами', 270, cat_map['Шаурма']), ('Люля-кебаб из свинины в лаваше', None, 300, cat_map['Люля-кебаб']), ('Люля-кебаб из говядины в лаваше', None, 300, cat_map['Люля-кебаб']), ('Картофель фри (100 гр)', 'Классический картофель фри', 100, cat_map['Гарниры']), ('Картофель по-деревенски (100 гр)', 'Аппетитные дольки картофеля', 100, cat_map['Гарниры']), ('Наггетсы (5 шт)', 'Куриные наггетсы', 100, cat_map['Гарниры']), ('Бургер-Хит', 'Наш фирменный бургер', 300, cat_map['Другое']), ('Доп. Картофель фри', None, 30, cat_map['Добавки']), ('Доп. Огурцы соленые', None, 30, cat_map['Добавки']), ('Доп. Сыр', None, 30, cat_map['Добавки']), ('Доп. Халапеньо', None, 30, cat_map['Добавки']), ('Доп. Мясо', None, 70, cat_map['Добавки']), ('Доп. Сосиска', None, 40, cat_map['Добавки']),
        ]
        await db.executemany("INSERT INTO menu_items (name, description, price, category_id) VALUES (?, ?, ?, ?)", items_to_add)
        await db.commit()
    logging.info("Database population complete.")

async def init_db():
    """Initializes the database and creates tables if they don't exist."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL)')
        await db.execute('''CREATE TABLE IF NOT EXISTS menu_items (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                          description TEXT, price REAL NOT NULL, photo_id TEXT, category_id INTEGER,
                          FOREIGN KEY (category_id) REFERENCES categories (id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS cart (user_id INTEGER, item_id INTEGER, quantity INTEGER,
                          PRIMARY KEY (user_id, item_id), FOREIGN KEY (item_id) REFERENCES menu_items (id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, user_id INTEGER, user_name TEXT,
                          phone_number TEXT, delivery_type TEXT, address TEXT, comment TEXT, total_amount REAL,
                          status TEXT DEFAULT 'new', created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS order_items (id INTEGER PRIMARY KEY, order_id INTEGER, item_name TEXT,
                          quantity INTEGER, price_per_item REAL, FOREIGN KEY (order_id) REFERENCES orders (id))''')
        await db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value REAL)')
        for admin_id in ADMIN_IDS:
            await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('delivery_fee', 400)")
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('free_delivery_threshold', 1000)")
        await db.commit()
    await populate_db()

# --- 3. BOT & FSM INITIALIZATION ---
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()

class OrderState(StatesGroup):
    awaiting_name = State()
    awaiting_phone = State()
    awaiting_address = State()
    awaiting_comment = State()
    awaiting_final_confirmation = State()

class AdminState(StatesGroup):
    awaiting_new_category_name = State()
    await_new_item_name = State()
    await_new_item_price = State()
    await_new_price = State()
    await_new_setting_value = State()

# --- 4. CALLBACK DATA FACTORIES ---
class CategoryCallback(CallbackData, prefix="cat"):
    id: int

class ItemCallback(CallbackData, prefix="item"):
    id: int

class RemoveFromCartCallback(CallbackData, prefix="rem"):
    item_id: int

class AdminCallback(CallbackData, prefix="admin"):
    action: str
    category_id: Optional[int] = None
    item_id: Optional[int] = None
    setting_key: Optional[str] = None
    
# --- 5. UI & LOGIC FUNCTIONS (USER) ---
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🍴 Меню")]], resize_keyboard=True)

async def show_categories(message: Message, message_id: Optional[int] = None):
    categories = await db_query("SELECT id, name FROM categories ORDER BY id")
    builder = InlineKeyboardBuilder()
    for cat_id, name in categories:
        builder.button(text=name, callback_data=CategoryCallback(id=cat_id))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛒 Корзина", callback_data='view_cart'))
    text = "👇 Выберите категорию:"
    try:
        if message_id:
            await bot.edit_message_text(text, message.chat.id, message_id, reply_markup=builder.as_markup())
        else:
            await message.answer(text, reply_markup=builder.as_markup())
    except Exception as e:
        logging.error(f"Error in show_categories: {e}")
        if message_id:
            await message.answer(text, reply_markup=builder.as_markup())

async def show_items_in_category(query: CallbackQuery, category_id: int):
    items = await db_query("SELECT id, name, price FROM menu_items WHERE category_id = ? ORDER BY name", (category_id,))
    builder = InlineKeyboardBuilder()
    for item_id, name, price in items:
        builder.button(text=f"{name} - {int(price)} руб.", callback_data=ItemCallback(id=item_id))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data='back_to_categories'))
    await query.message.edit_text("Выберите товар:", reply_markup=builder.as_markup())

async def show_cart(chat_id: int, message_id: Optional[int] = None, message: Optional[Message] = None):
    cart_items = await db_query('''SELECT mi.id, mi.name, mi.price, c.quantity FROM cart c 
                                   JOIN menu_items mi ON c.item_id = mi.id WHERE c.user_id = ?''', (chat_id,))
    builder = InlineKeyboardBuilder()
    text = "🛒 *Ваша корзина:*\n\n"
    if not cart_items:
        text = "🛒 Ваша корзина пуста."
        builder.button(text="⬅️ В меню", callback_data='back_to_categories')
    else:
        total_price = sum(price * quantity for _, _, price, quantity in cart_items)
        for item_id, name, price, quantity in cart_items:
            text += f"▪️ {name} ({int(price)}р) x {quantity} = {int(price * quantity)}р\n"
            builder.button(text=f"❌ Удалить {name}", callback_data=RemoveFromCartCallback(item_id=item_id))
        builder.adjust(1)
        text += f"\n*Итого: {int(total_price)} руб.*"
        builder.row(InlineKeyboardButton(text="✅ Оформить заказ", callback_data='checkout'))
        builder.row(InlineKeyboardButton(text="🗑️ Очистить", callback_data='clear_cart'),
                    InlineKeyboardButton(text="⬅️ В меню", callback_data='back_to_categories'))
    try:
        if message_id:
            await bot.edit_message_text(text, chat_id, message_id, reply_markup=builder.as_markup())
        elif message:
            await message.answer(text, reply_markup=builder.as_markup())
    except Exception as e:
        logging.error(f"Error editing cart message: {e}")
        if message_id and message:
            await message.answer(text, reply_markup=builder.as_markup())

async def confirm_order(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = message.chat.id
    cart_items = await db_query('''SELECT mi.name, mi.price, c.quantity FROM cart c JOIN menu_items mi 
                                   ON c.item_id = mi.id WHERE c.user_id = ?''', (chat_id,))
    subtotal = sum(price * quantity for _, price, quantity in cart_items)
    settings_list = await db_query("SELECT key, value FROM settings")
    settings = {key: value for key, value in settings_list}
    delivery_cost = 0
    delivery_cost_text = ""
    if data['delivery_type'] == 'delivery':
        if subtotal < settings['free_delivery_threshold']:
            delivery_cost = settings['delivery_fee']
            delivery_cost_text = f"🚛 *Доставка:* {int(delivery_cost)} руб.\n"
        else:
            delivery_cost_text = f"🚛 *Доставка:* Бесплатно (заказ от {int(settings['free_delivery_threshold'])} руб.)\n"
    final_total = subtotal + delivery_cost
    await state.update_data(final_total=final_total)
    delivery_text = 'Самовывоз' if data['delivery_type'] == 'takeaway' else 'Доставка'
    text = (f"🔍 *Проверьте ваш заказ:*\n\n"
            f"👤 *Имя:* {data['name']}\n"
            f"📞 *Телефон:* {data['phone']}\n"
            f"*Способ получения:* {delivery_text}\n")
    if data['delivery_type'] == 'delivery':
        text += f"📍 *Адрес:* {data.get('address', 'Не указан')}\n"
    if 'comment' in data:
        text += f"💬 *Комментарий:* {data['comment']}\n"
    text += "\n*Состав заказа:*\n" + "\n".join([f"▪️ {name} x {q} шт." for name, _, q in cart_items])
    text += f"\n\n📦 *Товары:* {int(subtotal)} руб.\n"
    text += delivery_cost_text
    text += f"💰 *Итого к оплате: {int(final_total)} руб.*\n\nВсё верно?"
    await state.set_state(OrderState.awaiting_final_confirmation)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, подтвердить", callback_data='confirm_order')],
        [InlineKeyboardButton(text="❌ Отмена", callback_data='cancel_order')]
    ])
    await message.answer(text, reply_markup=markup)

async def process_final_confirmation(query: CallbackQuery, state: FSMContext):
    chat_id = query.from_user.id
    data = await state.get_data()
    cart_items = await db_query('''SELECT mi.id, mi.name, mi.price, c.quantity FROM cart c 
                                   JOIN menu_items mi ON c.item_id = mi.id WHERE c.user_id = ?''', (chat_id,))
    if not cart_items:
        await query.message.answer("Ваша корзина пуста.", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return
    final_total = data.get('final_total', 0)
    delivery_text = 'Самовывоз' if data['delivery_type'] == 'takeaway' else 'Доставка'
    admin_text = (f"🔔 *Новый заказ*\n\n"
                  f"*Клиент:* {data['name']}, {data['phone']}\n"
                  f"*Тип:* {delivery_text}\n")
    if data['delivery_type'] == 'delivery':
        admin_text += f"*Адрес:* {data.get('address', 'Не указан')}\n"
    if 'comment' in data:
        admin_text += f"*Комментарий:* {data['comment']}\n"
    admin_text += "\n*Заказ:*\n" + "\n".join([f"▪️ {n} x {q} = {int(p * q)}р" for _, n, p, q in cart_items])
    admin_text += f"\n\n*Итого с доставкой: {int(final_total)} руб.*"
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''INSERT INTO orders (user_id, user_name, phone_number, delivery_type, address, comment, total_amount)
                                     VALUES (?, ?, ?, ?, ?, ?, ?)''', (chat_id, data['name'], data['phone'], data['delivery_type'],
                                     data.get('address', ''), data.get('comment', ''), final_total))
        order_id = cursor.lastrowid
        for _, name, price, quantity in cart_items:
            await db.execute('INSERT INTO order_items (order_id, item_name, quantity, price_per_item) VALUES (?, ?, ?, ?)',
                           (order_id, name, quantity, price))
        await db.commit()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text)
            await bot.send_message(admin_id, f"Заказу присвоен номер `#{order_id}`")
        except Exception as e:
            logging.error(f"Failed to send message to admin {admin_id}: {e}")
    await query.message.edit_text(f"✅ Спасибо! Ваш заказ `#{order_id}` принят.", reply_markup=None)
    await query.message.answer("Вы можете сделать новый заказ.", reply_markup=get_main_menu_keyboard())
    await db_query("DELETE FROM cart WHERE user_id = ?", (chat_id,), commit=True)
    await state.clear()

# --- 6. UI & LOGIC FUNCTIONS (ADMIN) ---
async def get_admin_panel(message_or_query):
    builder = InlineKeyboardBuilder()
    builder.button(text="Управление товарами", callback_data=AdminCallback(action="manage_items"))
    builder.button(text="⚙️ Настройки", callback_data=AdminCallback(action="settings"))
    builder.adjust(1)
    text = "Добро пожаловать в панель администратора."
    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=builder.as_markup())
    elif isinstance(message_or_query, CallbackQuery):
        await message_or_query.message.edit_text(text, reply_markup=builder.as_markup())

async def show_item_management_categories(query: CallbackQuery):
    categories = await db_query("SELECT id, name FROM categories ORDER BY id")
    builder = InlineKeyboardBuilder()
    for cat_id, name in categories:
        builder.button(text=name, callback_data=AdminCallback(action="view_cat_items", category_id=cat_id))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="➕ Добавить категорию", callback_data=AdminCallback(action="add_category")))
    builder.row(InlineKeyboardButton(text="➖ Удалить категорию", callback_data=AdminCallback(action="delete_category_menu")))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=AdminCallback(action="back_to_main")))
    await query.message.edit_text("Выберите категорию для управления товарами или воспользуйтесь опциями ниже:",
                                  reply_markup=builder.as_markup())

async def show_items_for_admin(query: CallbackQuery, category_id: int):
    items = await db_query("SELECT id, name, price FROM menu_items WHERE category_id = ?", (category_id,))
    builder = InlineKeyboardBuilder()
    for item_id, name, price in items:
        builder.button(text=f"{name} - {int(price)}р", callback_data=AdminCallback(action="edit_item", item_id=item_id))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="➕ Добавить новый товар",
                                      callback_data=AdminCallback(action="add_item", category_id=category_id)))
    builder.row(InlineKeyboardButton(text="⬅️ Назад к категориям",
                                      callback_data=AdminCallback(action="manage_items")))
    await query.message.edit_text("Нажмите на товар для редактирования или добавьте новый:",
                                  reply_markup=builder.as_markup())

async def show_item_edit_menu(query: CallbackQuery, item_id: int):
    item_name, cat_id = await db_query("SELECT name, category_id FROM menu_items WHERE id = ?", (item_id,), fetchone=True)
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить цену", callback_data=AdminCallback(action="edit_price", item_id=item_id))
    builder.button(text="🗑️ Удалить товар", callback_data=AdminCallback(action="confirm_delete_item", item_id=item_id, category_id=cat_id))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад к товарам",
                                      callback_data=AdminCallback(action="view_cat_items", category_id=cat_id)))
    await query.message.edit_text(f"Редактирование товара: *{item_name}*", reply_markup=builder.as_markup())

async def show_admin_settings(query: CallbackQuery):
    settings_list = await db_query("SELECT key, value FROM settings")
    settings = {key: value for key, value in settings_list}
    text = (f"⚙️ *Настройки бота*\n\n"
            f"🚚 *Стоимость доставки:* {int(settings.get('delivery_fee', 0))} руб.\n"
            f"🎉 *Бесплатная доставка от:* {int(settings.get('free_delivery_threshold', 0))} руб.")
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить стоимость доставки",
                   callback_data=AdminCallback(action="edit_setting", setting_key="delivery_fee"))
    builder.button(text="✏️ Изменить порог бесплатной доставки",
                   callback_data=AdminCallback(action="edit_setting", setting_key="free_delivery_threshold"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=AdminCallback(action="back_to_main")))
    await query.message.edit_text(text, reply_markup=builder.as_markup())
    
async def show_categories_for_deletion(query: CallbackQuery):
    categories = await db_query("SELECT id, name FROM categories ORDER BY id")
    builder = InlineKeyboardBuilder()
    if not categories:
        builder.button(text="Нет категорий для удаления", callback_data="no_op")
    else:
        for cat_id, name in categories:
            builder.button(text=f"❌ {name}", callback_data=AdminCallback(action="confirm_delete_category", category_id=cat_id))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=AdminCallback(action="manage_items")))
    await query.message.edit_text("Выберите категорию для удаления. ВНИМАНИЕ: это удалит все товары внутри нее.",
                                  reply_markup=builder.as_markup())

# --- 7. MESSAGE HANDLERS (GENERAL) ---
@dp.message(CommandStart())
async def send_welcome(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Здравствуйте!", reply_markup=get_main_menu_keyboard())

@dp.message(F.text == "🍴 Меню")
async def show_menu(message: Message, state: FSMContext):
    await state.clear()
    await show_categories(message)

# --- 8. MESSAGE HANDLERS (FSM - ORDERING) ---
@dp.message(OrderState.awaiting_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Спасибо! Теперь отправьте ваш номер телефона.",
                         reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Отправить мой контакт", request_contact=True)]],
                                                          resize_keyboard=True, one_time_keyboard=True))
    await state.set_state(OrderState.awaiting_phone)

@dp.message(OrderState.awaiting_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await message.answer("Ваш номер принят.", reply_markup=ReplyKeyboardRemove())
    builder = InlineKeyboardBuilder()
    builder.button(text="🏃 Самовывоз", callback_data='delivery:takeaway')
    builder.button(text="🚚 Доставка", callback_data='delivery:delivery')
    await message.answer("Выберите способ получения:", reply_markup=builder.as_markup())

@dp.message(OrderState.awaiting_phone)
async def process_phone_text(message: Message, state: FSMContext):
    phone = re.sub(r'\D', '', message.text)
    if 10 <= len(phone) <= 15:
        await state.update_data(phone=message.text)
        await message.answer("Ваш номер принят.", reply_markup=ReplyKeyboardRemove())
        builder = InlineKeyboardBuilder()
        builder.button(text="🏃 Самовывоз", callback_data='delivery:takeaway')
        builder.button(text="🚚 Доставка", callback_data='delivery:delivery')
        await message.answer("Выберите способ получения:", reply_markup=builder.as_markup())
    else:
        await message.answer("❌ Неверный формат номера. Попробуйте еще раз.")

@dp.message(OrderState.awaiting_address)
async def process_address(message: Message, state: FSMContext):
    if message.text and len(message.text) > 5:
        await state.update_data(address=message.text)
        await message.answer("Есть ли комментарий к заказу? Если нет, напишите 'нет'.")
        await state.set_state(OrderState.awaiting_comment)
    else:
        await message.answer("❌ Адрес слишком короткий. Пожалуйста, введите полный адрес.")

@dp.message(OrderState.awaiting_comment)
async def process_comment(message: Message, state: FSMContext):
    if message.text.lower().strip() not in ['нет', 'no', '-']:
        await state.update_data(comment=message.text)
    await confirm_order(message, state)

# --- 9. MESSAGE HANDLERS (FSM - ADMIN) ---
@dp.message(AdminState.awaiting_new_category_name)
async def process_new_category_name(message: Message, state: FSMContext):
    cat_name = message.text.strip()
    exists = await db_query("SELECT id FROM categories WHERE name = ?", (cat_name,), fetchone=True)
    if exists:
        await message.answer("❌ Категория с таким названием уже существует.")
    else:
        await db_query("INSERT INTO categories (name) VALUES (?)", (cat_name,), commit=True)
        await message.answer(f"✅ Категория '{cat_name}' успешно добавлена.")
        await state.clear()
        await get_admin_panel(message)

@dp.message(AdminState.await_new_item_name)
async def process_new_item_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отлично. Теперь введите цену товара (только цифры):")
    await state.set_state(AdminState.await_new_item_price)

@dp.message(AdminState.await_new_item_price)
async def process_new_item_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
        data = await state.get_data()
        await db_query("INSERT INTO menu_items (name, price, category_id) VALUES (?, ?, ?)",
                       (data['name'], price, data['category_id']), commit=True)
        await message.answer(f"✅ Товар '{data['name']}' успешно добавлен!")
        await state.clear()
        await get_admin_panel(message)
    except ValueError:
        await message.answer("Ошибка: цена должна быть числом. Попробуйте снова.")

@dp.message(AdminState.await_new_price)
async def process_new_price(message: Message, state: FSMContext):
    try:
        new_price = float(message.text)
        data = await state.get_data()
        await db_query("UPDATE menu_items SET price = ? WHERE id = ?", (new_price, data['item_id']), commit=True)
        await message.answer(f"✅ Цена успешно обновлена до {int(new_price)} руб.")
        await state.clear()
        await get_admin_panel(message)
    except ValueError:
        await message.answer("Ошибка: цена должна быть числом. Попробуйте снова.")

@dp.message(AdminState.await_new_setting_value)
async def process_new_setting_value(message: Message, state: FSMContext):
    try:
        new_value = float(message.text)
        data = await state.get_data()
        await db_query("UPDATE settings SET value = ? WHERE key = ?", (new_value, data['key']), commit=True)
        await message.answer("✅ Настройка успешно обновлена!")
        await state.clear()
        await get_admin_panel(message)
    except ValueError:
        await message.answer("Ошибка: введите только число. Попробуйте снова.")

# --- 10. CALLBACK HANDLERS (USER) ---
@dp.callback_query(CategoryCallback.filter())
async def handle_category_selection(q: CallbackQuery, callback_data: CategoryCallback):
    await show_items_in_category(q, callback_data.id)
    await q.answer()

@dp.callback_query(ItemCallback.filter())
async def handle_item_selection(q: CallbackQuery, callback_data: ItemCallback):
    await db_query("INSERT OR REPLACE INTO cart (user_id, item_id, quantity) VALUES (?, ?, COALESCE((SELECT quantity FROM cart WHERE user_id = ? AND item_id = ?), 0) + 1)",
                   (q.from_user.id, callback_data.id, q.from_user.id, callback_data.id), commit=True)
    await q.answer("✅ Добавлено в корзину!")

@dp.callback_query(RemoveFromCartCallback.filter())
async def handle_remove_from_cart(q: CallbackQuery, callback_data: RemoveFromCartCallback):
    await db_query("DELETE FROM cart WHERE user_id = ? AND item_id = ?", (q.from_user.id, callback_data.item_id), commit=True)
    await q.answer("🗑️ Удалено из корзины")
    await show_cart(q.from_user.id, q.message.message_id)

@dp.callback_query(F.data == 'back_to_categories')
async def handle_back_to_categories(q: CallbackQuery):
    await show_categories(q.message, q.message.message_id)
    await q.answer()

@dp.callback_query(F.data == 'view_cart')
async def handle_view_cart(q: CallbackQuery):
    await show_cart(q.from_user.id, q.message.message_id)
    await q.answer()

@dp.callback_query(F.data == 'clear_cart')
async def handle_clear_cart(q: CallbackQuery):
    await db_query("DELETE FROM cart WHERE user_id = ?", (q.from_user.id,), commit=True)
    await q.answer("🗑️ Корзина очищена")
    await show_categories(q.message, q.message.message_id)

@dp.callback_query(F.data == 'checkout')
async def handle_checkout(q: CallbackQuery, state: FSMContext):
    cart_exists = await db_query("SELECT 1 FROM cart WHERE user_id = ?", (q.from_user.id,), fetchone=True)
    if not cart_exists:
        await q.answer("Ваша корзина пуста!", show_alert=True)
        return
    await q.message.answer("📝 Введите ваше имя:")
    await state.set_state(OrderState.awaiting_name)
    await q.answer()

@dp.callback_query(F.data.startswith('delivery:'))
async def handle_delivery_choice(q: CallbackQuery, state: FSMContext):
    delivery_type = q.data.split(':')[1]
    await state.update_data(delivery_type=delivery_type)
    await q.message.delete()
    if delivery_type == 'delivery':
        await q.message.answer("📍 Пожалуйста, введите ваш адрес:")
        await state.set_state(OrderState.awaiting_address)
    else: # takeaway
        await q.message.answer("Есть ли комментарий к заказу? Если нет, напишите 'нет'.")
        await state.set_state(OrderState.awaiting_comment)
    await q.answer()

@dp.callback_query(F.data == 'confirm_order', OrderState.awaiting_final_confirmation)
async def handle_final_confirmation(q: CallbackQuery, state: FSMContext):
    await process_final_confirmation(q, state)
    await q.answer()

@dp.callback_query(F.data == 'cancel_order')
async def handle_cancel_order(q: CallbackQuery, state: FSMContext):
    await state.clear()
    await q.message.edit_text("❌ Заказ отменен.")
    await q.message.answer("Вы можете продолжить просмотр меню.", reply_markup=get_main_menu_keyboard())
    await q.answer()

# --- 11. ADMIN HANDLERS ---
@dp.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel_command(message: Message, state: FSMContext):
    await state.clear()
    await get_admin_panel(message)

@dp.callback_query(AdminCallback.filter(F.action == "back_to_main"), F.from_user.id.in_(ADMIN_IDS))
async def admin_back_to_main(q: CallbackQuery, state: FSMContext):
    await state.clear()
    await get_admin_panel(q)
    await q.answer()

@dp.callback_query(AdminCallback.filter(F.action == "manage_items"), F.from_user.id.in_(ADMIN_IDS))
async def admin_manage_items(q: CallbackQuery):
    await show_item_management_categories(q)
    await q.answer()

@dp.callback_query(AdminCallback.filter(F.action == "settings"), F.from_user.id.in_(ADMIN_IDS))
async def admin_settings(q: CallbackQuery):
    await show_admin_settings(q)
    await q.answer()

# Category Management
@dp.callback_query(AdminCallback.filter(F.action == "add_category"), F.from_user.id.in_(ADMIN_IDS))
async def admin_add_category(q: CallbackQuery, state: FSMContext):
    await q.message.answer("Введите название новой категории:")
    await state.set_state(AdminState.awaiting_new_category_name)
    await q.answer()

@dp.callback_query(AdminCallback.filter(F.action == "delete_category_menu"), F.from_user.id.in_(ADMIN_IDS))
async def admin_delete_category_menu(q: CallbackQuery):
    await show_categories_for_deletion(q)
    await q.answer()

@dp.callback_query(AdminCallback.filter(F.action == "confirm_delete_category"), F.from_user.id.in_(ADMIN_IDS))
async def admin_confirm_delete_category(q: CallbackQuery, callback_data: AdminCallback):
    cat_id = callback_data.category_id
    await db_query("DELETE FROM cart WHERE item_id IN (SELECT id FROM menu_items WHERE category_id = ?)", (cat_id,), commit=True)
    await db_query("DELETE FROM menu_items WHERE category_id = ?", (cat_id,), commit=True)
    await db_query("DELETE FROM categories WHERE id = ?", (cat_id,), commit=True)
    await q.answer("🗑️ Категория и все товары в ней удалены.", show_alert=True)
    await show_categories_for_deletion(q)

# Item Management
@dp.callback_query(AdminCallback.filter(F.action == "view_cat_items"), F.from_user.id.in_(ADMIN_IDS))
async def admin_view_cat_items(q: CallbackQuery, callback_data: AdminCallback):
    await show_items_for_admin(q, callback_data.category_id)
    await q.answer()
    
@dp.callback_query(AdminCallback.filter(F.action == "add_item"), F.from_user.id.in_(ADMIN_IDS))
async def admin_add_item(q: CallbackQuery, state: FSMContext, callback_data: AdminCallback):
    await state.set_data({'category_id': callback_data.category_id})
    await q.message.answer("Введите название нового товара:")
    await state.set_state(AdminState.await_new_item_name)
    await q.answer()
    
@dp.callback_query(AdminCallback.filter(F.action == "edit_item"), F.from_user.id.in_(ADMIN_IDS))
async def admin_edit_item(q: CallbackQuery, callback_data: AdminCallback):
    await show_item_edit_menu(q, callback_data.item_id)
    await q.answer()

@dp.callback_query(AdminCallback.filter(F.action == "edit_price"), F.from_user.id.in_(ADMIN_IDS))
async def admin_edit_price(q: CallbackQuery, state: FSMContext, callback_data: AdminCallback):
    await state.set_data({'item_id': callback_data.item_id})
    await q.message.answer("Введите новую цену товара:")
    await state.set_state(AdminState.await_new_price)
    await q.answer()
    
@dp.callback_query(AdminCallback.filter(F.action == "confirm_delete_item"), F.from_user.id.in_(ADMIN_IDS))
async def admin_confirm_delete_item(q: CallbackQuery, callback_data: AdminCallback):
    item_id = callback_data.item_id
    await db_query("DELETE FROM cart WHERE item_id = ?", (item_id,), commit=True)
    await db_query("DELETE FROM menu_items WHERE id = ?", (item_id,), commit=True)
    await q.answer("🗑️ Товар удален.", show_alert=True)
    await show_items_for_admin(q, callback_data.category_id)
    
# Settings Management
@dp.callback_query(AdminCallback.filter(F.action == "edit_setting"), F.from_user.id.in_(ADMIN_IDS))
async def admin_edit_setting(q: CallbackQuery, state: FSMContext, callback_data: AdminCallback):
    key = callback_data.setting_key
    await state.set_data({'key': key})
    prompt_text = "Введите новую стоимость доставки:" if key == "delivery_fee" else "Введите новый порог для бесплатной доставки:"
    await q.message.answer(prompt_text)
    await state.set_state(AdminState.await_new_setting_value)
    await q.answer()
    
# --- 12. START POLLING ---
async def main():
    if not BOT_TOKEN:
        logging.critical("No BOT_TOKEN found. Please set it in your .env file.")
        return
    if not ADMIN_IDS:
        logging.warning("No ADMIN_IDS found. Admin panel will be inaccessible.")
    await init_db()
    logging.info("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
