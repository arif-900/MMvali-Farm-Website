# app.py - full updated (orders with payment, optional Twilio WhatsApp, tracking fixes)
import os
from datetime import datetime
import csv
import io
import urllib.parse
import smtplib
from email.message import EmailMessage
from functools import wraps

from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash, check_password_hash

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, Response, abort
)
from flask_sqlalchemy import SQLAlchemy

# Optional Twilio (for automatic WhatsApp) - install twilio if you will enable this.
try:
    from twilio.rest import Client as TwilioClient
except Exception:
    TwilioClient = None

# -------------------------
# APP & CONFIG
# -------------------------
app = Flask(__name__)
app.secret_key = "dev-secret-change-later"  # CHANGE in production
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

DB_PATH = os.path.join(INSTANCE_DIR, "mmvali_farm.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Admin credentials (change)
app.config["ADMIN_USERNAME"] = "admin"
app.config["ADMIN_PASSWORD"] = "mmvali123"

# Email config (for sending emails)
app.config["EMAIL_HOST"] = "smtp.gmail.com"
app.config["EMAIL_PORT"] = 587
app.config["EMAIL_USER"] = ""        # your SMTP user (email)
app.config["EMAIL_PASSWORD"] = ""    # SMTP password/app password
app.config["OWNER_EMAIL"] = ""       # admin notification email

# Twilio config (optional) - for automated WhatsApp messages
# To enable, install twilio: pip install twilio and fill these
app.config["TWILIO_ACCOUNT_SID"] = ""
app.config["TWILIO_AUTH_TOKEN"] = ""
app.config["TWILIO_WHATSAPP_FROM"] = "whatsapp:+14155238886"  # Twilio sandbox default (replace)

# Payment instructions (editable in code or via admin UI in future)
app.config["PAYMENT_INSTRUCTIONS"] = {
    "bank_account": "Bank: ABC Bank\nA/C: 1234567890\nIFSC: ABCD0123456\nName: MMVALI Farm",
    "upi": "mmvali@upi",
    "note": "After payment, WhatsApp / email admin with your Order ID to confirm."
}

# Token serializer
serializer = URLSafeTimedSerializer(app.secret_key)

db = SQLAlchemy(app)

# Twilio client helper
def get_twilio_client():
    sid = app.config.get("TWILIO_ACCOUNT_SID")
    token = app.config.get("TWILIO_AUTH_TOKEN")
    if sid and token and TwilioClient:
        return TwilioClient(sid, token)
    return None

# -------------------------
# MODELS
# -------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140))
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    orders = db.relationship("Order", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    customer_name = db.Column(db.String(120), nullable=False)
    customer_email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(30), nullable=False)
    address = db.Column(db.Text, nullable=False)
    product = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    total_price = db.Column(db.Integer)
    status = db.Column(db.String(20), default="Pending")  # Pending, Processing, Paid, Delivered, Cancelled
    payment_method = db.Column(db.String(20), default="COD")  # COD or ONLINE
    payment_status = db.Column(db.String(20), default="Pending")  # Pending, Paid, Failed
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Order {self.id} {self.customer_name} {self.product} x {self.quantity}>"

# -------------------------
# PRODUCTS
# -------------------------
PRODUCTS = [
    {"id": 1, "name": "Fresh Cow Milk (1L)", "description": "Pure farm fresh milk collected every morning.", "price": 60, "image": "p5.jpg"},
    {"id": 2, "name": "Milk Kova (200g)", "description": "Traditional milk sweet, rich and creamy.", "price": 180, "image": "p1.jpg"},
    {"id": 3, "name": "Paneer (200g)", "description": "Soft and fresh paneer perfect for curries.", "price": 120, "image": "p2.jpg"},
    {"id": 4, "name": "Curd (200g)", "description": "Thick, homemade-style curd.", "price": 20, "image": "p3.jpg"},
    {"id": 5, "name": "Ghee (200g)", "description": "A2 cow ghee with rich aroma and flavour.", "price": 300, "image": "p4.jpg"},
]

# -------------------------
# DB INIT
# -------------------------
with app.app_context():
    db.create_all()

# -------------------------
# HELPERS & NOTIFICATIONS
# -------------------------
def admin_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

def find_product_price(name):
    return next((p["price"] for p in PRODUCTS if p["name"] == name), 0)

def send_email(subject: str, to_email: str, body: str) -> bool:
    host = app.config.get("EMAIL_HOST")
    port = app.config.get("EMAIL_PORT")
    user = app.config.get("EMAIL_USER")
    password = app.config.get("EMAIL_PASSWORD")
    if not all([host, port, user, password, to_email]):
        print("send_email: config incomplete; skipping.")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_email
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        print(f"Email sent to {to_email}")
        return True
    except Exception as e:
        print("Error sending email:", e)
        return False

def send_whatsapp_via_twilio(to_phone: str, body_text: str) -> bool:
    """Send WhatsApp message using Twilio (if configured). Returns True/False."""
    client = get_twilio_client()
    if not client:
        print("Twilio not configured or twilio package not installed.")
        return False
    from_whatsapp = app.config.get("TWILIO_WHATSAPP_FROM")
    to_whatsapp = f"whatsapp:{to_phone}" if not str(to_phone).startswith("whatsapp:") else to_phone
    try:
        msg = client.messages.create(body=body_text, from_=from_whatsapp, to=to_whatsapp)
        print("Twilio message SID:", msg.sid)
        return True
    except Exception as e:
        print("Twilio error:", e)
        return False

def notify_admin_new_order(order: Order):
    admin_email = app.config.get("OWNER_EMAIL")
    if admin_email:
        body = f"New order #{order.id}\nCustomer: {order.customer_name}\nPhone: {order.phone}\nProduct: {order.product}\nQty: {order.quantity}\nTotal: ₹{order.total_price or 0}\nAddress:\n{order.address}"
        send_email(f"New Order #{order.id}", admin_email, body)

def notify_customer_on_status_change(order: Order):
    # email
    if order.customer_email:
        body = f"Update for your order #{order.id}\nStatus: {order.status}\nProduct: {order.product}\nQty: {order.quantity}\nTotal: ₹{order.total_price or 0}\n\nThank you,\nMMVALI Farm"
        send_email(f"Order #{order.id} status update", order.customer_email, body)
    # whatsapp via Twilio if configured
    # (we send a brief message; Twilio WhatsApp requires business approval in production)
    client = get_twilio_client()
    if client and order.phone:
        text = f"Order #{order.id} status updated to {order.status}. Product: {order.product}. Total ₹{order.total_price or 0}."
        sent = send_whatsapp_via_twilio(order.phone, text)
        if sent:
            print("WhatsApp update sent to customer via Twilio.")

# -------------------------
# ROUTES
# -------------------------
@app.route("/")
def index():
    return render_template("index.html", products=PRODUCTS)

@app.route("/products")
def products():
    return render_template("products.html", products=PRODUCTS)

@app.route("/about")
def about():
    return render_template("about.html")

# Registration / Login
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Please provide email and password.", "error")
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            flash("Email already registered. Please login.", "error")
            return redirect(url_for("login"))
        u = User(name=name, email=email)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        session["user_id"] = u.id
        session["user_email"] = u.email
        session["user_name"] = u.name
        flash("Registered and logged in.", "success")
        return redirect(url_for("profile"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            session["user_email"] = user.email
            session["user_name"] = user.name
            flash("Logged in.", "success")
            return redirect(next_url or url_for("profile"))
        flash("Invalid credentials.", "error")
    return render_template("login.html", next=next_url)

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user_email", None)
    session.pop("user_name", None)
    flash("Logged out.", "success")
    return redirect(url_for("index"))

# Password reset
@app.route("/reset-request", methods=["GET", "POST"])
def reset_request():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        # always show same message to avoid leaking whether email exists
        if user:
            token = serializer.dumps({"user_id": user.id, "email": user.email})
            link = url_for("reset_password", token=token, _external=True)
            body = f"Reset password: {link}\nValid for 1 hour. Check spam/junk if not visible."
            sent = send_email("Password Reset - MMVALI Farm", user.email, body)
            if sent:
                flash("Reset instructions sent (check spam).", "info")
            else:
                flash("Unable to send reset email. Contact admin.", "error")
        else:
            flash("If the email is registered we sent reset instructions (check spam).", "info")
        return redirect(url_for("login"))
    return render_template("reset_request.html")

@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        data = serializer.loads(token, max_age=3600)
        user_id = data.get("user_id")
    except Exception:
        flash("Invalid/expired reset link.", "error")
        return redirect(url_for("login"))
    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        password = request.form.get("password", "")
        if not password:
            flash("Provide a new password.", "error")
            return render_template("reset_password.html")
        user.set_password(password)
        db.session.commit()
        flash("Password updated. Log in.", "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html")

# Order page: user must be logged in to order
@app.route("/order", methods=["GET", "POST"])
@login_required
def order():
    if request.method == "POST":
        # form fields
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        product = request.form.get("product", "").strip()
        quantity_raw = request.form.get("quantity", "1").strip()
        notes = request.form.get("notes", "").strip()
        payment_method = request.form.get("payment_method", "COD")  # COD or ONLINE

        # validations
        if not name or not phone or not address:
            flash("Please fill name, phone and address.", "error")
            return redirect(url_for("order"))

        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                quantity = 1
        except ValueError:
            quantity = 1

        unit_price = find_product_price(product)
        total_price = unit_price * quantity

        user_id = session.get("user_id")
        user_email = session.get("user_email")

        # If payment_method == ONLINE -> redirect to pseudo-payment (simulate)
        if payment_method == "ONLINE":
            # create a temporary pending order record with payment_status pending
            new_order = Order(
                user_id=user_id,
                customer_name=name,
                customer_email=user_email,
                phone=phone,
                address=address,
                product=product,
                quantity=quantity,
                total_price=total_price,
                status="Pending",
                payment_method="ONLINE",
                payment_status="Pending",
                notes=notes
            )
            db.session.add(new_order)
            db.session.commit()
            # In real app: redirect to payment gateway with order id and amount
            # → For now we simulate payment page where user "pays" and we set payment_status accordingly
            return redirect(url_for("mock_pay", order_id=new_order.id))
        else:
            # COD: create order with payment_status 'Pending' and payment_method COD
            new_order = Order(
                user_id=user_id,
                customer_name=name,
                customer_email=user_email,
                phone=phone,
                address=address,
                product=product,
                quantity=quantity,
                total_price=total_price,
                status="Pending",
                payment_method="COD",
                payment_status="Pending",
                notes=notes
            )
            db.session.add(new_order)
            db.session.commit()

            # notify admin and customer
            notify_admin_new_order(new_order)
            # send email with tracking link if email present
            if new_order.customer_email:
                token = serializer.dumps({"order_id": new_order.id, "email": new_order.customer_email})
                link = url_for("order_success", order_id=new_order.id, token=token, _external=True)
                body = f"Thanks for your order #{new_order.id}\nTrack: {link}\nPayment: Cash on Delivery\nPayment instructions (if you want to pay online):\n{app.config['PAYMENT_INSTRUCTIONS']['bank_account']}\nUPI: {app.config['PAYMENT_INSTRUCTIONS']['upi']}"
                send_email(f"Order #{new_order.id} - MMVALI Farm", new_order.customer_email, body)

            flash("Order placed. Check your profile or email for tracking details.", "success")
            return redirect(url_for("order_success", order_id=new_order.id))

    # GET prefill user info
    user = User.query.get(session.get("user_id"))
    return render_template("order.html", products=PRODUCTS, user=user, payment_info=app.config["PAYMENT_INSTRUCTIONS"])

# Mock payment simulation page - in real integrate with a real gateway
@app.route("/mock-pay/<int:order_id>", methods=["GET", "POST"])
@login_required
def mock_pay(order_id):
    order = Order.query.get_or_404(order_id)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "success":
            order.payment_status = "Paid"
            order.status = "Paid"
            db.session.commit()
            notify_admin_new_order(order)
            # notify customer via email
            if order.customer_email:
                token = serializer.dumps({"order_id": order.id, "email": order.customer_email})
                link = url_for("order_success", order_id=order.id, token=token, _external=True)
                send_email(f"Order #{order.id} - Payment received", order.customer_email,
                           f"Payment received for order #{order.id}. Track: {link}")
            flash("Payment successful. Order confirmed.", "success")
            return redirect(url_for("order_success", order_id=order.id))
        else:
            order.payment_status = "Failed"
            db.session.commit()
            flash("Payment failed. You can try again or choose Cash on Delivery.", "error")
            return redirect(url_for("order"))
    return render_template("mock_pay.html", order=order)

@app.route("/order/success/<int:order_id>")
def order_success(order_id):
    token = request.args.get("token")
    order = Order.query.get_or_404(order_id)
    # token optional: if present, validate for safety (useful for guest link)
    if token:
        try:
            data = serializer.loads(token, max_age=60*60*24*30)  # 30 days
            if data.get("order_id") != order.id:
                flash("Invalid tracking token.", "error")
                return redirect(url_for("track"))
        except Exception:
            flash("Invalid or expired tracking link.", "error")
            return redirect(url_for("track"))
    return render_template("order_success.html", order=order, payment_info=app.config["PAYMENT_INSTRUCTIONS"])

@app.route("/track", methods=["GET", "POST"])
def track():
    result = None
    error = None
    if request.method == "POST":
        oid_raw = request.form.get("order_id", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not oid_raw:
            error = "Enter the Order ID."
            return render_template("track.html", result=None, error=error)
        try:
            oid = int(oid_raw)
        except ValueError:
            error = "Order ID must be a number."
            return render_template("track.html", result=None, error=error)
        order = Order.query.get(oid)
        if not order:
            error = "Order not found. Check the ID."
        else:
            ok = False
            if phone and phone == order.phone:
                ok = True
            if email and order.customer_email and email == order.customer_email:
                ok = True
            if session.get("user_id") and order.user_id == session.get("user_id"):
                ok = True
            if not ok:
                error = "Verification failed. Provide the phone or email used when ordering or log in."
            else:
                result = order
    return render_template("track.html", result=result, error=error)

# -------------------------
# ADMIN ROUTES
# -------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username == app.config["ADMIN_USERNAME"] and password == app.config["ADMIN_PASSWORD"]:
            session["admin_logged_in"] = True
            flash("Logged in as admin.", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("admin_orders"))
        else:
            flash("Invalid admin credentials.", "error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
@admin_login_required
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Logged out.", "success")
    return redirect(url_for("admin_login"))

@app.route("/admin/orders")
@admin_login_required
def admin_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template("admin_orders.html", orders=orders)

@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_login_required
def admin_update_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status", "Pending")
    if new_status not in ["Pending", "Processing", "Paid", "Delivered", "Cancelled"]:
        new_status = "Pending"
    order.status = new_status
    # if delivered and admin wants to auto-delete, we don't delete automatically here; admin may delete
    db.session.commit()
    notify_customer_on_status_change(order)
    flash(f"Order #{order.id} status updated to {new_status}.", "success")
    return redirect(url_for("admin_orders"))

@app.route("/admin/orders/<int:order_id>/whatsapp_owner")
@admin_login_required
def admin_order_whatsapp_owner(order_id):
    order = Order.query.get_or_404(order_id)
    msg_link = build_whatsapp_link_owner(order := order)  # not used; we'll redirect to wa.me, simpler:
    # use wa.me link (opens WhatsApp)
    text = f"New order #{order.id} - {order.product} x{order.quantity}. Customer: {order.customer_name}. Phone: {order.phone}"
    phone = app.config.get("OWNER_WHATSAPP", "").lstrip("+")
    link = f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"
    return redirect(link)

# Backwards-compatible alias for older templates that use admin_order_whatsapp
@app.route("/admin/orders/<int:order_id>/whatsapp")
@admin_login_required
def admin_order_whatsapp(order_id):
    """
    Alias route kept for compatibility. Redirects to the new admin_order_whatsapp_user endpoint
    which opens a WhatsApp chat to the customer's phone.
    """
    return redirect(url_for("admin_order_whatsapp_user", order_id=order_id))

@app.route("/admin/orders/<int:order_id>/whatsapp_user")
@admin_login_required
def admin_order_whatsapp_user(order_id):
    order = Order.query.get_or_404(order_id)
    # open WhatsApp to user phone (client side)
    text = f"Update for your order #{order.id}: Status {order.status}. Product: {order.product}. Total ₹{order.total_price or 0}."
    phone = order.phone.lstrip("+")
    link = f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"
    return redirect(link)

@app.route("/admin/orders/<int:order_id>/delete", methods=["POST"])
@admin_login_required
def admin_delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()
    flash(f"Order #{order_id} deleted.", "success")
    return redirect(url_for("admin_orders"))

@app.route("/admin/users")
@admin_login_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/users/<int:user_id>")
@admin_login_required
def admin_user_detail(user_id):
    user = User.query.get_or_404(user_id)
    orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
    return render_template("admin_user.html", user=user, orders=orders)

@app.route("/admin/orders/export/csv")
@admin_login_required
def admin_export_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Customer", "Phone", "Address", "Product", "Quantity", "TotalPrice", "Status", "PaymentMethod", "PaymentStatus", "Email", "UserID", "Notes", "CreatedAt"])
    for o in orders:
        writer.writerow([
            o.id, o.customer_name, o.phone, o.address, o.product,
            o.quantity, o.total_price or 0, o.status or "", o.payment_method or "",
            o.payment_status or "", o.customer_email or "", o.user_id or "",
            (o.notes or "").replace("\n", " "), o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else ""
        ])
    csv_data = output.getvalue(); output.close()
    response = Response(csv_data, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=orders.csv"})
    return response

# -------------------------
# PROFILE
# -------------------------
@app.route("/profile")
@login_required
def profile():
    user = User.query.get_or_404(session.get("user_id"))
    orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
    return render_template("profile.html", user=user, orders=orders)

# -------------------------
# UTIL: small build_whatsapp_link_owner helper (unused main) - keep for reference
# -------------------------
def build_whatsapp_link_owner(order: Order) -> str:
    text = f"New order #{order.id} - {order.product} x{order.quantity}. Customer: {order.customer_name}. Phone: {order.phone}"
    phone = app.config.get("OWNER_WHATSAPP", "").lstrip("+")
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# -------------------------
# POLICY
# -------------------------
@app.route("/terms")
def terms():
    return render_template("terms.html")
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")
@app.route("/refund")
def refund():
    return render_template("refund.html")

# -------------------------
# MAIN
# -------------------------

# --- Admin product/settings helpers (paste into app.py) ---
import json

PRODUCTS_JSON = os.path.join(INSTANCE_DIR, "products.json")
SETTINGS_JSON = os.path.join(INSTANCE_DIR, "settings.json")

# Ensure default files exist
def ensure_products_file():
    if not os.path.exists(PRODUCTS_JSON):
        default = [
            {"id": 1, "name": "Fresh Cow Milk (1L)", "price": 60, "description": "Fresh milk", "image": "p1.jpg"},
            {"id": 2, "name": "Milk Kova (250g)", "price": 180, "description": "Milk sweet", "image": "p2.jpg"},
            {"id": 3, "name": "Paneer (250g)", "price": 120, "description": "Paneer", "image": "p3.jpg"},
        ]
        with open(PRODUCTS_JSON, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)

def load_products():
    ensure_products_file()
    with open(PRODUCTS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def save_products(products):
    with open(PRODUCTS_JSON, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2)

def ensure_settings_file():
    if not os.path.exists(SETTINGS_JSON):
        default = {
            "owner_whatsapp": app.config.get("OWNER_WHATSAPP", "+919876543210"),
            "owner_email": app.config.get("OWNER_EMAIL", ""),
            "payment_instructions": app.config.get("PAYMENT_INSTRUCTIONS", {})
        }
        with open(SETTINGS_JSON, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)

def load_settings():
    ensure_settings_file()
    with open(SETTINGS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def save_settings(settings):
    with open(SETTINGS_JSON, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

# --- Admin Dashboard route ---
@app.route("/admin")
@admin_login_required
def admin_dashboard():
    # summary metrics
    total_orders = Order.query.count()
    total_users = User.query.count()
    total_revenue = db.session.query(db.func.sum(Order.total_price)).scalar() or 0
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(6).all()
    products = load_products()
    settings = load_settings()
    return render_template(
        "admin_dashboard.html",
        total_orders=total_orders,
        total_users=total_users,
        total_revenue=int(total_revenue),
        recent_orders=recent_orders,
        products=products,
        settings=settings,
    )

# --- Admin Products CRUD (JSON-backed) ---
@app.route("/admin/products")
@admin_login_required
def admin_products():
    products = load_products()
    return render_template("admin_products.html", products=products)

@app.route("/admin/products/add", methods=["POST"])
@admin_login_required
def admin_products_add():
    data = request.form
    products = load_products()
    # compute new id
    new_id = max((p["id"] for p in products), default=0) + 1
    item = {
        "id": new_id,
        "name": data.get("name").strip(),
        "price": int(data.get("price") or 0),
        "description": data.get("description", "").strip(),
        "image": data.get("image", "").strip() or f"p{new_id}.jpg"
    }
    products.append(item)
    save_products(products)
    flash("Product added.", "success")
    return redirect(url_for("admin_products"))

@app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
@admin_login_required
def admin_products_edit(pid):
    products = load_products()
    product = next((p for p in products if p["id"] == pid), None)
    if not product:
        abort(404)
    if request.method == "POST":
        product["name"] = request.form.get("name").strip()
        product["price"] = int(request.form.get("price") or 0)
        product["description"] = request.form.get("description", "").strip()
        product["image"] = request.form.get("image", "").strip() or product.get("image")
        save_products(products)
        flash("Product updated.", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin_product_edit.html", product=product)

@app.route("/admin/products/<int:pid>/delete", methods=["POST"])
@admin_login_required
def admin_products_delete(pid):
    products = load_products()
    new = [p for p in products if p["id"] != pid]
    save_products(new)
    flash("Product removed.", "success")
    return redirect(url_for("admin_products"))

# --- Admin settings editor ---
@app.route("/admin/settings", methods=["GET", "POST"])
@admin_login_required
def admin_settings():
    if request.method == "POST":
        settings = load_settings()
        settings["owner_whatsapp"] = request.form.get("owner_whatsapp", settings.get("owner_whatsapp"))
        settings["owner_email"] = request.form.get("owner_email", settings.get("owner_email"))
        payment_instructions = {
            "bank_account": request.form.get("bank_account", settings.get("payment_instructions", {}).get("bank_account", "")),
            "upi": request.form.get("upi", settings.get("payment_instructions", {}).get("upi", "")),
            "note": request.form.get("note", settings.get("payment_instructions", {}).get("note", ""))
        }
        settings["payment_instructions"] = payment_instructions
        save_settings(settings)
        flash("Settings updated.", "success")
        return redirect(url_for("admin_settings"))
    settings = load_settings()
    return render_template("admin_settings.html", settings=settings)

if __name__ == "__main__":
    app.run(debug=True)
