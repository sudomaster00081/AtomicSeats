from flask import Flask, render_template

app = Flask("Seater")

@app.route("/")
def home_page():

    return render_template("home.html")

app.run()