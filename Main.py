from flask import Flask, render_template, request, redirect, url_for, session
import pymysql
import datetime
import re
import random
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

app = Flask(__name__)
app.secret_key = "welcome"
app.debug = True

sid = SentimentIntensityAnalyzer()

# =====================================================
# DATABASE CONNECTION
# =====================================================
def get_db_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="root",
        database="negotiate",
        port=3306,
        cursorclass=pymysql.cursors.DictCursor
    )

# =====================================================
# CSV LOADERS
# =====================================================
def load_ecommerce_data():
    return pd.read_csv("ecommerce.csv").to_dict(orient="records")

def load_model_data():
    return pd.read_csv("model.csv").to_dict(orient="records")

# =====================================================
# PRICE CLEANER
# =====================================================
def clean_price(value):
    return float(str(value).replace(",", "").strip())

# =====================================================
# HOME
# =====================================================
@app.route("/")
@app.route("/index")
def index():
    return render_template("index.html")

# =====================================================
# SIGNUP
# =====================================================
@app.route("/Signup")
def Signup():
    return render_template("signup.html", msg="")

@app.route("/SignupAction", methods=["POST"])
def SignupAction():
    username = request.form["t1"]
    password = generate_password_hash(request.form["t2"])
    phone = request.form["t3"]
    email = request.form["t4"]
    address = request.form["t5"]
    gender = request.form["t6"]

    con = get_db_connection()
    with con:
        cur = con.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            return render_template("signup.html", msg="Username already exists")

        cur.execute("""
            INSERT INTO users (username,password,phone,email,address,gender)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (username,password,phone,email,address,gender))
        con.commit()

    return render_template("signup.html", msg="Signup successful")

# =====================================================
# LOGIN
# =====================================================
@app.route("/Login")
def Login():
    return render_template("login.html", msg="")

@app.route("/LoginAction", methods=["POST"])
def LoginAction():
    username = request.form["t1"]
    password = request.form["t2"]

    con = get_db_connection()
    with con:
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        row = cur.fetchone()

    if row and check_password_hash(row["password"], password):
        session.clear()
        session["username"] = username
        return redirect(url_for("UserScreen"))

    return render_template("login.html", msg="Invalid username or password")

@app.route("/Logout")
def Logout():
    session.clear()
    return redirect(url_for("index"))

# =====================================================
# USER DASHBOARD
# =====================================================
@app.route("/UserScreen")
def UserScreen():
    if "username" not in session:
        return redirect(url_for("Login"))
    return render_template("userscreen.html", msg="Welcome " + session["username"])

# =====================================================
# BROWSE PRODUCTS
# =====================================================
@app.route("/BrowseProducts")
def BrowseProducts():
    if "username" not in session:
        return redirect(url_for("Login"))

    products = load_ecommerce_data()
    for p in products:
        p["image"] = p["Images"].split(",")[0] if isinstance(p.get("Images"), str) else ""

    return render_template("browseproducts.html", products=products)

# =====================================================
# CHATBOT  ✅ FIXED MIN PRICE LOGIC
# =====================================================
@app.route("/Chatbot/<pid>")
def Chatbot(pid):
    if "username" not in session:
        return redirect(url_for("Login"))

    products = load_ecommerce_data()
    models = load_model_data()

    product = next((p for p in products if str(p["index"]) == pid), None)
    model = next((m for m in models if str(m["index"]) == pid), None)

    original_price = clean_price(product["Price"])

    # ✅ DATASET NEGOTIATE PRICE = ABSOLUTE MINIMUM PRICE
    min_price = clean_price(model["Negotiate"]) if model else original_price

    session.update({
        "product_id": product["index"],
        "product_name": product["Name"],
        "current_price": original_price,
        "original_price": original_price,   # ← ADD THIS LINE
        "min_price": min_price,
        "last_offer": None,
        "deal_done": False,
        "chat": f"Product: {product['Name']}\nOriginal Price: ₹{original_price}\n"
    })


    return render_template("chatbot.html", msg=session["chat"])

# =====================================================
# CHAT ACTION (NEGOTIATION LOGIC)
# =====================================================
@app.route("/ChatAction", methods=["POST"])
def ChatAction():
    user_msg = request.form["user_msg"].strip()

    # 🔹 SMART NUMBER EXTRACTION
    nums = re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", user_msg)

    if not nums:
        session["chat"] += f"\nYou: {user_msg}\nBot: Please enter a valid price."
        return render_template("chatbot.html", msg=session["chat"])

    # ✅ MISSING VARIABLES (NOW FIXED)
    offer = clean_price(nums[0])
    current = round(session["current_price"], 2)
    min_price = round(session["min_price"], 2)
    original_price = round(session["original_price"], 2)

    # ✅ OFFER GREATER THAN ORIGINAL PRICE
    if offer > original_price:
        reply = f"The original price of the product is ₹{original_price}"
        session["chat"] += f"\nYou: {user_msg}\nBot: {reply}"
        return render_template("chatbot.html", msg=session["chat"])

    # 🔹 DEAL ALREADY DONE
    if session.get("deal_done"):
        reply = f"Deal already finalized at ₹{current}"
        session["chat"] += f"\nYou: {user_msg}\nBot: {reply}"
        return render_template("chatbot.html", msg=session["chat"])

    # 🔹 ACCEPT OFFER
    if offer >= min_price:
        session["current_price"] = offer
        session["deal_done"] = True
        reply = f"Deal accepted at ₹{offer}"
    else:
        step = random.uniform(5, 15)
        counter = max(min_price, round(current - step, 2))
        session["current_price"] = counter
        reply = f"I can offer ₹{counter}"

    session["chat"] += f"\nYou: {user_msg}\nBot: {reply}"
    return render_template("chatbot.html", msg=session["chat"])


# =====================================================
# COMPLETE ORDER
# =====================================================
@app.route("/CompleteOrder", methods=["POST"])
def CompleteOrder():
    if "username" not in session or "product_id" not in session:
        return redirect(url_for("BrowseProducts"))

    try:
        con = get_db_connection()
        with con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO purchaseorder
                (username, product_id, product_name, amount, transaction_date)
                VALUES (%s,%s,%s,%s,%s)
            """, (
                session["username"],
                session["product_id"],
                session["product_name"],
                session["current_price"],
                datetime.datetime.now()
            ))
            con.commit()
    except Exception as e:
        print("DB Error:", e)
        return "Database error! Please check server logs."

    return redirect(url_for("ViewOrders"))

