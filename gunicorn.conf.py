# gunicorn.conf.py
#
# This is a configuration file for Gunicorn, the production web server
# that Render uses to run your Flask application.

# The host and port to bind to. Render will automatically handle this.
bind = "0.0.0.0:10000"

# Number of worker processes. A good starting point is (2 x $CORES) + 1.
# Render's free tier has a shared CPU, so 3 is a reasonable number.
workers = 3

# The type of worker to use. 'gevent' is great for I/O-bound applications
# like this one, which spends time waiting for APIs (Firebase, Gemini).
worker_class = "gevent"

# Timeout for workers. If a worker is silent for this long, it's killed and restarted.
timeout = 120
