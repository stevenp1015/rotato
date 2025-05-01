import os, sqlite3, uuid, json
from flask import Flask, render_template, request, redirect, url_for, g
from dotenv import load_dotenv
from pairing import round_robin, no_recent_repeats

load_dotenv()
DB = "rotato.db"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.execute("""CREATE TABLE IF NOT EXISTS rooms(
                          id TEXT PRIMARY KEY,
                          names TEXT,
                          history TEXT
                       )""")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    if (db := g.pop("db", None)):
        db.close()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        names = request.form["names"].strip().splitlines()
        room_id = str(uuid.uuid4())
        db = get_db()
        db.execute("INSERT INTO rooms VALUES (?,?,?)",
                   (room_id, json.dumps(names), json.dumps([])))
        db.commit()
        return redirect(url_for("room", room_id=room_id))
    return render_template("index.html")

@app.route("/<room_id>", methods=["GET", "POST"])
def room(room_id):
    db = get_db()
    row = db.execute("SELECT names, history FROM rooms WHERE id = ?",
                     (room_id,)).fetchone()
    if not row:
        return "Room not found", 404
    names, history = map(json.loads, row)

    if request.method == "POST":
        for _ in range(100):
            pairs = round_robin(names)
            if no_recent_repeats(history, pairs):
                break
        history.append(pairs)
        db.execute("UPDATE rooms SET history = ? WHERE id = ?",
                   (json.dumps(history), room_id))
        db.commit()

    current = history[-1] if history else []
    return render_template("index.html",
                           names="\n".join(names),
                           pairs=current,
                           history=history[:-1],
                           room_id=room_id)

if __name__ == "__main__":
    app.run(debug=True, port=5000)