# =====================================================
# VIEW ORDERS
# =====================================================
@app.route("/ViewOrders")
def ViewOrders():
    if "username" not in session:
        return redirect(url_for("Login"))

    try:
        con = get_db_connection()
        with con:
            cur = con.cursor()
            cur.execute("SELECT * FROM purchaseorder WHERE username=%s", (session["username"],))
            orders = cur.fetchall()
    except Exception as e:
        print("DB Error:", e)
        orders = []

    return render_template("vieworders.html", orders=orders)

# =====================================================
# POST REVIEW
# =====================================================
@app.route("/PostReview")
def PostReview():
    if "username" not in session:
        return redirect(url_for("Login"))
    return render_template("postreview.html", msg="")

@app.route("/PostReviewAction", methods=["POST"])
def PostReviewAction():
    review = request.form["t1"]
    sentiment = sid.polarity_scores(review)["compound"]
    label = "Positive" if sentiment >= 0.05 else "Negative" if sentiment <= -0.05 else "Neutral"

    try:
        con = get_db_connection()
        with con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO reviews (username, review, sentiment)
                VALUES (%s,%s,%s)
            """, (session["username"], review, label))
            con.commit()
    except Exception as e:
        print("DB Error:", e)
        return "Database error! Please check server logs."

    return render_template("postreview.html", msg="Review submitted successfully")

# =====================================================
# VIEW REVIEWS
# =====================================================
@app.route("/ViewReview")
def ViewReview():
    try:
        con = get_db_connection()
        with con:
            cur = con.cursor()
            cur.execute("SELECT * FROM reviews")
            reviews = cur.fetchall()
    except Exception as e:
        print("DB Error:", e)
        reviews = []

    return render_template("ViewReview.html", reviews=reviews)

# =====================================================
# RUN APP
# =====================================================
if __name__ == "__main__":
    app.run(debug=True)
