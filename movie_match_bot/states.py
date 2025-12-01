from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    waiting_for_partner = State()
    entering_code = State()
    answering_questions = State()


class QuestionStates(StatesGroup):
    genre = State()
    favorite_movies = State()
    mood = State()
    duration = State()
    year = State()
    additional = State()