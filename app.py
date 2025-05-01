import os, sqlite3, uuid, json, datetime, re, bcrypt, requests
from flask import Flask, render_template, request, redirect, url_for, g, flash, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from slack import WebClient
from slack.errors import SlackApiError
import stripe
from dotenv import load_dotenv
from pairing import round_robin, no_recent_repeats


load_dotenv()
DB = "rotato.db"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

# Set up Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_51PQRSTuvwxyz")
stripe_publishable_key = os.getenv("STRIPE_PUBLISHABLE_KEY", "pk_test_123456789")

# Set up LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# Set up Scheduler
scheduler = BackgroundScheduler()
scheduler.start()

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB, detect_types=sqlite3.PARSE_DECLTYPES)
        
        # Create tables if they don't exist
        g.db.execute("""CREATE TABLE IF NOT EXISTS rooms(
                          id TEXT PRIMARY KEY,
                          names TEXT,
                          history TEXT,
                          owner_id INTEGER,
                          created_at TEXT,
                          last_updated TEXT,
                          slack_channel TEXT,
                          slack_webhook TEXT,
                          auto_schedule TEXT,
                          FOREIGN KEY(owner_id) REFERENCES users(id)
                       )""")
        
        g.db.execute("""CREATE TABLE IF NOT EXISTS users(
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                          email TEXT UNIQUE NOT NULL,
                          password TEXT NOT NULL,
                          name TEXT,
                          created_at TEXT,
                          last_login TEXT,
                          subscription_tier TEXT DEFAULT 'free',
                          subscription_id TEXT,
                          stripe_customer_id TEXT,
                          slack_workspace_id TEXT,
                          slack_access_token TEXT
                       )""")
        
        g.db.execute("""CREATE TABLE IF NOT EXISTS jobs(
                          id TEXT PRIMARY KEY,
                          room_id TEXT NOT NULL,
                          job_type TEXT NOT NULL,
                          next_run TEXT,
                          frequency TEXT,
                          FOREIGN KEY(room_id) REFERENCES rooms(id)
                       )""")
        
        g.db.commit()
    return g.db

@app.teardown_appcontext
def close_db(exc):
    if (db := g.pop("db", None)):
        db.close()

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, email, name, subscription_tier, stripe_customer_id=None, slack_workspace_id=None):
        self.id = id
        self.email = email
        self.name = name
        self.subscription_tier = subscription_tier
        self.stripe_customer_id = stripe_customer_id
        self.slack_workspace_id = slack_workspace_id
    
    def is_premium(self):
        return self.subscription_tier == 'premium'
    
    def get_id(self):
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user_data = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user_data:
        return User(
            id=user_data[0],
            email=user_data[1],
            name=user_data[3],
            subscription_tier=user_data[6],
            stripe_customer_id=user_data[8],
            slack_workspace_id=user_data[9]
        )
    return None

# Forms for authentication
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')

class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    name = StringField('Name', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField('Repeat Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')
    
    def validate_email(self, email):
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email.data,)).fetchone()
        if user:
            raise ValidationError('Email already registered.')

# Helper functions for Slack integration and scheduling
def send_slack_notification(webhook_url, message, pairs):
    """Send a notification to a Slack webhook with the current pairs"""
    payload = {
        "text": message,
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": message
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Here are this round's pairs:*"
                }
            }
        ]
    }
    
    # Add each pair as a section
    for a, b in pairs:
        payload["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"• *{a}* + *{b}*"
            }
        })
    
    # Send the payload to Slack
    response = requests.post(webhook_url, json=payload)
    if response.status_code != 200:
        raise Exception(f"Slack API returned status code {response.status_code}")

def generate_new_pairs(room_id):
    """Generate a new round of pairs for a room and update the database"""
    db = get_db()
    row = db.execute(
        "SELECT names, history, slack_webhook FROM rooms WHERE id = ?", 
        (room_id,)
    ).fetchone()
    
    if not row:
        return False
    
    names, history, slack_webhook = json.loads(row[0]), json.loads(row[1]), row[2]
    
    for _ in range(100):
        pairs = round_robin(names)
        if no_recent_repeats(history, pairs):
            break
    
    history.append(pairs)
    now = datetime.datetime.now().isoformat()
    
    db.execute(
        "UPDATE rooms SET history = ?, last_updated = ? WHERE id = ?",
        (json.dumps(history), now, room_id)
    )
    db.commit()
    
    # Send Slack notification if configured
    if slack_webhook:
        try:
            send_slack_notification(slack_webhook, "New automatic pairings are ready!", pairs)
        except Exception:
            # Log the error but continue
            pass
    
    return True

