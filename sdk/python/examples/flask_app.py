"""Flask Integration Example for Analytics SDK."""

from flask import Flask, jsonify
from analytics.client import AnalyticsClient
from analytics.middleware.flask import FlaskAnalytics

app = Flask(__name__)

# Initialize Sync Analytics Client
client = AnalyticsClient(
    endpoint="http://localhost:8000",
    write_key="apk_live_sample_flask_key_002",
    flush_interval_sec=1.0,
)

# Attach fail-open Flask extension
analytics = FlaskAnalytics(app, client=client, exclude_paths=["/health"])


@app.route("/")
def index():
    return jsonify({"service": "Flask Consumer", "status": "online"})


@app.route("/checkout", methods=["POST"])
def checkout():
    # Record custom checkout event
    client.track(
        event_name="checkout_completed",
        event_type="click",
        page_path="/checkout",
        metadata={"total": 120.50, "items": 2},
    )
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(port=5000)
