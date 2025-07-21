# gunicorn.conf.py
bind = "0.0.0.0:10000"
workers = 3
worker_class = "gevent"
timeout = 120
