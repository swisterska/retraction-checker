def register_routes(app):

    @app.route("/")
    def index():
        return "<h1>System Retraction Checker is working</h1>"
