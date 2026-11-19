PY    ?= python3
VENV  := .venv
BIN   := $(VENV)/bin
DOOR  ?= D03

.PHONY: all build test check demo dist clean

## make            — тесты + полная сборка (out/: .xlsx, .blend, рендеры, наложение на PDF)
all: test build

$(BIN)/activate: requirements.txt
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install -q -r requirements.txt
	touch $(BIN)/activate

build: $(BIN)/activate
	$(BIN)/python build.py

test: $(BIN)/activate
	$(BIN)/python -m pytest -q

## make check     — только проверка plan.json, Excel и наложение (без Blender)
check: $(BIN)/activate
	$(BIN)/python build.py --skip-blender --out out_check

## make demo DOOR=D03 — дверь шире на 100 мм на копии входа, сравнение до/после
demo: $(BIN)/activate
	$(BIN)/python scripts/demo_change.py --opening $(DOOR) --delta 100 --with-blender

## make dist     — архив для сдачи: код, plan.json, исходный PDF, результаты out/ и out_variant/
dist: build demo
	rm -rf dist && mkdir -p dist
	zip -qr dist/apartment-takehome.zip README.md Makefile requirements.txt build.py \
	    src blender scripts tools tests data video/build_video.py video/blender_orbit.py video/narration.txt \
	    out out_variant out_variant.input -x '*/__pycache__/*' '*.pyc' '*.DS_Store' 'out_variant/top.png' 'out_variant/iso.png'
	@echo "dist/apartment-takehome.zip"

clean:
	rm -rf out out.tmp out_check out_check.tmp out_variant out_variant.tmp out_variant.input \
	       out_base_for_demo out_base_for_demo.tmp dist $(VENV)
