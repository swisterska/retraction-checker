
import os
from flask import Flask
from app.routes import register_routes
from app.database import db



def create_app(test_config=None):
    app = Flask(
        __name__,
        instance_path=os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "instance")
        ),
    )

    os.makedirs(app.instance_path, exist_ok=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + os.path.join(app.instance_path, "retraction_checker.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if test_config:
        app.config.update(test_config)

    db.init_app(app)

    register_routes(app)

    with app.app_context():
        from app.models import (
            User,
            UploadedDocument,
            ExtractedReference,
            RetractedPublication,
            DetectionResult,
            Notification,
        )
        db.create_all()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
