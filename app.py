from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import datetime
from dotenv import load_dotenv
import os
from urllib.parse import quote_plus

load_dotenv()


app = Flask(__name__)
app.secret_key = 'secret-key'


# For Render PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

with app.app_context():
    try:
        db.create_all()
        print("Database tables created successfully")
    except Exception as e:
        print(f"Database error: {str(e)}")
        db.session.rollback()

@app.route('/test_db')
def test_db():
    try:
        db.session.execute(text("SELECT 1"))
        return "Database connection successful!"
    except Exception as e:
        return f"Database connection failed: {str(e)}", 500

# Login Table
class Login(db.Model):
    __tablename__ = 'login'
    id = db.Column(db.Integer, primary_key=True)
    groupname = db.Column(db.String(30))
    name = db.Column(db.String(30))
    password = db.Column(db.String(20))


@app.route('/')
def index():
    return render_template('login.html')


@app.route('/signup', methods=['POST'])
def signup():
    name = request.form['name']
    groupname = request.form['group']
    password = request.form['password']

    existing_group = Login.query.filter_by(groupname=groupname).first()
    if existing_group:
        flash('Group name already in use!')
        return redirect(url_for('index'))

    new_user = Login(groupname=groupname, name=name, password=password)
    db.session.add(new_user)
    db.session.commit()
    flash('Account created successfully. Please login.')
    return redirect(url_for('index'))


def create_group_table(groupname):
    with db.engine.connect() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{groupname}` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                topic VARCHAR(100),
                name VARCHAR(100),
                date DATE,
                description TEXT
            );
        """))


def create_log_table():
    with db.engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS group_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                groupname VARCHAR(100),
                user VARCHAR(100),
                action VARCHAR(255),
                timestamp DATETIME
            );
        """))


@app.route('/signin', methods=['POST'])
def signin():
    name = request.form['name']
    groupname = request.form['groupname']
    password = request.form['password']

    user = Login.query.filter_by(groupname=groupname, password=password).first()
    if user:
        session['user'] = name
        session['group'] = groupname
        create_group_table(groupname)
        create_log_table()

        db.session.execute(text("""
            INSERT INTO group_logs (groupname, user, action, timestamp)
            VALUES (:groupname, :user, :action, :timestamp)
        """), {
            "groupname": groupname,
            "user": name,
            "action": "Logged in",
            "timestamp": datetime.datetime.now()
        })
        db.session.commit()
        return redirect('/home')
    else:
        flash('Invalid credentials.')
        return redirect(url_for('index'))


@app.route('/home')
def home():
    if 'user' not in session or 'group' not in session:
        return redirect(url_for('index'))

    table_name = session['group']
    with db.engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM `{table_name}`")).fetchall()

    grouped = {}
    for row in result:
        topic = row.topic
        if topic not in grouped:
            grouped[topic] = []
        grouped[topic].append(row)

    logs = db.session.execute(text("""
        SELECT user, action, timestamp FROM group_logs
        WHERE groupname = :groupname ORDER BY timestamp DESC
    """), {"groupname": table_name}).fetchall()

    return render_template('home.html', grouped=grouped, logs=logs)


@app.route('/add_entry', methods=['POST'])
def add_entry():
    if 'user' not in session or 'group' not in session:
        return redirect(url_for('index'))

    topic = request.form['topic']
    date = request.form['date']
    description = request.form['description']
    name = session['user']
    table_name = session['group']

    try:
        db.session.execute(text(f"""
            INSERT INTO `{table_name}` (topic, name, date, description)
            VALUES (:topic, :name, :date, :description)
        """), {
            "topic": topic,
            "name": name,
            "date": date,
            "description": description
        })

        db.session.execute(text("""
            INSERT INTO group_logs (groupname, user, action, timestamp)
            VALUES (:groupname, :user, :action, :timestamp)
        """), {
            "groupname": table_name,
            "user": name,
            "action": f"Added topic '{topic}'",
            "timestamp": datetime.datetime.now()
        })

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Insert failed:", e)

    return redirect('/home')


@app.route('/edit_entry/<int:id>', methods=['GET', 'POST'])
def edit_entry(id):
    table_name = session['group']
    name = session['user']

    if request.method == 'POST':
        topic = request.form['topic']
        date = request.form['date']
        description = request.form['description']

        try:
            db.session.execute(text(f"""
                UPDATE `{table_name}` SET topic=:topic, date=:date, description=:description
                WHERE id=:id
            """), {
                "topic": topic,
                "date": date,
                "description": description,
                "id": id
            })

            db.session.execute(text("""
                INSERT INTO group_logs (groupname, user, action, timestamp)
                VALUES (:groupname, :user, :action, :timestamp)
            """), {
                "groupname": table_name,
                "user": name,
                "action": f"Edited entry ID {id}",
                "timestamp": datetime.datetime.now()
            })

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print("Update failed:", e)
        return redirect('/home')

    row = db.session.execute(text(f"SELECT * FROM `{table_name}` WHERE id = :id"), {"id": id}).fetchone()
    return render_template('edit_entry.html', row=row)


@app.route('/delete_entry/<int:id>', methods=['POST'])
def delete_entry(id):
    table_name = session['group']
    name = session['user']

    try:
        db.session.execute(text(f"DELETE FROM `{table_name}` WHERE id = :id"), {"id": id})

        db.session.execute(text("""
            INSERT INTO group_logs (groupname, user, action, timestamp)
            VALUES (:groupname, :user, :action, :timestamp)
        """), {
            "groupname": table_name,
            "user": name,
            "action": f"Deleted entry ID {id}",
            "timestamp": datetime.datetime.now()
        })

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Delete failed:", e)

    return redirect('/home')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