def schedule_automatic_pairing(room_id, schedule):
    """Set up or update a scheduled job for automatic pairing"""
    # Remove any existing jobs first
    cancel_scheduled_jobs(room_id)
    
    # Parse the schedule string (format: "day_of_week:hour:minute")
    try:
        day_of_week, hour, minute = schedule.split(':')
        job_id = f"pairing_{room_id}"
        
        # Schedule the job
        scheduler.add_job(
            generate_new_pairs,
            CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute),
            id=job_id,
            args=[room_id],
            replace_existing=True
        )
        
        # Save job info to database
        db = get_db()
        job = scheduler.get_job(job_id)
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        
        db.execute(
            "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?, ?)",
            (job_id, room_id, "pairing", next_run, schedule)
        )
        db.commit()
        
        return True
    except Exception as e:
        print(f"Error scheduling job: {str(e)}")
        return False

def cancel_scheduled_jobs(room_id):
    """Remove all scheduled jobs for a room"""
    job_id = f"pairing_{room_id}"
    
    # Remove from scheduler if exists
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # Remove from database
    db = get_db()
    db.execute("DELETE FROM jobs WHERE room_id = ?", (room_id,))
    db.commit()

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        db = get_db()
        hashed_password = bcrypt.hashpw(form.password.data.encode('utf-8'), bcrypt.gensalt())
        now = datetime.datetime.now().isoformat()
        
        db.execute(
            "INSERT INTO users (email, password, name, created_at) VALUES (?, ?, ?, ?)",
            (form.email.data, hashed_password.decode('utf-8'), form.name.data, now)
        )
        db.commit()
        
        flash('Congratulations, you are now registered! Please log in.')
        return redirect(url_for('login'))
    
    return render_template('register.html', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        db = get_db()
        user_data = db.execute("SELECT * FROM users WHERE email = ?", (form.email.data,)).fetchone()
        
        if user_data and bcrypt.checkpw(form.password.data.encode('utf-8'), user_data[2].encode('utf-8')):
            user = User(
                id=user_data[0],
                email=user_data[1],
                name=user_data[3],
                subscription_tier=user_data[6],
                stripe_customer_id=user_data[8],
                slack_workspace_id=user_data[9]
            )
            
            login_user(user, remember=form.remember_me.data)
            
            # Update last login time
            now = datetime.datetime.now().isoformat()
            db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_data[0]))
            db.commit()
            
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('dashboard')
            return redirect(next_page)
        
        flash('Invalid email or password')
    
    return render_template('login.html', form=form)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    # Get user's rooms
    rooms = db.execute(
        "SELECT id, names, created_at, last_updated FROM rooms WHERE owner_id = ?", 
        (current_user.id,)
    ).fetchall()
    
    rooms_data = []
    for room in rooms:
        names = json.loads(room[1])
        rooms_data.append({
            'id': room[0],
            'participant_count': len(names),
            'created_at': room[2],
            'last_updated': room[3]
        })
    
    return render_template('dashboard.html', rooms=rooms_data, user=current_user)

@app.route("/about")
def about():
    return render_template("landing.html")

@app.route('/subscription')
@login_required
def subscription():
    return render_template('subscription.html', 
                          user=current_user, 
                          stripe_publishable_key=stripe_publishable_key)

@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    try:
        # Create a new customer or get existing one
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.name
            )
            db = get_db()
            db.execute("UPDATE users SET stripe_customer_id = ? WHERE id = ?", 
                      (customer.id, current_user.id))
            db.commit()
            customer_id = customer.id
        else:
            customer_id = current_user.stripe_customer_id
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': os.getenv('STRIPE_PRICE_ID', 'price_1abcdefghijklmnop'),
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'subscription-success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'subscription',
        )
        
        return redirect(checkout_session.url)
    
    except Exception as e:
        return str(e), 403

@app.route('/subscription-success')
@login_required
def subscription_success():
    session_id = request.args.get('session_id')
    if not session_id:
        return redirect(url_for('subscription'))
    
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        subscription_id = checkout_session.subscription
        
        # Update user's subscription status
        db = get_db()
        db.execute("UPDATE users SET subscription_tier = ?, subscription_id = ? WHERE id = ?", 
                  ('premium', subscription_id, current_user.id))
        db.commit()
        
        flash('Thank you for subscribing to Rotato Premium!')
        return redirect(url_for('dashboard'))
    
    except Exception as e:
        flash('There was an error processing your subscription.')
        return redirect(url_for('subscription'))

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv('STRIPE_WEBHOOK_SECRET', 'whsec_123456789')
        )
        
        # Handle the event
        if event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            db = get_db()
            db.execute("UPDATE users SET subscription_tier = 'free', subscription_id = NULL WHERE subscription_id = ?", 
                      (subscription.id,))
            db.commit()
        
        return jsonify(success=True)
    
    except Exception as e:
        return jsonify(success=False, error=str(e)), 400

