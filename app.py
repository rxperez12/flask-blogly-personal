import os
from dotenv import load_dotenv

from flask import Flask, render_template, request, flash, redirect, session, g
from flask_debugtoolbar import DebugToolbarExtension
from werkzeug.exceptions import Unauthorized
from sqlalchemy.exc import IntegrityError

from forms import UserAddForm, LoginForm, MessageForm, CsrfForm, UserEditForm
from models import db, dbx, User, Message, Like, DEFAULT_IMAGE_URL, DEFAULT_HEADER_IMAGE_URL


load_dotenv()

CURR_USER_KEY = "curr_user"

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
app.config['SQLALCHEMY_ECHO'] = False
app.config['DEBUG_TB_INTERCEPT_REDIRECTS'] = True
app.config['SQLALCHEMY_RECORD_QUERIES'] = True
app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
# toolbar = DebugToolbarExtension(app)

db.init_app(app)


##############################################################################
# User signup/login/logout


@app.before_request
def add_user_to_g():
    """If we're logged in, add curr user to Flask global."""

    if CURR_USER_KEY in session:
        g.user = db.session.get(User, session[CURR_USER_KEY])

    else:
        g.user = None


@app.before_request
def add_csrf_form_to_g():
    g.csrf_form = CsrfForm()


def do_login(user):
    """Log in user."""

    session[CURR_USER_KEY] = user.id


def do_logout():
    """Log out user."""

    if CURR_USER_KEY in session:
        del session[CURR_USER_KEY]


@app.route('/signup', methods=["GET", "POST"])
def signup():
    """Handle user signup.

    Create new user and add to DB. Redirect to home page.

    If form not valid, present form.

    If the there already is a user with that username: flash message
    and re-present form.
    """

    do_logout()

    form = UserAddForm()

    if form.validate_on_submit():
        try:
            user = User.signup(
                username=form.username.data,
                password=form.password.data,
                email=form.email.data,
                image_url=form.image_url.data or User.image_url.default.arg,
            )
            db.session.commit()

        except IntegrityError:
            flash("Username already taken", 'danger')
            return render_template('users/signup.jinja', form=form)

        do_login(user)

        return redirect("/")

    else:
        return render_template('users/signup.jinja', form=form)


@app.route('/login', methods=["GET", "POST"])
def login():
    """Handle user login and redirect to homepage on success."""

    form = LoginForm()

    if form.validate_on_submit():
        user = User.authenticate(
            form.username.data,
            form.password.data,
        )

        if user:
            do_login(user)
            flash(f"Hello, {user.username}!", "success")
            return redirect("/")

        flash("Invalid credentials.", 'danger')

    return render_template('users/login.jinja', form=form)


@app.post('/logout')
def logout():
    """Handle logout of user and redirect to homepage."""

    form = g.csrf_form

    if form.validate_on_submit():
        do_logout()

        return redirect('/login')

    else:
        raise Unauthorized()


##############################################################################
# General user routes:

@app.get('/users')
def list_users():
    """Page with listing of users.

    Can take a 'q' param in querystring to search by that username.
    """

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    search = request.args.get('q')

    if not search:
        q = db.select(User).order_by(User.id.desc())

    else:
        q = db.select(User).filter(User.username.like(f"%{search}%"))

    users = dbx(q).scalars().all()

    return render_template('users/index.jinja', users=users)


@app.get('/users/<int:user_id>')
def show_user(user_id):
    """Show user profile."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = db.get_or_404(User, user_id)

    return render_template('users/show.jinja', user=user)


@app.get('/users/<int:user_id>/following')
def show_following(user_id):
    """Show list of people this user is following."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = db.get_or_404(User, user_id)
    return render_template('users/following.jinja', user=user)


