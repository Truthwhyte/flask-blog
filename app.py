import os
import uuid
from datetime import datetime

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_bcrypt import Bcrypt
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Secrets come from the environment, never from the code.
# Locally: export SECRET_KEY="some-long-random-string" before running.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///blogs.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ── upload config ──
UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB per upload
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── extensions ──
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


# ── helpers ──
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(file):
    """Save an uploaded image under a unique name so uploads never overwrite each other."""
    if not file or file.filename == '' or not allowed_file(file.filename):
        return None
    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return filename


def get_own_blog_or_403(blog_id):
    """Fetch a blog and make sure the logged-in user wrote it."""
    blog = db.get_or_404(Blogs, blog_id)
    if blog.user_id != current_user.id:
        abort(403)
    return blog


# ── models ──
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)  # bcrypt hash
    blogs = db.relationship('Blogs', backref='author', lazy=True)

    def __init__(self, username, email, password):
        self.username = username
        self.email = email
        self.password = password


class Blogs(db.Model):
    _id = db.Column(db.Integer(), primary_key=True)
    title = db.Column(db.String(100), unique=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __init__(self, title, content, user_id, image=None):
        self.title = title
        self.content = content
        self.user_id = user_id
        self.image = image


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ── routes ──

# HOME
@app.route('/')
@login_required
def blogs():
    all_blogs = Blogs.query.order_by(Blogs.created_at.desc()).all()
    return render_template('home.html', blogs=all_blogs, title='Blogs Page', total=len(all_blogs))


# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('blogs'))

    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password'].strip()
        remember = bool(request.form.get('remember'))

        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user, remember=remember)
            flash('Logged in successfully', 'success')
            next_page = request.args.get('next')
            # only follow relative links, so the login page can't be used to redirect elsewhere
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            return redirect(url_for('blogs'))
        flash('Invalid email or password', 'danger')

    return render_template('login.html')


# LOGOUT
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))


# REGISTER
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('blogs'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm = request.form['confirm']

        if not username or not email or not password:
            flash('All fields are required', 'danger')
        elif password != confirm:
            flash('Passwords do not match', 'danger')
        elif len(password) < 6:
            flash('Password must be at least 6 characters', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Username already taken', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered', 'danger')
        else:
            hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
            db.session.add(User(username=username, email=email, password=hashed_pw))
            db.session.commit()
            flash('Account created! You can now log in.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')


# ADD BLOG
@app.route('/addblog', methods=['GET', 'POST'])
@login_required
def add_blog():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        if not title or not content:
            flash('Title and content are required', 'danger')
            return render_template('addblog.html')

        if Blogs.query.filter_by(title=title).first():
            flash('A blog with this title already exists', 'danger')
            return render_template('addblog.html')

        blog = Blogs(
            title=title,
            content=content,
            user_id=current_user.id,
            image=save_image(request.files.get('image')),
        )
        db.session.add(blog)

        try:
            db.session.commit()
            flash('Blog added successfully', 'success')
            return redirect(url_for('blogs'))
        except Exception as e:
            db.session.rollback()
            app.logger.error("Error adding blog: %s", e)
            flash('Something went wrong. Please try again.', 'danger')

    return render_template('addblog.html')


# VIEW BLOG
@app.route('/viewblog/<title>')
def viewblog(title):
    blog = Blogs.query.filter_by(title=title).first_or_404()
    return render_template('view_blog.html', blog=blog)


# DELETE BLOG (POST only, author only)
@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def deleteuser(id):
    blog = get_own_blog_or_403(id)
    db.session.delete(blog)
    try:
        db.session.commit()
        flash('Blog deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error("Error deleting blog: %s", e)
        flash('Something went wrong. Please try again.', 'danger')
    return redirect(url_for('blogs'))


# UPDATE BLOG (author only)
@app.route('/updateblog/<int:id>', methods=['GET', 'POST'])
@login_required
def updateblog(id):
    blog = get_own_blog_or_403(id)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        if not title or not content:
            return render_template('updateblog.html', blog=blog, error="Title and content cannot be empty.")

        existing = Blogs.query.filter_by(title=title).first()
        if existing and existing._id != blog._id:
            return render_template('updateblog.html', blog=blog, error="A blog with this title already exists.")

        blog.title = title
        blog.content = content
        new_image = save_image(request.files.get('image'))
        if new_image:
            blog.image = new_image

        try:
            db.session.commit()
            flash('Blog updated successfully', 'success')
            return redirect(url_for('viewblog', title=blog.title))
        except Exception as e:
            db.session.rollback()
            app.logger.error("Error updating blog: %s", e)
            return render_template('updateblog.html', blog=blog, error="Something went wrong. Please try again.")

    return render_template('updateblog.html', blog=blog)


# ── init db ──
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
