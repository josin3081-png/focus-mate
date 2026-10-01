import ast
import json
import math
import os
import operator
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "assistant.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("ASSISTANT_SECRET", "local-development-key-change-me")


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def generate_otp():
    return f"{secrets.randbelow(900000) + 100000:06d}"


def send_otp_email(email, otp):
    print(f"[Focusmate OTP] To: {email} | Code: {otp}")


def init_db():
    connection = get_db()
    existing_users = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
    if existing_users:
        user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        if "otp_code" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN otp_code TEXT DEFAULT NULL")
        if "otp_expires_at" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN otp_expires_at TEXT DEFAULT NULL")
    existing_tasks = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tasks'").fetchone()
    if existing_tasks:
        task_columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()}
        if "user_id" not in task_columns:
            connection.execute("ALTER TABLE tasks RENAME TO tasks_legacy")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            otp_code TEXT DEFAULT NULL,
            otp_expires_at TEXT DEFAULT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            detail TEXT DEFAULT '',
            due TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'normal',
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )
    connection.commit()
    connection.close()


init_db()


def logged_in(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_user():
    return {"current_user": session.get("user_name")}


@app.route("/")
def index():
    return redirect(url_for("dashboard" if "user_id" in session else "login"))


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(BASE_DIR, "focusmate.ico", mimetype="image/x-icon")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "database": str(DATABASE.resolve())})


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        connection = get_db()
        user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        connection.close()
        if not user or not check_password_hash(user["password"], password):
            error = "That email and password combination could not be verified."
        else:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
    return render_template("login.html", error=error, mode="login")


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            error = "Add your name, a valid email, and a password with 8+ characters."
        else:
            connection = get_db()
            try:
                cursor = connection.execute(
                    "INSERT INTO users (name, email, password, otp_code, otp_expires_at, created_at) VALUES (?, ?, ?, NULL, NULL, ?)",
                    (name, email, generate_password_hash(password), datetime.utcnow().isoformat()),
                )
                user_id = cursor.lastrowid
                starter_tasks = [
                    ("Plan the day", "Choose the three outcomes that matter most.", "09:00", "high"),
                    ("Deep work block", "Protect 90 minutes for your highest-impact work.", "11:30", "high"),
                    ("Review and reset", "Close loops and prepare tomorrow's first move.", "17:30", "normal"),
                ]
                connection.executemany(
                    "INSERT INTO tasks (user_id, title, detail, due, priority, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    [(user_id, *task, datetime.utcnow().isoformat()) for task in starter_tasks],
                )
                connection.commit()
            except sqlite3.IntegrityError:
                error = "An account with that email already exists."
                connection.rollback()
            else:
                session["user_id"] = user_id
                session["user_name"] = name
                connection.close()
                return redirect(url_for("dashboard"))
            connection.close()
    return render_template("login.html", error=error, mode="register")


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    error = None
    message = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            error = "Enter the email associated with your account."
        else:
            connection = get_db()
            user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user:
                error = "No account matches that email address."
            else:
                otp = generate_otp()
                expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
                connection.execute(
                    "UPDATE users SET otp_code = ?, otp_expires_at = ? WHERE id = ?",
                    (otp, expires_at, user["id"]),
                )
                connection.commit()
                connection.close()
                send_otp_email(email, otp)
                message = f"An OTP has been sent to {email}. For this demo, your code is {otp}."
                return render_template("login.html", mode="reset", email=email, message=message)
            connection.close()
    return render_template("login.html", error=error, message=message, mode="forgot")


@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    error = None
    message = None
    email = request.form.get("email", "").strip().lower() or request.args.get("email", "").strip().lower()
    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        new_password = request.form.get("new_password", "")
        if not email or not otp or not new_password:
            error = "Email, OTP, and a new password are required."
        elif len(new_password) < 8:
            error = "Choose a password with at least 8 characters."
        else:
            connection = get_db()
            user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user:
                error = "We could not find an account with that email."
            elif not user["otp_code"] or not user["otp_expires_at"]:
                error = "No active OTP was found. Request a new one."
            elif user["otp_code"] != otp:
                error = "That OTP is invalid. Please try again."
            else:
                expires_at = datetime.fromisoformat(user["otp_expires_at"])
                if expires_at < datetime.utcnow():
                    error = "The OTP has expired. Please request a new one."
                else:
                    connection.execute(
                        "UPDATE users SET password = ?, otp_code = NULL, otp_expires_at = NULL WHERE id = ?",
                        (generate_password_hash(new_password), user["id"]),
                    )
                    connection.commit()
                    connection.close()
                    return render_template("login.html", mode="login", message="Password reset successful. Please sign in with your new password.")
            connection.close()
    return render_template("login.html", error=error, message=message, mode="reset", email=email)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@logged_in
