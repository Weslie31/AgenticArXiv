PY ?= python3

.PHONY: start stop restart status logs install install-locked run

install:
	$(PY) scripts/bootstrap.py

install-locked:
	$(PY) scripts/bootstrap.py --locked

start:
	$(PY) scripts/service.py start

stop:
	$(PY) scripts/service.py stop

restart: stop start

status:
	$(PY) scripts/service.py status

logs:
	$(PY) scripts/service.py logs -n 120 --follow

run: start
