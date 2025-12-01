import asyncio
import logging
import random
import string
import sqlite3
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN
from database import Database
from utils import generate_movie_recommendations

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Инициализация базы данных
db = Database()


# Определяем состояния
class UserStates(StatesGroup):
    waiting_for_partner = State()
    entering_code = State()


class QuestionStates(StatesGroup):
    genre = State()
    favorite_movies = State()
    mood = State()
    duration = State()
    year = State()
    additional = State()


# Вопросы для опроса
QUESTIONS = [
    ("genre", "Какие жанры фильмов вы предпочитаете?\n(например: комедия, фантастика, драма, боевик)"),
    ("favorite_movies", "Какие ваши любимые фильмы?\n(назовите 2-3 фильма, которые вам особенно нравятся)"),
    ("mood",
     "Какое у вас сегодня настроение для просмотра?\n(например: веселое, романтическое, напряженное, расслабленное)"),
    ("duration",
     "Какую длительность фильма предпочитаете?\n(например: короткий до 90 мин, стандартный 90-120 мин, длинный 120+ мин)"),
    ("year", "Фильмы какого периода вас интересуют?\n(например: классика 70-90х, современные 2000+, новинки)"),
    ("additional",
     "Есть ли дополнительные пожелания?\n(например: без ужасов, хочу что-то легкое, интересные диалоги)")
]


# REPLY-КЛАВИАТУРЫ (кнопки под строкой ввода)

def get_main_keyboard():
    """Основная клавиатура меню"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Создать сессию"), KeyboardButton(text="🔗 Присоединиться")],
            [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="📊 Мои сессии")]
        ],
        resize_keyboard=True,  # Адаптируется под размер экрана
        one_time_keyboard=False,  # Не скрывается после нажатия
        input_field_placeholder="Выберите действие 👇"
    )


def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def get_back_keyboard():
    """Клавиатура с кнопкой назад"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def get_skip_keyboard():
    """Клавиатура для пропуска вопроса"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭️ Пропустить")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def generate_session_code():
    """Генерация 6-значного кода сессии"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


async def start_questions_for_user(user_id: int, session_code: str, username: str = None):
    """Запуск вопросов для пользователя"""
    from aiogram.fsm.storage.base import StorageKey
    storage_key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    user_state = FSMContext(storage=storage, key=storage_key)

    await user_state.set_state(QuestionStates.genre)
    await user_state.update_data(
        session_code=session_code,
        current_question=0,
        answers={},
        partner_username=username
    )

    # Отправляем первый вопрос
    question_num = 1
    question_text = QUESTIONS[0][1]

    greeting = ""
    if username:
        greeting = f"🎉 К вам присоединился @{username}!\n\n"

    await bot.send_message(
        user_id,
        f"{greeting}🎬 Давайте начнем подбор фильмов!\n\n"
        f"Введите любой текст, для готовности",
        reply_markup=get_skip_keyboard()
    )


async def ask_next_question(user_id: int, state: FSMContext):
    """Задать следующий вопрос"""
    data = await state.get_data()
    current_question = data.get('current_question', 0)
    session_code = data.get('session_code')

    if current_question < len(QUESTIONS):
        question_key, question_text = QUESTIONS[current_question]

        # Отправляем вопрос с прогрессом
        progress = f"({current_question + 1}/{len(QUESTIONS)})"
        await bot.send_message(
            user_id,
            f"{progress} {question_text}",
            reply_markup=get_skip_keyboard()
        )

        # Обновляем счетчик
        await state.update_data(current_question=current_question + 1)
        return True
    else:
        # Все вопросы отвечены
        answers = data.get('answers', {})
        db.save_user_answers(session_code, user_id, answers)

        await bot.send_message(
            user_id,
            "✅ Спасибо! Ваши ответы сохранены. Ждем ответы второго пользователя...",
            reply_markup=ReplyKeyboardRemove()
        )

        # Проверяем, ответил ли партнер
        user1_answers, user2_answers = db.get_both_answers(session_code)

        if user1_answers and user2_answers:
            await generate_and_send_recommendations(session_code, user1_answers, user2_answers)
            db.complete_session(session_code)

            # Очищаем состояния
            session = db.get_session(session_code)
            if session:
                for uid in [session[1], session[2]]:
                    if uid:
                        storage_key = StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid)
                        user_state = FSMContext(storage=storage, key=storage_key)
                        await user_state.clear()

                        # Отправляем главное меню
                        await bot.send_message(
                            uid,
                            "🎬 Хотите подобрать еще фильмы?",
                            reply_markup=get_main_keyboard()
                        )

        return False


# ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    db.add_user(user_id, username, first_name)

    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        "🎥 Добро пожаловать в бота для поиска фильмов!\n\n"
        "Я помогу вам и вашему другу выбрать фильм, который понравится обоим.\n"
        "Создайте сессию и поделитесь кодом с другом, чтобы начать подбор фильмов!",
        reply_markup=get_main_keyboard()
    )


@router.message(F.text == "ℹ️ Помощь")
@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик помощи"""
    help_text = """
🤖 !! Как использовать бота: !!

1. 🎬 Создать сессию
   • Нажмите "Создать сессию"
   • Получите 6-значный код
   • Поделитесь кодом с другом

2. 🔗 Присоединиться
   • Нажмите "Присоединиться"
   • Введите код от друга
   • Начните опрос

3. 📊 Мои сессии
   • Показывает ваши активные сессии
   • Показывает код для присоединения

4. ⏭️ Пропустить
   • Можно пропустить любой вопрос
   • Бот учтет это при подборе

🎬 Процесс:
1. Оба участника отвечают на 6 вопросов
2. ИИ анализирует ваши предпочтения
3. Вы получаете персонализированную подборку фильмов

🍿 Приятного просмотра!
"""
    await message.answer(help_text, reply_markup=get_main_keyboard())


@router.message(F.text == "🎬 Создать сессию")
async def create_session(message: Message, state: FSMContext):
    """Создание новой сессии"""
    user_id = message.from_user.id
    session_code = generate_session_code()

    # Проверяем, нет ли активной сессии
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute('SELECT session_id FROM sessions WHERE user1_id = ? AND status != "completed"', (user_id,))
    active_session = cursor.fetchone()
    conn.close()

    if active_session:
        await message.answer(
            f"⚠️ У вас уже есть активная сессия!\n\n"
            f"Код: `{active_session[0]}`\n\n"
            f"Дождитесь присоединения участника или отмените сессию.",
            reply_markup=get_main_keyboard()
        )
        return

    # Создаем сессию
    db.create_session(session_code, user_id)

    await state.set_state(UserStates.waiting_for_partner)
    await state.update_data(session_code=session_code)

    await message.answer(
        f"✅ Сессия создана!\n\n"
        f"🎯 Код сессии: {session_code}\n\n\n"
        f"📋 Что делать дальше: \n"
        f"1. Поделитесь этим кодом с другом\n"
        f"2. Друг нажимает \"Присоединиться\" и вводит код\n"
        f"3. Оба начинаете отвечать на вопросы\n\n"
        f"⏰ Код действителен 1 час",
        reply_markup=get_cancel_keyboard()
    )

    # Запускаем таймер для удаления просроченной сессии
    asyncio.create_task(delete_expired_session(session_code))


@router.message(F.text == "🔗 Присоединиться")
async def join_session_prompt(message: Message, state: FSMContext):
    """Запрос кода сессии для присоединения"""
    await state.set_state(UserStates.entering_code)

    await message.answer(
        "🔢 Присоединение к сессии\n\n"
        "Введите 6-значный код сессии, который вам отправил друг:\n\n"
        "Пример: `A1B2C3`",
        reply_markup=get_cancel_keyboard()
    )


@router.message(F.text == "❌ Отмена")
async def cancel_operation(message: Message, state: FSMContext):
    """Отмена текущей операции"""
    data = await state.get_data()
    session_code = data.get('session_code')

    current_state = await state.get_state()

    if current_state == UserStates.waiting_for_partner and session_code:
        # Удаляем сессию из БД
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_code,))
        conn.commit()
        conn.close()

        await message.answer(
            "❌ Сессия отменена.\n\n"
            "Вы можете создать новую сессию.",
            reply_markup=get_main_keyboard()
        )
    elif current_state == UserStates.entering_code:
        await message.answer(
            "❌ Ввод кода отменен.",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "❌ Действие отменено.",
            reply_markup=get_main_keyboard()
        )

    await state.clear()


@router.message(F.text == "🔙 Назад")
async def back_to_menu(message: Message, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    await message.answer(
        "🔙 Возвращаемся в главное меню...",
        reply_markup=get_main_keyboard()
    )


@router.message(F.text == "📊 Мои сессии")
async def show_my_sessions(message: Message):
    """Показать активные сессии пользователя"""
    user_id = message.from_user.id

    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()

    # Сессии, где пользователь создатель
    cursor.execute('''
        SELECT session_id, status, user2_id, created_at 
        FROM sessions 
        WHERE user1_id = ? AND status != "completed"
    ''', (user_id,))

    creator_sessions = cursor.fetchall()

    # Сессии, где пользователь участник
    cursor.execute('''
        SELECT session_id, status, user1_id, created_at 
        FROM sessions 
        WHERE user2_id = ? AND status != "completed"
    ''', (user_id,))

    participant_sessions = cursor.fetchall()

    conn.close()

    response = "📊 !! Ваши активные сессии !!\n\n"

    if not creator_sessions and not participant_sessions:
        response += "У вас нет активных сессий.\nСоздайте новую сессию!"
    else:
        if creator_sessions:
            response += "👑 **Вы создатель:**\n"
            for session in creator_sessions:
                session_code, status, user2_id, created_at = session
                if user2_id:
                    response += f"• Код: `{session_code}` - участник подключен ✅\n"
                else:
                    response += f"• Код: `{session_code}` - ожидание участника ⏳\n"
            response += "\n"

        if participant_sessions:
            response += "👤 **Вы участник:**\n"
            for session in participant_sessions:
                session_code, status, user1_id, created_at = session
                response += f"• Код: `{session_code}` - активна\n"

    await message.answer(response, reply_markup=get_main_keyboard())


@router.message(F.text == "⏭️ Пропустить")
async def skip_question(message: Message, state: FSMContext):
    """Пропуск текущего вопроса"""
    current_state = await state.get_state()

    if current_state and "QuestionStates" in str(current_state):
        data = await state.get_data()
        current_question_idx = data.get('current_question', 1) - 1
        answers = data.get('answers', {})

        if current_question_idx < len(QUESTIONS):
            question_key, _ = QUESTIONS[current_question_idx]
            answers[question_key] = "не указано"
            await state.update_data(answers=answers)

            await message.answer(
                f"⏭️ Вопрос пропущен.",
                reply_markup=get_skip_keyboard()
            )

            await ask_next_question(message.from_user.id, state)


@router.message(UserStates.entering_code)
async def process_session_code(message: Message, state: FSMContext):
    """Обработка введенного кода сессии"""
    session_code = message.text.strip().upper()

    # Проверяем формат кода
    if len(session_code) != 6 or not session_code.isalnum():
        await message.answer(
            "❌ Неверный формат кода.\n\n"
            "Код должен состоять из 6 букв и цифр.\n"
            "Пример: `A1B2C3`\n\n"
            "Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )
        return

    # Проверяем существование сессии
    session = db.get_session(session_code)

    if not session:
        await message.answer(
            "❌ Сессия не найдена.\n\n"
            "Проверьте код или создайте новую сессию.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()
        return

    if session[2] is not None:  # Если уже есть второй участник
        await message.answer(
            "❌ В этой сессии уже есть два участника.\n\n"
            "Создайте новую сессию или присоединитесь к другой.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()
        return

    if session[1] == message.from_user.id:  # Если пользователь пытается присоединиться к своей же сессии
        await message.answer(
            "❌ Вы не можете присоединиться к своей собственной сессии.\n\n"
            "Ожидайте присоединения друга.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()
        return

    # Присоединяем пользователя к сессии
    user2_id = message.from_user.id
    db.join_session(session_code, user2_id)
    db.add_user(user2_id, message.from_user.username, message.from_user.first_name)

    # ЗАПУСКАЕМ ОПРОС ДЛЯ ОБОИХ ПОЛЬЗОВАТЕЛЕЙ

    # 1. Для присоединившегося пользователя (user2)
    await state.clear()  # Очищаем состояние ввода кода
    await start_questions_for_user(
        user2_id,
        session_code,
        username=None
    )

    # 2. Для создателя сессии (user1)
    creator_id = session[1]
    await start_questions_for_user(
        creator_id,
        session_code,
        username=message.from_user.username or "друг"
    )


# Обработчики ответов на вопросы
@router.message(QuestionStates.genre)
async def process_genre(message: Message, state: FSMContext):
    """Обработка ответа на вопрос о жанрах"""
    if message.text == "⏭️ Пропустить":
        await skip_question(message, state)
        return

    data = await state.get_data()
    answers = data.get('answers', {})
    answers['genre'] = message.text
    await state.update_data(answers=answers)
    await ask_next_question(message.from_user.id, state)


@router.message(QuestionStates.favorite_movies)
async def process_favorite_movies(message: Message, state: FSMContext):
    """Обработка ответа на вопрос о любимых фильмах"""
    if message.text == "⏭️ Пропустить":
        await skip_question(message, state)
        return

    data = await state.get_data()
    answers = data.get('answers', {})
    answers['favorite_movies'] = message.text
    await state.update_data(answers=answers)
    await ask_next_question(message.from_user.id, state)


@router.message(QuestionStates.mood)
async def process_mood(message: Message, state: FSMContext):
    """Обработка ответа на вопрос о настроении"""
    if message.text == "⏭️ Пропустить":
        await skip_question(message, state)
        return

    data = await state.get_data()
    answers = data.get('answers', {})
    answers['mood'] = message.text
    await state.update_data(answers=answers)
    await ask_next_question(message.from_user.id, state)


@router.message(QuestionStates.duration)
async def process_duration(message: Message, state: FSMContext):
    """Обработка ответа на вопрос о длительности"""
    if message.text == "⏭️ Пропустить":
        await skip_question(message, state)
        return

    data = await state.get_data()
    answers = data.get('answers', {})
    answers['duration'] = message.text
    await state.update_data(answers=answers)
    await ask_next_question(message.from_user.id, state)


@router.message(QuestionStates.year)
async def process_year(message: Message, state: FSMContext):
    """Обработка ответа на вопрос о годе выпуска"""
    if message.text == "⏭️ Пропустить":
        await skip_question(message, state)
        return

    data = await state.get_data()
    answers = data.get('answers', {})
    answers['year'] = message.text
    await state.update_data(answers=answers)
    await ask_next_question(message.from_user.id, state)


@router.message(QuestionStates.additional)
async def process_additional(message: Message, state: FSMContext):
    """Обработка ответа на дополнительный вопрос"""
    if message.text == "⏭️ Пропустить":
        await skip_question(message, state)
        return

    data = await state.get_data()
    answers = data.get('answers', {})
    answers['additional'] = message.text
    await state.update_data(answers=answers)
    await ask_next_question(message.from_user.id, state)


async def generate_and_send_recommendations(session_code: str, user1_answers: dict, user2_answers: dict):
    """Генерация и отправка рекомендаций"""
    session = db.get_session(session_code)
    if not session:
        return

    user1_id, user2_id = session[1], session[2]

    generating_msg = "🎭 Анализируем ваши предпочтения... ИИ подбирает идеальные фильмы!\n\nЭто может занять 10-15 секунд ⏳"

    try:
        msg1 = await bot.send_message(user1_id, generating_msg)
        msg2 = await bot.send_message(user2_id, generating_msg)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщения: {e}")
        return

    recommendations = await generate_movie_recommendations(user1_answers, user2_answers)

    result_text = f"""
{recommendations}
    """

    try:
        await bot.edit_message_text(
            result_text,
            chat_id=user1_id,
            message_id=msg1.message_id,
            parse_mode='Markdown'
        )
        await bot.edit_message_text(
            result_text,
            chat_id=user2_id,
            message_id=msg2.message_id,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Не удалось отправить рекомендации: {e}")
        try:
            await bot.send_message(user1_id, result_text, parse_mode='Markdown')
            await bot.send_message(user2_id, result_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Не удалось отправить новые сообщения: {e}")


async def delete_expired_session(session_code: str, delay_seconds: int = 3600):
    """Удаление просроченной сессии"""
    await asyncio.sleep(delay_seconds)

    session = db.get_session(session_code)
    if session and session[2] is None:
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_code,))
        conn.commit()
        conn.close()

        try:
            await bot.send_message(
                session[1],
                "⏰ Время сессии истекло. Никто не присоединился.\n\n"
                "Создайте новую сессию!",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить: {e}")


# Обработчик любых других сообщений
@router.message()
async def handle_other_messages(message: Message, state: FSMContext):
    """Обработчик всех остальных сообщений"""
    current_state = await state.get_state()

    if current_state is None:
        # Если пользователь просто что-то пишет без контекста
        await message.answer(
            "👋 Не понял ваше сообщение.\n\n"
            "Используйте кнопки меню для навигации:",
            reply_markup=get_main_keyboard()
        )
    else:
        # Если пользователь в каком-то состоянии, но отправил что-то не то
        await message.answer(
            "⚠️ Пожалуйста, используйте кнопки для ответа.",
            reply_markup=get_skip_keyboard() if "QuestionStates" in str(current_state) else get_cancel_keyboard()
        )


async def main():
    """Основная функция"""
    logger.info("🎬 Movie Match Bot запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())