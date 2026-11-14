from flask import Flask, jsonify
from psycopg import OperationalError

from .api import api
from .errors import ApiError


def create_app():
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.register_blueprint(api)

    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(error={"code": error.code, "message": error.message}), error.status

    @app.errorhandler(OperationalError)
    def unavailable(error):
        app.logger.error("Database operation failed: %s", type(error).__name__)
        return jsonify(error={"code": "DATABASE_UNAVAILABLE", "message": "The database is unavailable."}), 503

    @app.after_request
    def disable_api_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    return app
