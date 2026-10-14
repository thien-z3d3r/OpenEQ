PREFIX ?= /usr/local
PYTHON ?= python3
DESTDIR ?=

all:
	@echo "OpenEQ - Peace Equalizer APO fork for Linux"
	@echo "Usage:"
	@echo "  make run        Run the GTK4 GUI directly"
	@echo "  make test       Run test suite"
	@echo "  make install    Install system-wide to $(PREFIX)"
	@echo "  make user-install Install to ~/.local"
	@echo "  make uninstall  Uninstall from $(PREFIX)"

run:
	$(PYTHON) -m openeq gui

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py"

install:
	install -d $(DESTDIR)$(PREFIX)/lib/python3/dist-packages/openeq
	install -m 644 openeq/*.py $(DESTDIR)$(PREFIX)/lib/python3/dist-packages/openeq/
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 755 bin/openeq $(DESTDIR)$(PREFIX)/bin/openeq
	install -d $(DESTDIR)$(PREFIX)/share/applications
	install -m 644 data/io.github.openeq.desktop $(DESTDIR)$(PREFIX)/share/applications/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps
	install -m 644 data/io.github.openeq.svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/
	install -d $(DESTDIR)$(PREFIX)/lib/systemd/user
	install -m 644 data/openeq.service $(DESTDIR)$(PREFIX)/lib/systemd/user/
	install -d $(DESTDIR)$(PREFIX)/share/openeq/presets
	install -m 644 presets/*.txt $(DESTDIR)$(PREFIX)/share/openeq/presets/

user-install:
	pip install --user .
	install -d $(HOME)/.local/share/applications
	install -m 644 data/io.github.openeq.desktop $(HOME)/.local/share/applications/
	install -d $(HOME)/.local/share/icons/hicolor/scalable/apps
	install -m 644 data/io.github.openeq.svg $(HOME)/.local/share/icons/hicolor/scalable/apps/
	install -d $(HOME)/.config/systemd/user
	install -m 644 data/openeq.service $(HOME)/.config/systemd/user/
	install -d $(HOME)/.config/openeq/presets
	install -m 644 presets/*.txt $(HOME)/.config/openeq/presets/

uninstall:
	rm -rf $(DESTDIR)$(PREFIX)/lib/python3/dist-packages/openeq
	rm -f $(DESTDIR)$(PREFIX)/bin/openeq
	rm -f $(DESTDIR)$(PREFIX)/share/applications/io.github.openeq.desktop
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/io.github.openeq.svg
	rm -f $(DESTDIR)$(PREFIX)/lib/systemd/user/openeq.service
	rm -rf $(DESTDIR)$(PREFIX)/share/openeq

.PHONY: all run test install user-install uninstall
