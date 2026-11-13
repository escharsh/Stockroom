from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3


@event.listens_for(Engine, 'connect')
def enable_foreign_keys(connection, record):
    if isinstance(connection, sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys = ON')
        cursor.close()

# Global extensions (used by blueprints)
db = SQLAlchemy()
login_manager = LoginManager()

# Where users get redirected when not logged in
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
