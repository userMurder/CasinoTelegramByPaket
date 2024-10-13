import time

from aiocryptopay import AioCryptoPay, Networks
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, \
    KeyboardButton
import asyncio
import uuid
import random
import sqlite3
import config
from datetime import datetime, timedelta
import keyboard

# Настройки бота
API_TOKEN = config.API_TOKEN
CRYPTO_API_TOKEN = config.CRYPTOPAY_API_TOKEN

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Инициализация CryptoPay
cryptopay = AioCryptoPay(token=CRYPTO_API_TOKEN, network=Networks.TEST_NET)

# Инициализация базы данных
conn = sqlite3.connect('casino_bot.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users
              (user_id INTEGER PRIMARY KEY, balance REAL)''')
conn.commit()

# Инициализация базы данных для логов
log_conn = sqlite3.connect(config.LOG_FILE)
log_cursor = log_conn.cursor()
log_cursor.execute('''
    CREATE TABLE IF NOT EXISTS logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        amount REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')
log_conn.commit()

referral_conn = sqlite3.connect(config.REFERRAL_FILE)
referral_cursor = referral_conn.cursor()

# Создаем таблицу referrals, если она не существует
referral_cursor.execute('''
    CREATE TABLE IF NOT EXISTS referrals (
        referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        referral_code TEXT,
        referred_user_id INTEGER,
        status TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')

# Сохраняем изменения
referral_conn.commit()


def log_action(user_id, action, amount):
    log_cursor.execute("INSERT INTO logs (user_id, action, amount) VALUES (?, ?, ?)",
                       (user_id, action, amount))
    log_conn.commit()


async def notify_admins(message):
    chat_id = config.chat_id_log
    await bot.send_message(chat_id, message)


def generate_referral_code(user_id):
    return f"{user_id}"


def generate_referral_link(user_id):
    referral_code = generate_referral_code(user_id)
    return f"https://t.me/FulldBetBot?start={referral_code}"


# Команда /start для регистрации пользователя
@dp.message(Command("start"))
async def send_welcome(message: Message):
    user_id = message.from_user.id
    referral_code = None

    # Проверяем наличие реферального кода
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]

    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user is None:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 100))
        conn.commit()
        log_action(user_id, "Registration", 100)
        await message.answer(
            "🎰 Добро пожаловать в наше казино! Ваш аккаунт создан и на баланс зачислено 10 USDT.\n/help для помощи")

        # Проверка и начисление реферального бонуса
        if referral_code:
            referral_cursor.execute("SELECT * FROM referrals WHERE referral_code=?", (referral_code,))
            referral_record = referral_cursor.fetchone()
            if referral_record:
                referrer_id = referral_record[1]
                # Проверка, не был ли уже добавлен этот реферал
                if referral_record[3] is None:
                    referral_cursor.execute("UPDATE referrals SET referred_user_id=?, status=? WHERE referral_code=?",
                                            (user_id, "completed", referral_code))
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (100, referrer_id))
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (100, user_id))
                    referral_conn.commit()
                    await bot.send_message(referrer_id,
                                           f"🎉 У вас новый реферал: @{message.from_user.username}!\nВы получили 100 USDT.")

    else:
        await message.answer("Вы уже зарегистрированы в казино.")

    await message.answer("Выберите действие:", reply_markup=keyboard.main_menu_markup)


# Команда /balance для проверки баланса
@dp.message(Command("balance"))
async def send_balance(message: Message):
    user_id = message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user:
        balance = user[0]
        await message.answer(f"💰 Ваш баланс: {balance} USDT")
    else:
        await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")


@dp.message(lambda message: message.text == "🎉Рефералы")
async def send_referral_info(message: Message):
    user_id = message.from_user.id

    # Получаем реферальную ссылку
    referral_link = generate_referral_link(user_id)

    # Информация о правилах и призах
    referral_info = (
        "🎉 Программа рефералов\n\n"
        "Пригласите своих друзей и получите вознаграждение! Вот как это работает:\n\n"
        "1. Как пригласить друзей: Отправьте своим друзьям вашу уникальную реферальную ссылку.\n"
        "2. Что вы получаете: Вы получите 100 USDT за каждого приглашенного друга, который зарегистрируется и начнет использовать наше казино.\n\n"
        f"🌟 Ваша уникальная реферальная ссылка: {referral_link}\n"
        f"РЕФЕРАЛКА ВРЕМЕННО НЕ РАБОТАЕТ!!!!!!!!!!!!!!!!!!!!!!!!"
    )

    await message.answer(referral_info)


@dp.message(lambda message: message.text in ["💰 Баланс", "🎮 Играть", "💳 Пополнить", "🏦 Вывод"])
async def handle_buttons(message: Message):
    if message.text == "💰 Баланс":
        await send_balance(message)
    elif message.text == "🎮 Играть":
        await play_game(message)
    elif message.text == "💳 Пополнить":
        await deposit(message)
    elif message.text == "🏦 Вывод":
        await withdraw(message)


# Команда /addbalance для выбора суммы пополнения
@dp.message(Command("deposit"))
async def deposit(message: Message):
    user_id = message.from_user.id
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💵 $1", callback_data="deposit_1")],
            [InlineKeyboardButton(text="💰 $10", callback_data="deposit_10")],
            [InlineKeyboardButton(text="💸 $100", callback_data="deposit_100")],
            [InlineKeyboardButton(text="💵 $500", callback_data="deposit_500")],
            [InlineKeyboardButton(text="💰 $1000", callback_data="deposit_1000")],
            [InlineKeyboardButton(text="💎 $5000", callback_data="deposit_5000")],
            [InlineKeyboardButton(text="💎 $10000", callback_data="deposit_10000")]

        ])
        await message.answer("💳 Выберите сумму для пополнения:", reply_markup=markup)
    else:
        await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")


@dp.callback_query(lambda c: c.data and c.data.startswith("deposit_"))
async def process_deposit(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    amount = int(callback_query.data.split("_")[1])  # Получаем сумму из callback_data
    invoice = await cryptopay.create_invoice(asset='USDT', amount=amount)

    # Кнопки для оплаты
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить через мини-приложение", url=invoice.mini_app_invoice_url)],
        [InlineKeyboardButton(text="Оплатить через бота", url=invoice.bot_invoice_url)]
    ])
    await bot.send_message(user_id, f"Переведите {amount} USDT для пополнения баланса.", reply_markup=markup)

    # Начинаем проверку платежа
    processed_invoices = set()

    while True:
        invoices = await cryptopay.get_invoices()
        for inv in invoices:
            invoice_id1 = invoices[0].invoice_id
            status = invoices[0].status
            amounts = invoices[0].amount

            # Проверяем, оплачен ли счет и не был ли он уже обработан
            if status == 'paid' and invoice_id1 not in processed_invoices:
                # Проверяем, совпадает ли оплаченный счет с ожидаемым
                if invoice_id1 == invoice.invoice_id:
                    # Обновляем баланс, логируем действие и уведомляем пользователя
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amounts, user_id))
                    conn.commit()
                    log_action(user_id, "Deposit", amounts)
                    processed_invoices.add(invoice_id1)  # Добавляем ID счета в множество обработанных

                    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
                    new_balance = cursor.fetchone()[0]
                    await bot.send_message(user_id,
                                           f"✅ Ваш баланс был пополнен на {amounts} USDT. Ваш текущий баланс: {new_balance} USDT.")
                    # Уведомляем администраторов
                    await notify_admins(f"💳 Пополнение баланса:\n\nПользователь ID: {user_id}\nСумма: {amounts} USDT")
                else:
                    # Если оплаченный счет не совпадает с ожидаемым, все равно зачисляем платеж
                    log_action(user_id, "Deposit (Unexpected Invoice)", amounts)
                    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
                    new_balance = cursor.fetchone()[0]
                    await bot.send_message(user_id,
                                           f"⚠️ Вы оплатили не ваш счет, но платеж будет зачислен.\n "
                                           f"Ваш баланс будет пополнен на {amounts} USDT. \n"
                                           f"Ваш текущий баланс: {new_balance} USDT. \n"
                                           f"Если это ошибка, свяжитесь с @dev_paketik.\n")
                    # Уведомляем администраторов о несоответствии
                    await notify_admins(f"⚠️ Неожиданное пополнение баланса:\n\nПользователь ID: {user_id}\n"
                                        f"Ожидался ID счета: {invoice.invoice_id}\n"
                                        f"Получен ID счета: {invoice_id1}\n"
                                        f"Сумма: {amounts} USDT")
                break  # Выходим из цикла после обработки платежа

        else:
            await asyncio.sleep(10)  # Ждем 10 секунд перед следующей проверкой
            continue
        break  # Выход из внешнего цикла, если найден и обработан оплаченный счет

    await callback_query.answer()


####################НАЧАЛО
# Команда /play для выбора режима игры
user_game_status = {}


@dp.message(Command("play"))
async def play_game(message: types.Message):
    user_id = message.from_user.id

    if user_game_status.get(user_id, False):
        await message.answer("🚫 Вы уже играете. Подождите, пока текущая игра завершится.")
        return

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user and user[0] >= 1:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Чет/Нечет", callback_data="mode_even_odd")],
            [InlineKeyboardButton(text="🔼 Больше/Меньше", callback_data="mode_higher_lower")],
            [InlineKeyboardButton(text="📦 Коробки", callback_data="mode_boxes")]
        ])
        await message.answer("🕹️ Объяснение игры - /help \nВыберите режим игры:", reply_markup=markup)
    else:
        await message.answer("🚫 На вашем балансе недостаточно средств для игры. Пополните баланс с помощью /deposit.")
        await message.answer("❗ Вы не зарегистрированы. Используйте /start для регистрации.")


@dp.callback_query(lambda c: c.data.startswith("mode_"))
async def choose_game_mode(callback_query: CallbackQuery):
    await callback_query.answer()

    user_id = callback_query.from_user.id
    game_mode = callback_query.data.split("_")[1]

    if user_game_status.get(user_id, False):
        await callback_query.message.answer("🚫 Вы уже играете. Подождите, пока текущая игра завершится.")
        return

    #user_game_status[user_id] = True

    if game_mode == "even_odd":
        await callback_query.message.edit_text("Вы выбрали режим: Чет/Нечет. 🎲")
        time.sleep(1)
    elif game_mode == "higher_lower":
        await callback_query.message.edit_text("Вы выбрали режим: Больше/Меньше. 🎲")
        time.sleep(1)
    elif game_mode == "boxes":
        await callback_query.message.edit_text("Вы выбрали режим: Коробки. 📦")
        time.sleep(1)

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💵 1 $", callback_data=f"stake_1_{game_mode}")],
            [InlineKeyboardButton(text="💰 10 $", callback_data=f"stake_10_{game_mode}")],
            [InlineKeyboardButton(text="💸 100 $", callback_data=f"stake_100_{game_mode}")],
            [InlineKeyboardButton(text="🤑 500 $", callback_data=f"stake_500_{game_mode}")],
            [InlineKeyboardButton(text="💴 1000 $", callback_data=f"stake_1000_{game_mode}")],
            [InlineKeyboardButton(text="💰 5000 $", callback_data=f"stake_5000_{game_mode}")]
        ])
        await callback_query.message.edit_text("Выберите сумму ставки:", reply_markup=markup)
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💵 1 $", callback_data=f"stake_1_{game_mode}")],
            [InlineKeyboardButton(text="💰 10 $", callback_data=f"stake_10_{game_mode}")],
            [InlineKeyboardButton(text="💸 100 $", callback_data=f"stake_100_{game_mode}")],
            [InlineKeyboardButton(text="🤑 500 $", callback_data=f"stake_500_{game_mode}")],
            [InlineKeyboardButton(text="💴 1000 $", callback_data=f"stake_1000_{game_mode}")],
            [InlineKeyboardButton(text="💰 5000 $", callback_data=f"stake_5000_{game_mode}")]
        ])
        await callback_query.message.edit_text("Выберите сумму ставки:", reply_markup=markup)


@dp.callback_query(lambda c: c.data.startswith("stake_"))
async def choose_stake(callback_query: CallbackQuery):
    await callback_query.answer()

    user_id = callback_query.from_user.id
    stake_data = callback_query.data.split("_")
    stake_amount = int(stake_data[1])
    game_mode = stake_data[2]

    if user_game_status.get(user_id, False):
        await callback_query.message.edit_text("🚫 Вы уже играете. Подождите, пока текущая игра завершится.")
        return

    user_game_status[user_id] = True

    if game_mode == "boxes":
        markup = InlineKeyboardMarkup(inline_keyboard=
        [
            [InlineKeyboardButton(text="📦", callback_data=f"box_1_{stake_amount}"),
             InlineKeyboardButton(text="📦", callback_data=f"box_2_{stake_amount}"),
             InlineKeyboardButton(text="📦", callback_data=f"box_3_{stake_amount}")]
        ]
        )
        await callback_query.message.edit_text("Выберите шкатулку:", reply_markup=markup)
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Кинуть кубик", callback_data=f"play_{stake_amount}_{game_mode}")]
        ])
        await callback_query.message.edit_text(
            f"💰 Ставка: {stake_amount} $. Нажмите кнопку ниже, чтобы кинуть кубик:",
            reply_markup=markup)


@dp.callback_query(lambda c: c.data.startswith("box_"))
async def choose_box(callback_query: CallbackQuery):
    await callback_query.answer()

    user_id = callback_query.from_user.id
    box_data = callback_query.data.split("_")
    chosen_box = int(box_data[1])
    stake_amount = int(box_data[2])

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user:
        balance = user[0]
        if balance >= stake_amount:
            try:
                prize_box = random.randint(1, 3)

                if chosen_box == prize_box:

                    win_amount = round(stake_amount * config.box_cof, 1)
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win_amount, user_id))
                    result_message = f"🎉 Вы выбрали шкатулку {chosen_box} и нашли приз! Вы выиграли {win_amount:.1f} USDT!"
                    user_name = callback_query.from_user.username
                    await notify_win(user_name, win_amount, 'Коробки📦')
                else:
                    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (stake_amount, user_id))
                    result_message = f"😔 Вы выбрали шкатулку {chosen_box}, но не нашли приз. Вы проиграли {stake_amount:.1f} USDT."

                conn.commit()
                updated_balance = cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()[0]
                updated_balance = round(updated_balance, 1)

                await callback_query.message.edit_text(
                    f"{result_message}\n💵 Ваш текущий баланс: {updated_balance} USDT.")
            except Exception as e:
                await callback_query.message.answer(f"⚠️ Ошибка при обновлении баланса: {e}")
                conn.rollback()
        else:
            await callback_query.message.edit_text(
                "🚫 На вашем балансе недостаточно средств для этой игры. Пополните баланс с помощью /deposit.")

    user_game_status[user_id] = False
    await callback_query.answer()


@dp.callback_query(lambda c: c.data.startswith("play_"))
async def play_dice_game(callback_query: CallbackQuery):
    global result_message
    user_id = callback_query.from_user.id
    play_data = callback_query.data.split("_")
    stake_amount = int(play_data[1])
    game_mode = play_data[2]

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user and user[0] >= stake_amount:
        try:
            dice_message = await callback_query.message.answer_dice(emoji="🎲")
            dice_value = dice_message.dice.value

            coefficient = config.coefficient

            if game_mode == "even":
                if dice_value % 2 == 0:
                    win_amount = round(stake_amount * coefficient, 1)
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win_amount, user_id))
                    result_message = f"🎉 Вам выпало {dice_value}. Вы выиграли {win_amount:.1f} USDT!"
                    user_name = callback_query.from_user.username
                    await notify_win(user_name, win_amount, 'Чет/Нечет🎲')
                else:
                    loss_amount = round(stake_amount, 1)
                    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (loss_amount, user_id))
                    result_message = f"😔 Вам выпало {dice_value}. Вы проиграли {loss_amount:.1f} USDT."

            elif game_mode == "higher":
                if dice_value >= 4:
                    win_amount = round(stake_amount * coefficient, 1)
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win_amount, user_id))
                    result_message = f"🎉 Вам выпало {dice_value}. Вы выиграли {win_amount:.1f} USDT!"
                    user_name = callback_query.from_user.username
                    await notify_win(user_name, win_amount, 'Больше/Меньше🎲')
                else:
                    loss_amount = round(stake_amount, 1)
                    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (loss_amount, user_id))
                    result_message = f"😔 Вам выпало {dice_value}. Вы проиграли {loss_amount:.1f} USDT."

            conn.commit()

            updated_balance = cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()[0]
            updated_balance = round(updated_balance, 1)

            await callback_query.message.edit_text(f"{result_message} 💵 Ваш текущий баланс: {updated_balance} USDT.")
        except Exception as e:
            await callback_query.message.answer(f"⚠️ Ошибка при обновлении баланса: {e}")
            conn.rollback()
    else:
        await callback_query.message.edit_text(
            "🚫 На вашем балансе недостаточно средств для этой ставки. Пополните баланс с помощью /deposit.")

    user_game_status[user_id] = False
    await callback_query.answer()


######################КОНЕЦ

user_cooldowns = {}

COOLDOWN_TIME = 30  # Время кд в секундах


@dp.message(Command("outbalance"))
async def withdraw(message: types.Message):
    user_id = message.from_user.id

    # Проверка, если пользователь уже успешно выводил средства недавно
    if user_id in user_cooldowns:
        last_withdraw_time = user_cooldowns[user_id]
        time_diff = datetime.now() - last_withdraw_time
        if time_diff < timedelta(seconds=COOLDOWN_TIME):
            remaining_time = COOLDOWN_TIME - int(time_diff.total_seconds())
            await message.answer(f"⏳ Пожалуйста, подождите {remaining_time} секунд перед повторным выводом средств.")
            return

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user:
        balance = user[0]
        if balance > 0:

            withdraw_10_button = KeyboardButton(text="💸 Вывести 10%")
            withdraw_25_button = KeyboardButton(text="💸 Вывести 25%")
            withdraw_50_button = KeyboardButton(text="💸 Вывести 50%")
            withdraw_all_button = KeyboardButton(text="💸 Вывести всё")

            markup = ReplyKeyboardMarkup(
                keyboard=[
                    [withdraw_10_button, withdraw_25_button],
                    [withdraw_50_button, withdraw_all_button]
                ],
                resize_keyboard=True
            )

            await message.answer(f"💰 Ваш баланс: {balance:.2f} USDT\nВыберите сумму для вывода:", reply_markup=markup)
        else:
            await message.answer("🚫 На вашем балансе недостаточно средств для вывода.")
    else:
        await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")


# Обработчик для кнопки "Вывести 10%"
@dp.message(lambda message: message.text == "💸 Вывести 10%")
async def withdraw_10_percent(message: types.Message):
    await process_withdrawal(message, 10)


# Обработчик для кнопки "Вывести 25%"
@dp.message(lambda message: message.text == "💸 Вывести 25%")
async def withdraw_25_percent(message: types.Message):
    await process_withdrawal(message, 25)


# Обработчик для кнопки "Вывести 50%"
@dp.message(lambda message: message.text == "💸 Вывести 50%")
async def withdraw_50_percent(message: types.Message):
    await process_withdrawal(message, 50)


# Обработчик для кнопки "Вывести всё"
@dp.message(lambda message: message.text == "💸 Вывести всё")
async def withdraw_all(message: types.Message):
    await process_withdrawal(message, 100)


# Общий метод для обработки вывода средств

async def process_withdrawal(message: types.Message, percentage: int):
    user_id = message.from_user.id  # Не забывайте получать user_id из сообщения
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if user:
        balance = user[0]

        if balance > 0:
            amount = balance * (percentage / 100)

            # Проверка баланса приложения
            app_balance = await cryptopay.get_balance()
            usdt_balance = get_balance('USDT', app_balance)

            if usdt_balance >= amount:
                # Обновление баланса пользователя
                cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                conn.commit()

                # Перевод средств
                transfer = await cryptopay.transfer(user_id=user_id, asset="USDT", amount=amount,
                                                    spend_id=str(uuid.uuid4()))

                # Отправка сообщения пользователю
                await message.answer(f"🏦 Средства в размере {amount:.2f} USDT были успешно отправлены вам.", reply_markup=keyboard.main_menu_markup)

                # Логирование действия
                log_action(user_id, "Withdraw", amount)

                # Уведомление администраторов
                await notify_admins(f"🏦 Вывод средств:\n\nПользователь ID: {user_id}\nСумма: {amount:.2f} USDT")
            else:
                # В случае недостатка средств у бота не списываем средства с базы данных
                invoice = await cryptopay.create_invoice(asset='USDT', amount=amount - usdt_balance)
                await message.answer("🚫 На счету приложения недостаточно средств для проведения операции.",
                                     reply_markup=keyboard.main_menu_markup)
                await notify_admins(f"🏦 ПОПОЛНИ СУКА КАЗНУ!!! \n"
                                    f"НА КАЗНЕ {round(usdt_balance, 1)} USDT\n"
                                    f"Не хватает {round(amount - usdt_balance, 1)} USDT\n"
                                    f"{invoice.mini_app_invoice_url}")
        else:
            await message.answer("🚫 На вашем балансе недостаточно средств для вывода.",
                                 reply_markup=keyboard.main_menu_markup)
    else:
        await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.",
                             reply_markup=types.ReplyKeyboardRemove())


##reply_markup=types.ReplyKeyboardRemove()

# Админ-панель
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    admin_id = config.admin_id
    if message.from_user.id == admin_id:
        markup = InlineKeyboardMarkup(inline_keyboard=[

            [InlineKeyboardButton(text="👥 Показать всех пользователей 📋", callback_data="show_users")],
            [InlineKeyboardButton(text="💵 Добавить средства пользователю 💳", callback_data="add_funds")],
            [InlineKeyboardButton(text="📊 Статистика казино 📈", callback_data="casino_stats")],
            [InlineKeyboardButton(text="💰 Пополнение казны 🏦", callback_data="replenish_treasure")]

        ])
        await message.answer("⚙️ Админ-панель:", reply_markup=markup)
    else:
        await message.answer("🚫 У вас нет прав доступа к админ-панели.")


@dp.callback_query(lambda c: c.data == "show_users")
async def show_users(callback_query: types.CallbackQuery):
    admin_id = config.admin_id
    if callback_query.from_user.id == admin_id:
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()
        user_list = "\n".join([f"User ID: {user[0]}, Balance: {user[1]} USDT" for user in users])
        await bot.send_message(admin_id, f"📄 Список всех пользователей:\n\n{user_list}")
        await callback_query.answer("💰 Сообщение с информацией отправлено в лс.")
    else:
        await callback_query.answer("🚫 У вас нет прав доступа к админ-панели.")
    await callback_query.answer()


@dp.callback_query(lambda c: c.data == "casino_stats")
async def casino_stats(callback_query: types.CallbackQuery):
    conn2 = sqlite3.connect('casino_log.db')
    cursor2 = conn2.cursor()
    admin_id = config.admin_id
    if callback_query.from_user.id == admin_id:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor2.execute("SELECT sum(amount) FROM logs WHERE action='Deposit' AND DATE(timestamp) = ?", (today,))
        daily_deposit = cursor2.fetchone()[0] or 0.0

        cursor2.execute("SELECT sum(amount) FROM logs WHERE action='Withdraw' AND DATE(timestamp) = ?", (today,))
        daily_withdrawal = cursor2.fetchone()[0] or 0.0

        cursor.execute("SELECT sum(balance) FROM users")
        total_user_balance = cursor.fetchone()[0] or 0.0

        cursor2.execute("SELECT sum(amount) FROM logs WHERE action='Deposit'")
        total_deposits = cursor2.fetchone()[0] or 0.0

        cursor2.execute("SELECT sum(amount) FROM logs WHERE action='Withdraw'")
        total_withdrawals = cursor2.fetchone()[0] or 0.0
        app_balance = await cryptopay.get_balance()
        usdt_balance = get_balance('USDT', app_balance)

        message = (
            f"📊 Статистика казино:\n\n"
            f"📅 Дневная статистика ({today}):\n"
            f"💵 Пополнения: {daily_deposit:.2f} USDT\n"
            f"💸 Выводы: {daily_withdrawal:.2f} USDT\n"
            f"📊 Прибыль за день {daily_deposit - daily_withdrawal:.2f}\n"
            f"📈 Общая статистика:\n"
            f"💰 Баланс пользователей: {total_user_balance:.2f} USDT\n"
            f"💵 Всего пополнений: {total_deposits:.2f} USDT\n"
            f"💸 Всего выводов: {total_withdrawals:.2f} USDT\n\n"
            f"💸 Баланс казино: {usdt_balance:.2f} $"
        )
        await bot.send_message(admin_id, message)
        await callback_query.answer("💰 Сообщение с информацией отправлено в лс.")
    else:
        await callback_query.answer("🚫 У вас нет прав доступа к админ-панели.")
    await callback_query.answer()


@dp.callback_query(lambda c: c.data == "replenish_treasure")
async def replenish_treasure(callback_query: types.CallbackQuery):
    admin_id = config.admin_id
    if callback_query.from_user.id == admin_id:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💵 Пополнить на 500 USDT", callback_data="replenish_500")],
            [InlineKeyboardButton(text="💴 Пополнить на 1000 USDT", callback_data="replenish_1000")],
            [InlineKeyboardButton(text="💰 Пополнить на 5000 USDT", callback_data="replenish_5000")],
            [InlineKeyboardButton(text="🏦 Пополнить на 10000 USDT", callback_data="replenish_10000")]
        ])

        await bot.send_message(admin_id, "💰 Выберите сумму для пополнения казны:", reply_markup=markup)


@dp.callback_query(lambda c: c.data.startswith("replenish_"))
async def process_replenish(callback_query: types.CallbackQuery):
    admin_id = config.admin_id
    if callback_query.from_user.id == admin_id:
        amount = int(callback_query.data.split("_")[1])
        app_balance = await cryptopay.get_balance()
        usdt_balance = get_balance('USDT', app_balance)

        if usdt_balance >= amount:
            # Добавляем средства в базу данных
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id IS NOT NULL", (amount,))
            conn.commit()

            # Логируем пополнение
            log_action(admin_id, "Treasury Replenish", amount)

            invoice = await cryptopay.create_invoice(asset='USDT', amount=amount)

            await bot.send_message(admin_id, f"💰 Оплатите пополнение на {amount:.2f} USDT.\n"
                                             f"{invoice.mini_app_invoice_url}")
            await notify_admins(f"💰 Казна пополнена администратором:\n\nСумма: {amount:.2f} USDT")
        else:
            await bot.send_message(admin_id, "🚫 На счету приложения недостаточно средств для проведения операции.")
            invoice = await cryptopay.create_invoice(asset='USDT', amount=amount - usdt_balance)
            await bot.send_message(admin_id, f"🔗 Счёт для пополнения казны:\n{invoice.mini_app_invoice_url}")


    await callback_query.answer()


@dp.message(Command("help"))
async def help_command(message: Message):
    help_text = (
        "ℹ️ Помощь по игре\n\n"
        "1. /play - Начать игру в кубик.\n\n"
        "2. Выбор режима игры:\n"
        "   - Чет/Нечет: Выберите, хотите ли вы ставить на четное или нечетное число. Если число совпадает с вашим выбором, вы выиграете ставку.\n"
        "   - Больше/Меньше: Выберите, хотите ли вы ставить на то, что выпадет число 4 или выше, или 3 и ниже. Если ваше предположение верно, вы выиграете ставку.\n\n"
        "3. Ставка:\n"
        "   - Выберите сумму ставки из предложенных вариантов (1 USDT, 5 USDT, 10 USDT).\n\n"
        "4. Баланс:\n"
        "   - Ваш баланс обновляется после каждой игры. Выигрыши добавляются к вашему балансу, а проигрыши вычитаются.\n\n"
        "📊 Команды:\n"
        "   - /profile: Просмотреть информацию о вашем профиле и текущем балансе.\n /deposit: Пополнить баланс \n /outbalance - Вывод средств"
        "   - /help: Получить помощь и инструкции по игре.\n\n"
        "❓ Если у вас есть вопросы, не стесняйтесь спрашивать!"
    )
    await message.answer(help_text)


@dp.message(Command("profile"))
async def profile(message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name or ""
    username = message.from_user.username or "Не задан"

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user:
        balance = user[0]
        await message.answer(
            f"👤 Ваш профиль\n\n"
            f"🆔 ID: {user_id}\n"
            f"👤 Имя: {first_name} {last_name}\n"
            f"📛 Юзернейм: @{username}\n"
            f"💰 Баланс: {balance} USDT"
        )
    else:
        await message.answer("🚫 Вы не зарегистрированы. Используйте /start для регистрации.")


async def notify_win(user_name: str, win_amount: float, game_mode: str):
    win_chat_id = config.win_id

    messages = [
        f"🎉 Пользователь @{user_name} только что выиграл {win_amount:.1f} USDT! 🏆 В игре {game_mode} 🎲\nПопробуй и ты @{config.BOT_USERNAME}",
        f"👏 Поздравляем @{user_name}! Вы выиграли {win_amount:.1f} USDT в {game_mode}! 💵\nСделай ставку и ты @{config.BOT_USERNAME}!",
        f"🌟 @{user_name} получил выигрыш в размере {win_amount:.1f} USDT в игре {game_mode}! 🤑\nНе упусти шанс! @{config.BOT_USERNAME}",
        f"🥳 Отличная новость! @{user_name} выиграл {win_amount:.1f} USDT в {game_mode}! 🎊\nПрисоединяйтесь к нам, @{config.BOT_USERNAME}!",
        f"🎈 @{user_name} выигрывает {win_amount:.1f} USDT в {game_mode}! 🎉\nПроверь свои шансы @{config.BOT_USERNAME}!",
        f"🚀 @{user_name} выиграл {win_amount:.1f} USDT в {game_mode}! 💰\nПопробуй свою удачу, @{config.BOT_USERNAME}!",
        f"🔥 @{user_name} забирает {win_amount:.1f} USDT в игре {game_mode}! 💥\nСтавь и выигрывай @{config.BOT_USERNAME}!",
        f"💎 @{user_name} только что выиграл {win_amount:.1f} USDT! 🏅 В {game_mode} 🌟\nПопробуй и ты, @{config.BOT_USERNAME}!",
        f"🎲 @{user_name} выиграл {win_amount:.1f} USDT! 💸 В игре {game_mode} 🎉\nСтань следующим победителем @{config.BOT_USERNAME}!",
        f"🍾 @{user_name} получает {win_amount:.1f} USDT за победу в {game_mode}! 🎁\nСделай свою ставку @{config.BOT_USERNAME}!",
        f"🏅 @{user_name} выиграл {win_amount:.1f} USDT в {game_mode}! 🎉\nПроверь свои шансы, @{config.BOT_USERNAME}!",
        f"🎉 @{user_name} выиграл {win_amount:.1f} USDT в {game_mode}! 🌟\nПопробуй свою удачу, @{config.BOT_USERNAME}!",
        f"✨ Ура! @{user_name} забирает {win_amount:.1f} USDT за победу в {game_mode}! 🎉\nНе упусти свой шанс @{config.BOT_USERNAME}!",
        f"🏆 @{user_name} выигрывает {win_amount:.1f} USDT в {game_mode}! 🎲\nПрисоединяйся к нам, @{config.BOT_USERNAME}!",
        f"💸 @{user_name} только что выиграл {win_amount:.1f} USDT! 🎊 В {game_mode} 🎉\nПопробуй и ты, @{config.BOT_USERNAME}!",
        f"🎈 @{user_name} выиграл {win_amount:.1f} USDT в {game_mode}! 🌟\nПопробуй свою удачу @{config.BOT_USERNAME}!",
        f"🌟 Поздравляем @{user_name}! Вы выиграли {win_amount:.1f} USDT в {game_mode}! 💰\nПрисоединяйся к нам @{config.BOT_USERNAME}!",
        f"🎊 @{user_name} только что выиграл {win_amount:.1f} USDT! 🚀 В {game_mode} 🌟\nПопробуй и ты, @{config.BOT_USERNAME}!",
        f"🎉 @{user_name} выигрывает {win_amount:.1f} USDT в {game_mode}! 🏆\nСделай свою ставку @{config.BOT_USERNAME}!",
        f"💰 @{user_name} выиграл {win_amount:.1f} USDT в {game_mode}! 🎈\nПопробуй свою удачу @{config.BOT_USERNAME}!",
        f"🥳 Поздравляем @{user_name}! Вы выиграли {win_amount:.1f} USDT в {game_mode}! 🎉\nНе упусти шанс @{config.BOT_USERNAME}!",
        f"🎉 @{user_name} получает {win_amount:.1f} USDT за победу в {game_mode}! 🏅\nПопробуй свою удачу @{config.BOT_USERNAME}!"
    ]

    # Выбираем случайное сообщение из списка
    ran = random.randint(0, 19)
    text = messages[ran]
    message = random.choice(messages).format(user_name=user_name, win_amount=win_amount, game_mode=game_mode)
    await bot.send_message(chat_id=win_chat_id, text=text)


app_balance = cryptopay.get_balance()


def get_balance(currency_code, balances):
    for balance in balances:
        if balance.currency_code == currency_code:
            return float(balance.available)  # Преобразование в float
    return None  # если валюты нет в списке


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
