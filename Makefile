VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: setup install test clean

setup: $(VENV)/bin/activate install

$(VENV)/bin/activate:
	python3.13 -m venv $(VENV)

install: $(VENV)/bin/activate
	$(PIP) install -r requirements.txt

test:
	$(PYTHON) -m pytest tests/ -v

clean:
	rm -rf $(VENV)