def dashboard():
    now = datetime.now().astimezone()
    connection = get_db()
    tasks = connection.execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY completed, due, id", (session["user_id"],)
    ).fetchall()
    connection.close()
    completed = sum(task["completed"] for task in tasks)
    return render_template(
        "dashboard.html",
        tasks=tasks,
        completed=completed,
        today=f"{now:%A, %B} {now.day}",
        current_time=now.strftime("%I:%M %p").lstrip("0"),
        greeting=time_based_greeting(now.hour),
    )


@app.post("/api/tasks")
@logged_in
def create_task():
    payload = request.get_json(silent=True) or {}
    title = payload.get("title", "").strip()
    if not title:
        return jsonify({"error": "A task title is required."}), 400
    connection = get_db()
    cursor = connection.execute(
        "INSERT INTO tasks (user_id, title, detail, due, priority, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session["user_id"], title, payload.get("detail", ""), payload.get("due", "Anytime"), payload.get("priority", "normal"), datetime.utcnow().isoformat()),
    )
    connection.commit()
    task = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    connection.close()
    return jsonify(dict(task)), 201


@app.post("/api/tasks/<int:task_id>/toggle")
@logged_in
def toggle_task(task_id):
    connection = get_db()
    task = connection.execute(
        "SELECT completed FROM tasks WHERE id = ? AND user_id = ?", (task_id, session["user_id"])
    ).fetchone()
    if not task:
        connection.close()
        return jsonify({"error": "Task not found."}), 404
    completed = 0 if task["completed"] else 1
    connection.execute("UPDATE tasks SET completed = ? WHERE id = ?", (completed, task_id))
    connection.commit()
    connection.close()
    return jsonify({"completed": completed})


def time_based_greeting(hour):
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"


def build_assistant_answer(question, tasks, user_name, current_time=None):
    if not question:
        return "Ask me something first."

    current_time = current_time or datetime.now().astimezone()
    lower = question.lower()
    open_tasks = [task for task in tasks if not task["completed"]]

    if re.search(r"\b(hello|hi|hey)\b", lower):
        return f"{time_based_greeting(current_time.hour)}, {user_name}. I am ready to help you focus, plan, and close the loop."

    if re.search(r"\b(what time is it|current time|time now)\b", lower):
        local_time = current_time.strftime("%I:%M %p").lstrip("0")
        return f"It is {local_time} in this app's local time zone."

    if re.search(r"\b(what day is it|what date is it|today's date|current date)\b", lower):
        return f"Today is {current_time.strftime('%A, %B')} {current_time.day}."

    if any(word in lower for word in ("focus", "what should i do", "what should i focus", "next task")):
        if open_tasks:
            return f"Focus on {open_tasks[0]['title']} at {open_tasks[0]['due']}. It is the clearest next move, and you can keep the rest of the list as a buffer."
        return "Your list is clear. This is a good moment to review your wins or plan tomorrow."

    if any(word in lower for word in ("today", "my tasks", "my todos", "my work", "plan my day")):
        if open_tasks:
            task_lines = ", ".join(f"{task['title']} at {task['due']}" for task in open_tasks[:4])
            return f"You have {len(open_tasks)} open task{'s' if len(open_tasks) != 1 else ''}. Your next focus is {open_tasks[0]['title']}; your queue is {task_lines}."
        return "Your list is clear. This is a good moment to review your wins or plan tomorrow."

    if "priorit" in lower or "important" in lower:
        return "Start with the task that moves the day forward most, then protect a focused block before checking messages."

    if "done" in lower or "complete" in lower or "progress" in lower:
        completed = sum(task["completed"] for task in tasks)
        return f"You have completed {completed} of {len(tasks)} tasks so far. Keep the momentum by finishing the next single most important item."

    knowledge_answer = answer_local_knowledge(question)
    if knowledge_answer:
        return knowledge_answer

    configured_answer = answer_from_configured_provider(question)
    if configured_answer:
        return configured_answer

    return (
        f'I do not have an offline answer for "{question}". To answer broader questions, configure an '
        "OpenAI-compatible service with "
        "ASSISTANT_LLM_URL (and, if required, ASSISTANT_LLM_API_KEY) to enable broader answers."
    )


