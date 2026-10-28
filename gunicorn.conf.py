import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", f"0.0.0.0:{os.environ.get('PORT', '8000')}")
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
# On Turso, one request per worker process: the libsql driver keeps the whole process (every thread) waiting
# while it talks to the database, so a second thread only queues behind the first, and two threads writing at
# once can block each other until the worker is killed (a 502). Concurrency comes from worker processes.
threads = int(os.environ.get("GUNICORN_THREADS", 1 if os.environ.get("TURSO_DATABASE_URL") else 2))
# Requests that write a lot (bulk delete, large saves) wait on many round trips to Turso; don't kill them early.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 180))
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
