from flask import jsonify
from core import context as ctx


def register_api_routes(app):
    @app.route("/health")
    def health():
        return jsonify({
            "status": "ok",
            "processor_available": ctx.PROCESSOR_AVAILABLE,
            "processor_error": ctx.PROCESSOR_ERROR
        })

    @app.route("/api/status/<job_name>")
    def api_status(job_name):
        status = ctx.JOB_STATUS.get(job_name, {
            "done": 0,
            "total": 0,
            "percent": 0,
            "message": "Waiting...",
            "complete": False,
            "error": ""
        })

        return jsonify(status)