_MATH_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_MATH_FUNCTIONS = {
    "abs": abs,
    "ceil": math.ceil,
    "cos": math.cos,
    "floor": math.floor,
    "log": math.log,
    "log10": math.log10,
    "round": round,
    "sin": math.sin,
    "sqrt": math.sqrt,
    "tan": math.tan,
}


def _evaluate_math_node(node):
    if isinstance(node, ast.Expression):
        return _evaluate_math_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name) and node.id in {"pi", "e"}:
        return math.pi if node.id == "pi" else math.e
    if isinstance(node, ast.BinOp) and type(node.op) in _MATH_OPERATORS:
        left = _evaluate_math_node(node.left)
        right = _evaluate_math_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponent is too large.")
        return _MATH_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_math_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _MATH_FUNCTIONS:
        if node.keywords:
            raise ValueError("Keyword arguments are not supported.")
        return _MATH_FUNCTIONS[node.func.id](*[_evaluate_math_node(arg) for arg in node.args])
    raise ValueError("Unsupported math expression.")


def _natural_language_math_expression(question):
    expression = question.strip().lower().replace("×", "*").replace("÷", "/").replace("−", "-")
    expression = re.sub(r"^(?:what is|calculate|compute|solve|how much is)\s+", "", expression)
    expression = expression.rstrip(" ?.! ")
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"

    match = re.fullmatch(rf"({number})\s*(?:%|percent)\s+of\s+({number})", expression)
    if match:
        return f"({match.group(1)} / 100) * {match.group(2)}"

    match = re.fullmatch(rf"what percent(?:age)? is\s+({number})\s+of\s+({number})", expression)
    if match:
        return f"({match.group(1)} / {match.group(2)}) * 100"

    match = re.fullmatch(rf"({number})\s+is what percent(?:age)? of\s+({number})", expression)
    if match:
        return f"({match.group(1)} / {match.group(2)}) * 100"

    match = re.fullmatch(rf"(?:percentage|percent)\s+(increase|decrease)\s+from\s+({number})\s+to\s+({number})", expression)
    if match:
        original, final = match.group(2), match.group(3)
        difference = f"({final} - {original})" if match.group(1) == "increase" else f"({original} - {final})"
        return f"({difference} / {original}) * 100"

    operations = (
        (rf"(?:add|sum)\s+({number})\s+(?:and|to)\s+({number})", lambda match: f"{match.group(1)} + {match.group(2)}"),
        (rf"({number})\s+(?:plus|added to)\s+({number})", lambda match: f"{match.group(1)} + {match.group(2)}"),
        (rf"(?:subtract|take away)\s+({number})\s+from\s+({number})", lambda match: f"{match.group(2)} - {match.group(1)}"),
        (rf"({number})\s+minus\s+({number})", lambda match: f"{match.group(1)} - {match.group(2)}"),
        (rf"(?:multiply|multiply together)\s+({number})\s+(?:by|and)\s+({number})", lambda match: f"{match.group(1)} * {match.group(2)}"),
        (rf"({number})\s+(?:times|multiplied by)\s+({number})", lambda match: f"{match.group(1)} * {match.group(2)}"),
        (rf"divide\s+({number})\s+by\s+({number})", lambda match: f"{match.group(1)} / {match.group(2)}"),
        (rf"({number})\s+divided by\s+({number})", lambda match: f"{match.group(1)} / {match.group(2)}"),
    )
    for pattern, convert in operations:
        match = re.fullmatch(pattern, expression)
        if match:
            return convert(match)
    return expression


def answer_math_question(question):
    expression = _natural_language_math_expression(question)
    if len(expression) > 160 or not re.fullmatch(r"[0-9a-zA-Z_+\-*/().,%\s]+", expression):
        return None
    if not re.search(r"\d", expression):
        return None
    try:
        parsed = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(parsed)) > 64:
            return None
        result = _evaluate_math_node(parsed)
        if not math.isfinite(float(result)) or abs(result) > 1e100:
            return None
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return f"The answer is {result:.12g}."