@app.get('/users/<int:user_id>/followers')
def show_followers(user_id):
    """Show list of followers of this user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = db.get_or_404(User, user_id)
    return render_template('users/followers.jinja', user=user)


@app.post('/users/follow/<int:follow_id>')
def start_following(follow_id):
    """Add a follow for the currently-logged-in user.

    Redirect to following page for the current for the current user.
    """

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    form = g.csrf_form

    if form.validate_on_submit():
        followed_user = db.get_or_404(User, follow_id)
        g.user.follow(followed_user)
        db.session.commit()

        return redirect(f"/users/{g.user.id}/following")

    else:
        raise Unauthorized()


@app.post('/users/stop-following/<int:follow_id>')
def stop_following(follow_id):
    """Have currently-logged-in-user stop following this user.

    Redirect to following page for the current for the current user.
    """

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    form = g.csrf_form

    if form.validate_on_submit():
        followed_user = db.get_or_404(User, follow_id)
        g.user.unfollow(followed_user)
        db.session.commit()

        return redirect(f"/users/{g.user.id}/following")

    else:
        raise Unauthorized()


@app.route('/users/profile', methods=["GET", "POST"])
def show_or_process_edit_profile_form():
    """Update profile for current user.
    Redirects to base url if access is unauthorized
    Redirects to user detail page on successful submission
    """

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    form = UserEditForm(obj=g.user)

    if form.validate_on_submit():
        user = User.authenticate(g.user.username, form.password.data)

        if (user):
            g.user.username = form.username.data
            g.user.email = form.email.data
            g.user.image_url = form.image_url.data or DEFAULT_IMAGE_URL
            g.user.header_image_url = form.header_image_url.data or DEFAULT_HEADER_IMAGE_URL
            g.user.bio = form.bio.data

            try:
                db.session.commit()
            except IntegrityError:
                flash("Username already taken", "danger")
                db.session.rollback()
                return render_template('users/edit.jinja', form=form)

            return redirect(f"/users/{g.user.id}")

        else:
            flash('Incorrect Password. Please try again.', 'danger')

    return render_template('/users/edit.jinja', form=form)


@app.get("/users/<int:user_id>/likes")
def show_user_likes(user_id):
    """Show all messages liked by the current user"""

    if not g.user:  # or g.user.id != user_id  NOTE: make likes private/public?
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = db.get_or_404(User, user_id)
    return render_template('users/likes.jinja', user=user)


@app.post('/users/delete')
def delete_user():
    """Delete user.

    Redirect to signup page.
    """

    form = g.csrf_form

    if not g.user or not form.validate_on_submit():
        flash("Access unauthorized.", "danger")
        return redirect("/")

    do_logout()
    db.session.delete(g.user)
    db.session.commit()

    return redirect("/signup")


##############################################################################
# Messages routes:

@app.route('/messages/new', methods=["GET", "POST"])
def add_message():
    """Add a message:

    Show form if GET. If valid, update message and redirect to user page.
    """

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    form = MessageForm()

    if form.validate_on_submit():
        msg = Message(text=form.text.data)  # type: ignore
        g.user.messages.append(msg)
        db.session.commit()

        return redirect(f"/users/{g.user.id}")

    return render_template('messages/create.jinja', form=form)


@app.get('/messages/<int:message_id>')
def show_message(message_id):
    """Show a message."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    msg = db.get_or_404(Message, message_id)

    return render_template('messages/show.jinja', message=msg)


@app.post('/messages/<int:message_id>/delete')
def delete_message(message_id):
    """Delete a message.

    Check that this message was written by the current user.
    Redirect to user page on success.
    """

    form = g.csrf_form
    if not g.user or not form.validate_on_submit():
        flash("Access unauthorized.", "danger")
        return redirect("/")

    msg = db.get_or_404(Message, message_id)
    if msg.user_id != g.user.id:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    db.session.delete(msg)
    db.session.commit()

    return redirect(f"/users/{g.user.id}")


@app.post("/messages/<int:msg_id>/like")
def add_message_like(msg_id):
    """Adds message to user's liked messages"""

    form = g.csrf_form
    if not g.user or not form.validate_on_submit():
        flash("Access unauthorized.", "danger")
        return redirect("/")

    # check if trying to like user's own message
    msg = db.get_or_404(Message, msg_id)
    if msg.user_id == g.user.id:
        flash("Access unauthorized", "danger")
        return redirect("/")

    origin_url = request.form['url']

    g.user.add_like(msg_id)

    try:
        db.session.commit()

    except IntegrityError:
        flash("Already liked message", "danger")
        db.session.rollback()
        return redirect('/')

    return redirect(origin_url)

# NOTE: many websites block 'request.referrer', store origin url in form data instead


@ app.post("/messages/<int:msg_id>/unlike")
def remove_message_like(msg_id):
    """Removes message from user's liked messages"""

    form = g.csrf_form

    if not g.user or not form.validate_on_submit():
        flash("Access unauthorized.", 'danger')
        return redirect("/")

    # check if trying to unlike user's own message
    msg = db.get_or_404(Message, msg_id)
    if msg.user_id == g.user.id:
        flash("Access unauthorized", "danger")
        return redirect("/")

    origin_url = request.form['url']

    g.user.remove_like(msg_id)

    try:
        db.session.commit()

    except IntegrityError:
        flash("Already unliked message", "danger")
        db.session.rollback()
        return redirect('/')

    return redirect(origin_url)

##############################################################################
# Homepage and error pages


@ app.get('/')
def homepage():
    """Show homepage:

    - anon users: no messages
    - logged in: 100 most recent messages of self & followed_users
    """

    if g.user:
        following = g.user.following
        following_ids = [follower.id for follower in following]

        q = (
            db.select(Message)
            .where(Message.user_id.in_(following_ids)
                   | (Message.user_id == g.user.id))
            .order_by(Message.timestamp.desc())
            .limit(100)
        )

        messages = dbx(q).scalars().all()

        return render_template('home.jinja', messages=messages)

    else:
        return render_template('home-anon.jinja')


@app.after_request
def add_header(response):
    """Add non-caching headers on every request."""

    # https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control
    response.cache_control.no_store = True

    return response
