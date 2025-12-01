import sqlite3
import json


class Database:
    def __init__(self, db_path='movies.db'):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица сессий
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user1_id INTEGER,
                user2_id INTEGER,
                user1_answers TEXT,
                user2_answers TEXT,
                status TEXT DEFAULT 'waiting',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def add_user(self, user_id, username, first_name):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
        ''', (user_id, username, first_name))

        conn.commit()
        conn.close()

    def create_session(self, session_id, user1_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO sessions (session_id, user1_id, status)
            VALUES (?, ?, 'waiting')
        ''', (session_id, user1_id))

        conn.commit()
        conn.close()

    def join_session(self, session_id, user2_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE sessions 
            SET user2_id = ?, status = 'active'
            WHERE session_id = ? AND status = 'waiting'
        ''', (user2_id, session_id))

        conn.commit()
        conn.close()

    def save_user_answers(self, session_id, user_id, answers):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Определяем, какой это пользователь в сессии
        cursor.execute('SELECT user1_id, user2_id FROM sessions WHERE session_id = ?', (session_id,))
        session = cursor.fetchone()

        if session:
            user_field = 'user1_answers' if session[0] == user_id else 'user2_answers'
            answers_json = json.dumps(answers)

            cursor.execute(f'''
                UPDATE sessions 
                SET {user_field} = ?
                WHERE session_id = ?
            ''', (answers_json, session_id))

        conn.commit()
        conn.close()

    def get_session(self, session_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM sessions WHERE session_id = ?
        ''', (session_id,))

        session = cursor.fetchone()
        conn.close()
        return session

    def get_both_answers(self, session_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT user1_answers, user2_answers FROM sessions WHERE session_id = ?
        ''', (session_id,))

        result = cursor.fetchone()
        conn.close()

        if result and result[0] and result[1]:
            return json.loads(result[0]), json.loads(result[1])
        return None, None

    def complete_session(self, session_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE sessions 
            SET status = 'completed', finished_at = CURRENT_TIMESTAMP
            WHERE session_id = ?
        ''', (session_id,))

        conn.commit()
        conn.close()