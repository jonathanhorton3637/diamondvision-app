from flask import send_from_directory


def register_static_routes(app):
    @app.route("/manifest.json")
    def manifest():
        return send_from_directory("static", "manifest.json")

    @app.route("/service-worker.js")
    def service_worker():
        return send_from_directory("static", "service-worker.js")