def answer_local_knowledge(question):
    math_answer = answer_math_question(question)
    if math_answer:
        return math_answer

    lower = question.lower()
    entries = (
        (("python", "programming language"), "Python is a high-level, general-purpose programming language known for readable syntax. It is widely used for automation, web services, data analysis, and machine learning."),
        (("api", "application programming interface"), "An API is a defined way for software components to request data or actions from one another. A web API commonly uses HTTP methods such as GET and POST and returns structured data such as JSON."),
        (("http", "https"), "HTTP is the protocol browsers and servers use to exchange web requests and responses. HTTPS protects that connection with TLS encryption, helping prevent eavesdropping and tampering in transit."),
        (("algorithm",), "An algorithm is a finite, well-defined sequence of steps for solving a problem. Good algorithm choices consider correctness, memory use, and how running time grows as the input gets larger."),
        (("machine learning", "artificial intelligence", " ai "), "Artificial intelligence is a broad field of systems performing tasks that typically require human-like perception or reasoning. Machine learning is one approach: models learn statistical patterns from data, so their answers can be useful but still need verification."),
        (("database", "sql"), "A database stores and organizes information so applications can query and update it. Relational databases use tables and SQL; transactions help keep related changes consistent."),
        (("gravity",), "Gravity is the attractive interaction between objects with mass. In Newtonian mechanics it explains everyday falling and orbits; general relativity describes gravity as the curvature of spacetime."),
        (("photosynthesis",), "Photosynthesis is the process by which plants, algae, and some bacteria use light energy to convert carbon dioxide and water into energy-rich sugars, releasing oxygen in the process."),
        (("atom",), "An atom has a nucleus containing protons and usually neutrons, surrounded by electrons. The number of protons determines the chemical element."),
        (("prime number",), "A prime number is an integer greater than 1 whose only positive divisors are 1 and itself. For example, 2, 3, 5, and 7 are prime; 1 is not."),
        (("derivative",), "A derivative measures how quickly a function changes as its input changes. Geometrically, it is the slope of the tangent to the function's graph at a point."),
        (("probability",), "Probability quantifies uncertainty on a scale from 0 to 1, where 0 means impossible and 1 means certain. For equally likely outcomes, it is the number of favorable outcomes divided by the total number of outcomes."),
        (("water cycle",), "The water cycle moves water through evaporation, condensation into clouds, and precipitation such as rain or snow. Water then collects in rivers, lakes, and oceans, and the cycle continues."),
        (("water", "h2o"), "A water molecule contains two hydrogen atoms and one oxygen atom, written H2O. At standard atmospheric pressure, pure water freezes at 0°C and boils at 100°C."),
        (("earth", "planet earth"), "Earth is the third planet from the Sun. It takes about 24 hours to rotate once and about 365.25 days to orbit the Sun once."),
        (("sun", "the sun"), "The Sun is the star at the center of our solar system. Its light and heat power Earth's climate and support most life through photosynthesis."),
        (("continents", "continent"), "A common school model counts seven continents: Africa, Antarctica, Asia, Europe, North America, Australia, and South America. Some regions use different continent models."),
        (("ocean", "oceans"), "Earth has five commonly named oceans: Pacific, Atlantic, Indian, Southern, and Arctic. The Pacific is the largest."),
        (("air", "atmosphere"), "Dry air near Earth's surface is mostly nitrogen (about 78%) and oxygen (about 21%), with small amounts of argon, carbon dioxide, and other gases."),
        (("sky blue",), "The daytime sky often looks blue because air molecules scatter shorter-wavelength blue sunlight more strongly than longer-wavelength red light."),
        (("human heart", "heart"), "The human heart is a muscular pump. It moves blood through the lungs to pick up oxygen and around the body to deliver oxygen and nutrients."),
        (("solar system",), "Our solar system consists of the Sun, eight planets, their moons, and many smaller bodies such as dwarf planets, asteroids, and comets."),
    )
    padded = f" {lower} "
    for keywords, answer in entries:
        if any(keyword in padded for keyword in keywords):
            return answer
    return None


class AssistantProviderError(Exception):
    pass


