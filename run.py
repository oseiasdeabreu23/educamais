import os
from app import create_app, db

app = create_app()

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    porta = int(os.getenv('PORTA', 5000))
    app.run(debug=True, port=porta)