@app.route("/", methods=["GET"])
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template("landing.html")

@app.route("/create-room", methods=["GET", "POST"])
@login_required
def create_room():
    if request.method == "POST":
        names = request.form["names"].strip().splitlines()
        room_id = str(uuid.uuid4())
        
        # Check participant limit for free tier
        if len(names) > 10 and current_user.subscription_tier == 'free':
            flash('Free accounts are limited to 10 participants per room. Please upgrade to Premium for unlimited participants.')
            return render_template("create_room.html", names="\n".join(names))
        
        now = datetime.datetime.now().isoformat()
        db = get_db()
        db.execute(
            "INSERT INTO rooms (id, names, history, owner_id, created_at, last_updated) VALUES (?,?,?,?,?,?)",
            (room_id, json.dumps(names), json.dumps([]), current_user.id, now, now)
        )
        db.commit()
        
        # Set up automatic first round
        return redirect(url_for("room", room_id=room_id))
    
    return render_template("create_room.html")

@app.route("/room/<room_id>", methods=["GET", "POST"])
def room(room_id):
    db = get_db()
    row = db.execute(
        "SELECT names, history, owner_id, slack_channel, slack_webhook, auto_schedule FROM rooms WHERE id = ?", 
        (room_id,)
    ).fetchone()
    
    if not row:
        flash("Room not found")
        return redirect(url_for("index"))

    names, history, owner_id, slack_channel, slack_webhook, auto_schedule = (
        json.loads(row[0]), json.loads(row[1]), row[2], row[3], row[4], row[5]
    )
    
    # Check if user has access to this room
    is_owner = current_user.is_authenticated and current_user.id == owner_id
    room_settings = is_owner
    
    # ── Auto-generate first round if none exist ──
    if not history:
        # try a round-robin that doesn't repeat
        for _ in range(100):
            pairs = round_robin(names)
            if no_recent_repeats(history, pairs):
                break
        history.append(pairs)
        
        now = datetime.datetime.now().isoformat()
        db.execute(
            "UPDATE rooms SET history = ?, last_updated = ? WHERE id = ?",
            (json.dumps(history), now, room_id)
        )
        db.commit()
        
        # If Slack is configured, send notification
        if slack_webhook:
            try:
                send_slack_notification(slack_webhook, "New pairings are ready!", history[-1])
            except Exception as e:
                flash(f"Failed to send Slack notification: {str(e)}")
    
    # ── Handle manual generation of new rounds ──
    elif request.method == "POST" and "generate" in request.form:
        for _ in range(100):
            pairs = round_robin(names)
            if no_recent_repeats(history, pairs):
                break
        history.append(pairs)
        
        now = datetime.datetime.now().isoformat()
        db.execute(
            "UPDATE rooms SET history = ?, last_updated = ? WHERE id = ?",
            (json.dumps(history), now, room_id)
        )
        db.commit()
        
        # If Slack is configured, send notification
        if slack_webhook:
            try:
                send_slack_notification(slack_webhook, "New pairings are ready!", history[-1])
            except Exception as e:
                flash(f"Failed to send Slack notification: {str(e)}")
    
    current = history[-1]
    
    # Room settings form submission
    if request.method == "POST" and "save_settings" in request.form and is_owner:
        slack_channel = request.form.get("slack_channel", "")
        slack_webhook = request.form.get("slack_webhook", "")
        auto_schedule = request.form.get("auto_schedule", "")
        
        db.execute(
            "UPDATE rooms SET slack_channel = ?, slack_webhook = ?, auto_schedule = ? WHERE id = ?",
            (slack_channel, slack_webhook, auto_schedule, room_id)
        )
        db.commit()
        
        # Set up or update scheduler if auto_schedule is enabled
        if auto_schedule and current_user.subscription_tier == 'premium':
            schedule_automatic_pairing(room_id, auto_schedule)
            flash("Room settings and automatic scheduling updated successfully!")
        elif auto_schedule and current_user.subscription_tier != 'premium':
            flash("Automatic scheduling is a premium feature. Please upgrade to enable it.")
        else:
            # Remove any existing scheduled jobs for this room
            cancel_scheduled_jobs(room_id)
            flash("Room settings updated successfully!")
            
        return redirect(url_for("room", room_id=room_id))
    
    # Determine feature availability based on subscription
    premium_features = current_user.is_authenticated and current_user.subscription_tier == 'premium'
    
    return render_template(
        "room.html",
        names="\n".join(names),
        pairs=current,
        history=history[:-1],
        room_id=room_id,
        is_owner=is_owner,
        room_settings=room_settings,
        slack_channel=slack_channel,
        slack_webhook=slack_webhook,
        auto_schedule=auto_schedule,
        premium_features=premium_features,
        user=current_user if current_user.is_authenticated else None
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)
