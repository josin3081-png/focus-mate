import json
import os
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from io import BytesIO
from unittest.mock import patch

import app as assistant_app
from app import app, answer_local_knowledge, answer_from_configured_provider, build_assistant_answer, get_db


class PasswordResetFlowTest(unittest.TestCase):
    def setUp(self):
        self.original_database = assistant_app.DATABASE
        self.temporary_directory = TemporaryDirectory()
        assistant_app.DATABASE = Path(self.temporary_directory.name) / 'test-assistant.db'
        assistant_app.init_db()
        app.config['TESTING'] = True
        self.client = app.test_client()
        self.email = 'alice@example.com'

        with closing(get_db()) as connection:
            connection.execute('DELETE FROM tasks')
            connection.execute('DELETE FROM users')
            connection.commit()

    def tearDown(self):
        assistant_app.DATABASE = self.original_database
        self.temporary_directory.cleanup()

    def test_forgot_password_and_reset_flow(self):
        register_response = self.client.post(
            '/register',
            data={'name': 'Alice', 'email': self.email, 'password': 'strongpass'},
            follow_redirects=False,
        )
        self.assertEqual(register_response.status_code, 302)

        forgot_response = self.client.post(
            '/forgot_password',
            data={'email': self.email},
            follow_redirects=True,
        )
        self.assertIn(b'OTP', forgot_response.data)

        with closing(get_db()) as connection:
            row = connection.execute(
                'SELECT otp_code FROM users WHERE email = ?',
                (self.email,),
            ).fetchone()
            otp_code = row['otp_code'] if row else None

        self.assertIsNotNone(otp_code)
        self.assertEqual(len(otp_code), 6)

        reset_response = self.client.post(
            '/reset_password',
            data={'email': self.email, 'otp': otp_code, 'new_password': 'newstrongpass'},
            follow_redirects=True,
        )
        self.assertIn(b'Password reset', reset_response.data)

        login_response = self.client.post(
            '/login',
            data={'email': self.email, 'password': 'newstrongpass'},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)

    def test_registered_account_can_log_in_again_using_persistent_database(self):
        register_response = self.client.post(
            '/register',
            data={'name': 'Alice', 'email': 'Alice@example.com', 'password': 'strongpass'},
        )
        self.assertEqual(register_response.status_code, 302)

        self.client.get('/logout')
        login_response = self.client.post(
            '/login',
            data={'email': ' ALICE@EXAMPLE.COM ', 'password': 'strongpass'},
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertIn('/dashboard', login_response.headers['Location'])

    def test_health_check_reports_absolute_database_path(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['database'], str(assistant_app.DATABASE.resolve()))

    def test_assistant_answers_questions(self):
        register_response = self.client.post(
            '/register',
            data={'name': 'Alice', 'email': 'assistant@example.com', 'password': 'strongpass'},
            follow_redirects=False,
        )
        self.assertEqual(register_response.status_code, 302)

        response = self.client.post(
            '/api/assistant',
            json={'question': 'What should I focus on today?'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('focus', response.get_json()['answer'].lower())

    def test_dashboard_includes_spoken_reply_controls(self):
        self.client.post(
            '/register',
            data={'name': 'Alice', 'email': 'voice@example.com', 'password': 'strongpass'},
        )
        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="voice-reply-toggle"', response.data)
        self.assertIn(b'id="speak-button"', response.data)
        self.assertIn(b'id="assistant-voice-select"', response.data)

    def test_assistant_calculates_from_the_api(self):
        self.client.post(
            '/register',
            data={'name': 'Alice', 'email': 'math@example.com', 'password': 'strongpass'},
        )
        response = self.client.post('/api/assistant', json={'question': 'What is 12 * (3 + 2)?'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['answer'], 'The answer is 60.')

    def test_assistant_can_create_and_complete_a_task(self):
        self.client.post(
            '/register',
            data={'name': 'Alice', 'email': 'task-command@example.com', 'password': 'strongpass'},
        )

        create_response = self.client.post(
            '/api/assistant',
            json={'question': 'Add a task to prepare the launch notes'},
        )
        self.assertEqual(create_response.status_code, 200)
        created = create_response.get_json()
        self.assertEqual(created['action'], 'created')
        self.assertEqual(created['task']['title'], 'prepare the launch notes')

        complete_response = self.client.post(
            '/api/assistant',
            json={'question': 'Mark prepare the launch notes as done'},
        )
        self.assertEqual(complete_response.status_code, 200)
        completed = complete_response.get_json()
        self.assertEqual(completed['action'], 'completed')
        self.assertEqual(completed['task']['id'], created['task']['id'])
        self.assertEqual(completed['task']['completed'], 1)

        with closing(get_db()) as connection:
            row = connection.execute(
                'SELECT completed FROM tasks WHERE id = ?',
                (created['task']['id'],),
            ).fetchone()
        self.assertEqual(row['completed'], 1)

    def test_assistant_cannot_complete_another_users_task(self):
        self.client.post(
            '/register',
            data={'name': 'Alice', 'email': 'task-owner@example.com', 'password': 'strongpass'},
        )
        created = self.client.post(
            '/api/assistant',
            json={'question': 'Add task to send the private report'},
        ).get_json()['task']

        self.client.get('/logout')
        self.client.post(
            '/register',
            data={'name': 'Bob', 'email': 'other-user@example.com', 'password': 'strongpass'},
        )
        response = self.client.post(
            '/api/assistant',
            json={'question': 'Complete send the private report'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('action', response.get_json())
        with closing(get_db()) as connection:
            row = connection.execute(
                'SELECT completed FROM tasks WHERE id = ?',
                (created['id'],),
            ).fetchone()
        self.assertEqual(row['completed'], 0)

    def test_assistant_answers_math_and_common_knowledge_locally(self):
        self.assertEqual(answer_local_knowledge('What is 12 * (3 + 2)?'), 'The answer is 60.')
        self.assertIn('high-level', answer_local_knowledge('What is Python?'))
        self.assertIsNone(answer_local_knowledge('__import__("os").system("whoami")'))

    def test_assistant_calculates_natural_language_operations_and_percentages(self):
        examples = {
            'What is 12 plus 5?': 'The answer is 17.',
            'Subtract 5 from 20': 'The answer is 15.',
            'Multiply 6 by 7': 'The answer is 42.',
            'What is 20 divided by 4?': 'The answer is 5.',
            'What is 15% of 200?': 'The answer is 30.',
            'Calculate 25 percent of 80': 'The answer is 20.',
            'What percentage is 15 of 60?': 'The answer is 25.',
            'What percent is 15 of 60?': 'The answer is 25.',
            '15 is what percentage of 60?': 'The answer is 25.',
            'Calculate percentage increase from 80 to 100': 'The answer is 25.',
            'Calculate percent decrease from 100 to 80': 'The answer is 20.',
            'What is 18 ÷ 3?': 'The answer is 6.',
        }
        for question, expected in examples.items():
            with self.subTest(question=question):
                self.assertEqual(answer_local_knowledge(question), expected)

    def test_assistant_answers_everyday_world_knowledge_locally(self):
        self.assertIn('two hydrogen atoms and one oxygen atom', answer_local_knowledge('What is water made of?'))
        self.assertIn('seven continents', answer_local_knowledge('How many continents are there?'))
        self.assertIn('mostly nitrogen', answer_local_knowledge('What is air made of?'))
        self.assertIn('air molecules scatter shorter-wavelength blue sunlight', answer_local_knowledge('Why is the sky blue?'))

    def test_assistant_greeting_and_local_time_follow_current_hour(self):
        morning = datetime(2026, 9, 29, 8, 5).astimezone()
        evening = datetime(2026, 9, 29, 20, 5).astimezone()
        self.assertIn('Good morning, Alice', build_assistant_answer('Hello', [], 'Alice', morning))
        self.assertIn('Good evening, Alice', build_assistant_answer('Hello', [], 'Alice', evening))
        self.assertEqual(
            build_assistant_answer('What time is it?', [], 'Alice', evening),
            'It is 8:05 PM in this app\'s local time zone.',
        )

    def test_unconfigured_assistant_provider_identifies_unanswered_question(self):
        with patch.dict(os.environ, {}, clear=True):
            answer = build_assistant_answer('Explain black holes', [], 'Alice')
        self.assertIn('Explain black holes', answer)
        self.assertIn('ASSISTANT_LLM_URL', answer)

    def test_general_knowledge_explains_provider_setup_when_unconfigured(self):
        with patch.dict(os.environ, {}, clear=True):
            answer = build_assistant_answer('Explain quantum computing', [], 'Alice')
        self.assertIn('ASSISTANT_LLM_URL', answer)

    def test_general_knowledge_uses_configured_provider(self):
        response = BytesIO(json.dumps({
            'choices': [{'message': {'content': 'Quantum computers use quantum states to process information.'}}]
        }).encode('utf-8'))
        with patch.dict(os.environ, {'ASSISTANT_LLM_URL': 'https://example.test/v1/chat/completions'}):
            with patch('app.urlopen', return_value=response):
                answer = answer_from_configured_provider('Explain quantum computing')
        self.assertEqual(answer, 'Quantum computers use quantum states to process information.')


if __name__ == '__main__':
    unittest.main()