def answer_from_configured_provider(question):
    endpoint = os.environ.get("ASSISTANT_LLM_URL", "").strip()
    if not endpoint:
        return None
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
        raise AssistantProviderError("ASSISTANT_LLM_URL must be a valid HTTP or HTTPS chat-completions endpoint.")

    payload = json.dumps(
        {
            "model": os.environ.get("ASSISTANT_LLM_MODEL", "gpt-4o-mini"),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful general knowledge assistant. Answer questions about technology, "
                        "science, mathematics, programming, and other useful topics clearly and accurately. "
                        "Show concise reasoning or examples when useful, state uncertainty, and never claim "
                        "to have checked live information."
                    ),
                },
                {"role": "user", "content": question},
            ],
            "temperature": 0.3,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("ASSISTANT_LLM_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request_to_provider = Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urlopen(request_to_provider, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        answer = result["choices"][0]["message"]["content"]
    except HTTPError as error:
        raise AssistantProviderError(f"The knowledge service returned HTTP {error.code}. Check its endpoint and configuration.") from error
    except (URLError, TimeoutError) as error:
        raise AssistantProviderError("The knowledge service could not be reached. Check your connection and endpoint.") from error
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise AssistantProviderError("The knowledge service returned an unreadable response.") from error
    if not isinstance(answer, str) or not answer.strip():
        raise AssistantProviderError("The knowledge service returned an empty answer.")
    return answer.strip()


def execute_assistant_task_command(question, user_id):
    add_match = re.match(
        r"^(?:(?:please|can you)\s+)?(?:add|create)\s+(?:a\s+)?(?:task\s+)?(?:to\s+)?(.+)$",
        question.strip(),
        re.IGNORECASE,
    )
    if add_match:
        title = re.sub(r"\s+to\s+my\s+tasks?$", "", add_match.group(1).strip(), flags=re.IGNORECASE).strip(" .!?\t")
        if title:
            connection = get_db()
            cursor = connection.execute(
                "INSERT INTO tasks (user_id, title, detail, due, priority, created_at) VALUES (?, ?, '', 'Anytime', 'normal', ?)",
                (user_id, title, datetime.utcnow().isoformat()),
            )
            connection.commit()
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
            connection.close()
            return {"answer": f"I added {title} to your tasks.", "action": "created", "task": dict(task)}

    complete_match = re.match(
        r"^(?:(?:please|can you)\s+)?(?:mark|complete|finish)\s+(?:the\s+)?(?:task\s+)?(.+?)"
        r"(?:\s+(?:as\s+)?(?:done|complete|completed))?[.!?]*$",
        question.strip(),
        re.IGNORECASE,
    )
    if not complete_match:
        return None

    requested_title = complete_match.group(1).strip(" .!?\t")
    if not requested_title:
        return None

    connection = get_db()
    candidates = connection.execute(
        "SELECT id, title FROM tasks WHERE user_id = ? AND completed = 0 ORDER BY id",
        (user_id,),
    ).fetchall()
    matches = [task for task in candidates if task["title"].casefold() == requested_title.casefold()]
    if not matches:
        matches = [task for task in candidates if requested_title.casefold() in task["title"].casefold()]
    if len(matches) != 1:
        connection.close()
        if matches:
            titles = ", ".join(task["title"] for task in matches)
            return {"answer": f"I found a few matching tasks: {titles}. Please say the exact task name."}
        return {"answer": f"I couldn't find an open task matching {requested_title}."}

    task = matches[0]
    connection.execute(
        "UPDATE tasks SET completed = 1 WHERE id = ? AND user_id = ?",
        (task["id"], user_id),
    )
    connection.commit()
    connection.close()
    return {
        "answer": f"I marked {task['title']} as complete.",
        "action": "completed",
        "task": {"id": task["id"], "title": task["title"], "completed": 1},
    }


@app.post("/api/assistant")
@logged_in
def assistant_answer():
    question = (request.get_json(silent=True) or {}).get("question", "").strip()
    if not question:
        return jsonify({"error": "Ask me something first."}), 400
    task_command = execute_assistant_task_command(question, session["user_id"])
    if task_command:
        return jsonify(task_command)
    connection = get_db()
    rows = connection.execute(
        "SELECT title, due, priority, completed FROM tasks WHERE user_id = ? ORDER BY completed, due",
        (session["user_id"],),
    ).fetchall()
    connection.close()
    try:
        answer = build_assistant_answer(
            question,
            rows,
            session.get("user_name", "there"),
            current_time=datetime.now().astimezone(),
        )
    except AssistantProviderError as error:
        app.logger.warning("Knowledge provider request failed: %s", error)
        return jsonify({"error": str(error)}), 502
    return jsonify({"answer": answer})


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)